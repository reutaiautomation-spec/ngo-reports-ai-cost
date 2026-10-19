"""Shared UI helpers: RTL styling, number formatting, cached data access, chart palette."""
from __future__ import annotations

import json
from html import escape

import pandas as pd
import streamlit as st

from src import costs, db
from src.settings import ROOT

# reference palette, first three categorical slots (validated all-pairs, light + dark)
COLORS = {"correct": "#2a78d6", "naive": "#eb6834", "middle": "#1baf7a"}
COLORS_DARK = {"correct": "#3987e5", "naive": "#d95926", "middle": "#199e70"}
LABELS = {"naive": "נאיבי", "middle": "ביניים (Sonnet + Batch/Cache, בלי RAG)", "correct": "ארכיטקטורה נכונה"}


def inject_rtl() -> None:
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700&display=swap');
html, body, .stApp, [data-testid="stSidebar"] { direction: rtl; font-family: 'Heebo', sans-serif; }
.stApp p, .stApp li, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp label,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stCaptionContainer"] { text-align: right; }
[data-testid="stPlotlyChart"], code, pre, .ltr { direction: ltr; }
/* never truncate metrics or buttons with an ellipsis: wrap labels, shrink values to fit */
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] *, [data-testid="stMetricValue"], [data-testid="stMetricValue"] *,
[data-testid="stMetricDelta"], [data-testid="stMetricDelta"] *, .stButton button, .stButton button * {
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }
[data-testid="stMetricValue"] { direction: ltr; justify-content: flex-end; text-align: right;
  font-size: clamp(1.25rem, 2.1vw, 2.25rem) !important; line-height: 1.2; overflow-wrap: anywhere; }
[data-testid="stMetricLabel"] { height: auto !important; min-height: 1.5rem; }
.stButton button { height: auto !important; min-height: 2.5rem; padding-top: .45rem; padding-bottom: .45rem;
  line-height: 1.35; text-align: right; }
.cost-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
.cost-table th, .cost-table td { padding: 8px 10px; border-bottom: 1px solid rgba(128,128,128,.25); text-align: right; }
.cost-table th { font-weight: 500; opacity: .75; }
.cost-table td.num { font-variant-numeric: tabular-nums; direction: ltr; text-align: right; }
.cost-table tr.total td { font-weight: 700; border-top: 2px solid rgba(128,128,128,.5); }
.pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: .85rem;
        border: 1px solid rgba(128,128,128,.4); }
.report-box { border: 1px solid rgba(128,128,128,.3); border-radius: 8px; padding: 8px 20px; }
</style>""", unsafe_allow_html=True)


def usd(x: float | None, big: bool = False) -> str:
    if x is None or pd.isna(x):
        return "—"
    if big or abs(x) >= 100:
        return f"${x:,.0f}"
    if abs(x) >= 1:
        return f"${x:,.2f}"
    if abs(x) >= 0.01:
        return f"${x:.3f}"
    return f"${x:.5f}"


def pct(x: float | None) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:.0f}%"


def html_table(df: pd.DataFrame, num_cols: set[str], total_last: bool = False) -> str:
    head = "".join(f"<th>{escape(str(c))}</th>" for c in df.columns)
    body = []
    for i, row in enumerate(df.itertuples(index=False)):
        cls = ' class="total"' if total_last and i == len(df) - 1 else ""
        cells = "".join(f'<td class="num">{v}</td>' if c in num_cols else f"<td>{v}</td>"
                        for c, v in zip(df.columns, row))
        body.append(f"<tr{cls}>{cells}</tr>")
    return f'<table class="cost-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


@st.cache_data(ttl=20)
def calls() -> pd.DataFrame:
    return costs.load_calls()


@st.cache_data(ttl=60)
def orgs() -> list[dict]:
    return db.list_orgs()


@st.cache_data(ttl=60)
def docs_table() -> pd.DataFrame:
    rows = []
    for o in orgs():
        rows += [{"org_id": o["id"], **d} for d in db.documents(o["id"])]
    return pd.DataFrame(rows)


def results_json(name: str):
    f = ROOT / "data" / "results" / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def org_picker(key: str = "org") -> dict:
    os_ = orgs()
    if not os_:
        st.warning("אין עדיין עמותות במסד הנתונים — הרץ את סקריפט הקליטה (02_ingest.py).")
        st.stop()
    names = {o["id"]: f"{o['name']} ({o['field']})" for o in os_}
    oid = st.selectbox("עמותה", list(names), format_func=names.get, key=key)
    return next(o for o in os_ if o["id"] == oid)
