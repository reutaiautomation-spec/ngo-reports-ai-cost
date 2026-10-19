"""Component 1 (correct version): all financial calculations in code, $0.

The AI only ever receives the output of `metrics()` / `summary_text()`.
"""
from __future__ import annotations


def _pct(part: float, whole: float) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def _growth(new: float, old: float) -> float | None:
    return round(100.0 * (new - old) / old, 1) if old else None


def metrics(fin: dict) -> dict:
    years = sorted(fin["years"])
    out: dict = {"org_id": fin["org_id"], "years": years, "by_year": {}}
    prev = None
    for y in years:
        d = fin["years"][y]
        inc, exp = d["income"], d["expenses"]
        ti, te = sum(inc.values()), sum(exp.values())
        individual = inc.get("תרומות מיחידים", 0)
        program = exp.get("תוכניות ופעילות", 0)
        overhead = exp.get("הנהלה וכלליות", 0) + exp.get("גיוס משאבים", 0)
        grants = d.get("grants", [])
        m = {
            "income_total": ti,
            "expense_total": te,
            "surplus": ti - te,
            "income_by_source": inc,
            "income_share_pct": {k: _pct(v, ti) for k, v in inc.items()},
            "expenses_by_category": exp,
            "expense_share_pct": {k: _pct(v, te) for k, v in exp.items()},
            "program_expense_pct": _pct(program, te),
            "overhead_pct": _pct(overhead, te),
            "donors": d.get("donors"),
            "avg_individual_donation": round(individual / d["donors"]) if d.get("donors") else None,
            "beneficiaries": d.get("beneficiaries"),
            "cost_per_beneficiary": round(te / d["beneficiaries"]) if d.get("beneficiaries") else None,
            "grants_total": sum(g["amount"] for g in grants),
            "grants_count": len(grants),
            "largest_grant": max(grants, key=lambda g: g["amount"]) if grants else None,
        }
        if prev:
            p = out["by_year"][prev]
            m["growth_pct"] = {
                "income_total": _growth(ti, p["income_total"]),
                "expense_total": _growth(te, p["expense_total"]),
                "donors": _growth(m["donors"], p["donors"]) if m["donors"] and p["donors"] else None,
                "beneficiaries": _growth(m["beneficiaries"], p["beneficiaries"]) if m["beneficiaries"] and p["beneficiaries"] else None,
                "income_by_source": {k: _growth(v, p["income_by_source"].get(k, 0)) for k, v in inc.items()},
            }
        out["by_year"][y] = m
        prev = y
    first, last = out["by_year"][years[0]], out["by_year"][years[-1]]
    n = len(years) - 1
    out["cagr_income_pct"] = round(100 * ((last["income_total"] / first["income_total"]) ** (1 / n) - 1), 1) if n else None
    return out


def _ils(x: float | int | None) -> str:
    return "—" if x is None else f"{x:,.0f} ש\"ח"


def _p(x: float | None) -> str:
    return "—" if x is None else f"{x:+.1f}%"


def summary_text(m: dict, years: list[str] | None = None) -> str:
    """Hebrew, prompt-ready summary of precomputed metrics (no raw ledger)."""
    lines = []
    for y in years or m["years"]:
        d = m["by_year"][y]
        g = d.get("growth_pct", {})
        lines.append(f"### שנת {y}")
        lines.append(f"- סך הכנסות: {_ils(d['income_total'])}" + (f" (שינוי משנה קודמת: {_p(g.get('income_total'))})" if g else ""))
        lines.append(f"- סך הוצאות: {_ils(d['expense_total'])}" + (f" (שינוי: {_p(g.get('expense_total'))})" if g else ""))
        lines.append(f"- {'עודף' if d['surplus'] >= 0 else 'גירעון'}: {_ils(abs(d['surplus']))}")
        lines.append("- הכנסות לפי מקור: " + "; ".join(
            f"{k}: {_ils(v)} ({d['income_share_pct'][k]}%)" for k, v in d["income_by_source"].items()))
        lines.append("- הוצאות לפי סעיף: " + "; ".join(
            f"{k}: {_ils(v)} ({d['expense_share_pct'][k]}%)" for k, v in d["expenses_by_category"].items()))
        lines.append(f"- שיעור הוצאות הנהלה וגיוס: {d['overhead_pct']}%")
        lines.append(f"- מספר תורמים: {d['donors']:,}" + (f" (שינוי: {_p(g.get('donors'))})" if g else ""))
        lines.append(f"- תרומה ממוצעת מיחיד: {_ils(d['avg_individual_donation'])}")
        lines.append(f"- מספר מוטבים: {d['beneficiaries']:,}" + (f" (שינוי: {_p(g.get('beneficiaries'))})" if g else ""))
        lines.append(f"- עלות למוטב: {_ils(d['cost_per_beneficiary'])}")
        if d["largest_grant"]:
            lg = d["largest_grant"]
            lines.append(f"- מענקים: {d['grants_count']} מענקים בסך {_ils(d['grants_total'])}; "
                         f"הגדול ביותר: {lg['grantor']} — {_ils(lg['amount'])}")
    if m.get("cagr_income_pct") is not None and not years:
        lines.append(f"\nצמיחה שנתית ממוצעת בהכנסות ({m['years'][0]}–{m['years'][-1]}): {m['cagr_income_pct']}%")
    return "\n".join(lines)
