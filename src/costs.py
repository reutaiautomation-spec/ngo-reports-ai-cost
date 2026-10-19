"""Aggregates the api_calls ledger into the comparison tables and the 12-month forecast."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import ledger
from .pricing import Usage, claude_cost
from .settings import config, model_for

COMPONENTS = [
    ("finance", "1. חישובים כספיים"),
    ("ingest", "2. קליטת מסמכים"),
    ("card", "3. כרטיס עמותה"),
    ("report", "4. הפקת דוח"),
    ("chat", "5. שאלות חופשיות"),
]


def load_calls() -> pd.DataFrame:
    """Local ledger (mirrors the Supabase api_calls table, which scripts keep in sync)."""
    df = pd.DataFrame(ledger.rows())
    if df.empty:
        return pd.DataFrame(columns=["component", "kind", "cost_usd", "org_id", "model", "ref",
                                     "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens"])
    return df


def component_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, label in COMPONENTS:
        c = df[df["component"] == key]
        actual = c[c["kind"] == "actual"]["cost_usd"].sum()
        naive = c[c["kind"] == "naive_estimate"]["cost_usd"].sum()
        middle = c[c["kind"] == "middle_estimate"]["cost_usd"].sum()
        rows.append({"רכיב": label, "key": key, "נאיבי": naive, "ביניים": middle, "בפועל": actual,
                     "חיסכון $": naive - actual, "חיסכון %": (100 * (naive - actual) / naive) if naive else None,
                     "קריאות": int((c["kind"] == "actual").sum())})
    t = pd.DataFrame(rows)
    total = {"רכיב": "סה\"כ", "key": "total", "נאיבי": t["נאיבי"].sum(), "ביניים": t["ביניים"].sum(),
             "בפועל": t["בפועל"].sum(), "קריאות": t["קריאות"].sum()}
    total["חיסכון $"] = total["נאיבי"] - total["בפועל"]
    total["חיסכון %"] = 100 * total["חיסכון $"] / total["נאיבי"] if total["נאיבי"] else None
    return pd.concat([t, pd.DataFrame([total])], ignore_index=True)


def spent_summary(df: pd.DataFrame) -> dict:
    by_kind = df.groupby("kind")["cost_usd"].sum().to_dict() if not df.empty else {}
    return {"actual": by_kind.get("actual", 0.0), "setup": by_kind.get("setup", 0.0),
            "validation": by_kind.get("naive_validation", 0.0),
            "total_spent": sum(by_kind.get(k, 0.0) for k in ledger.SPENT_KINDS),
            "budget": config()["budget"]["hard_limit_usd"]}


# ───────────────────────── forecast ─────────────────────────
@dataclass
class Units:
    """Measured per-unit numbers that drive the forecast."""
    ingest_per_doc: float
    card_per_doc: float
    report: float
    chat_per_q: float
    doc_tokens: float                 # avg Claude tokens per document
    report_overhead_tokens: float     # naive report input that is not documents (instructions, raw finance)
    chat_overhead_tokens: float
    card_overhead_tokens: float
    report_output: float
    chat_output: float
    card_output: float
    naive_finance: float              # naive component-1 call per report


def _avg(s: pd.Series, default: float = 0.0) -> float:
    return float(s.mean()) if len(s) else default


def measure_units(df: pd.DataFrame, docs: pd.DataFrame) -> Units:
    """docs: columns org_id, n_tokens (one row per document)."""
    act = df[df["kind"] == "actual"]
    est = df[df["kind"] == "naive_estimate"]
    n_docs = max(len(docs), 1)
    org_tokens = docs.groupby("org_id")["n_tokens"].sum().to_dict()
    org_docs = docs.groupby("org_id").size().to_dict()

    rep = est[est["component"] == "report"]
    rep_over = [r.input_tokens - org_tokens.get(r.org_id, 0) for r in rep.itertuples()]
    chat = est[est["component"] == "chat"]
    chat_over = [r.input_tokens - org_tokens.get(r.org_id, 0) for r in chat.itertuples()]
    # last card estimate per org has the full history as input
    card = est[est["component"] == "card"]
    card_last = card.groupby("org_id").tail(1)
    card_over = [r.input_tokens - org_tokens.get(r.org_id, 0) for r in card_last.itertuples()]

    report_actual = act[act["component"] == "report"].groupby("org_id")["cost_usd"].sum()
    chat_actual = act[act["component"] == "chat"].groupby("ref")["cost_usd"].sum()
    return Units(
        ingest_per_doc=act[act["component"] == "ingest"]["cost_usd"].sum() / n_docs,
        card_per_doc=act[(act["component"] == "card")]["cost_usd"].sum() / max(int((act["component"] == "card").sum()), 1),
        report=_avg(report_actual),
        chat_per_q=_avg(chat_actual),
        doc_tokens=float(docs["n_tokens"].mean()) if len(docs) else 4000.0,
        report_overhead_tokens=_avg(pd.Series(rep_over), 3000),
        chat_overhead_tokens=_avg(pd.Series(chat_over), 300),
        card_overhead_tokens=_avg(pd.Series(card_over), 600),
        report_output=_avg(rep["output_tokens"], 2000),
        chat_output=_avg(chat["output_tokens"], 200),
        card_output=_avg(card["output_tokens"], 2500),
        naive_finance=_avg(est[est["component"] == "finance"]["cost_usd"]),
    )


def _sonnet(inp: float, out: float, batch: bool = False, cache_write: float = 0, cache_read: float = 0) -> float:
    return claude_cost(model_for("naive"), Usage(input_tokens=int(inp), output_tokens=int(out),
                                                 cache_write_tokens=int(cache_write), cache_read_tokens=int(cache_read)),
                       batch=batch)


def forecast(u: Units, orgs: int, months: int, docs_pm: int, reports_pm: int, questions_pm: int,
             start_docs: int = 0, session: int | None = None) -> pd.DataFrame:
    """Monthly cost for the whole fleet. History (and so naive cost) grows by docs_pm per month."""
    session = session or config()["middle"]["chat_questions_per_session"]
    ctx_limit = 1_000_000
    rows = []
    for m in range(1, months + 1):
        hist_end = start_docs + docs_pm * m                       # documents at end of month
        hist_tokens = hist_end * u.doc_tokens

        correct = docs_pm * (u.ingest_per_doc + u.card_per_doc) + reports_pm * u.report + questions_pm * u.chat_per_q

        # naive: every card rebuild / report / question re-reads the whole history
        card_n = sum(_sonnet(u.card_overhead_tokens + (hist_end - docs_pm + k) * u.doc_tokens, u.card_output)
                     for k in range(1, docs_pm + 1))
        rep_in = u.report_overhead_tokens + hist_tokens
        report_n = reports_pm * (_sonnet(rep_in, u.report_output) + u.naive_finance)
        chat_in = u.chat_overhead_tokens + hist_tokens
        chat_n = questions_pm * _sonnet(chat_in, u.chat_output)
        naive = card_n + report_n + chat_n

        # middle: same inputs, Batch for async work, caching within chat sessions
        card_mid = card_n * 0.5
        report_mid = reports_pm * (_sonnet(rep_in, u.report_output, batch=True) + u.naive_finance * 0.5)
        sessions_full, rem = divmod(questions_pm, session)
        n_write = sessions_full + (1 if rem else 0)
        n_read = questions_pm - n_write
        prefix = chat_in - 50
        chat_mid = (n_write * _sonnet(50, u.chat_output, cache_write=prefix)
                    + n_read * _sonnet(50, u.chat_output, cache_read=prefix))
        middle = card_mid + report_mid + chat_mid

        rows.append({
            "חודש": m, "מסמכים בהיסטוריה": hist_end, "טוקנים בהיסטוריה": int(hist_tokens),
            "נאיבי": naive * orgs, "ביניים": middle * orgs, "נכון": correct * orgs,
            "נאיבי — דוח": report_n * orgs, "נאיבי — צ'אט": chat_n * orgs, "נאיבי — כרטיס": card_n * orgs,
            "נכון — דוח": reports_pm * u.report * orgs, "נכון — צ'אט": questions_pm * u.chat_per_q * orgs,
            "נכון — קליטה וכרטיס": docs_pm * (u.ingest_per_doc + u.card_per_doc) * orgs,
            "חורג מחלון ההקשר": max(rep_in, chat_in) > ctx_limit,
        })
    return pd.DataFrame(rows)
