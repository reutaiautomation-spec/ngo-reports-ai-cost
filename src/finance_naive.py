"""Component 1 (naive version): raw financial data to Sonnet, asking it to compute the metrics.

Used for cost estimates (count_tokens) for every org, and run for real once to show the
accuracy risk: its numbers are compared with the code's.
"""
from __future__ import annotations

import json

from . import llm
from .settings import model_for

COMPONENT = "finance"

FIELDS = ["income_total", "expense_total", "surplus", "income_growth_pct", "expense_growth_pct",
          "donors_growth_pct", "overhead_pct", "program_expense_pct", "avg_individual_donation",
          "cost_per_beneficiary", "grants_total", "largest_grant_amount"]

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["years"],
    "properties": {"years": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["year"] + FIELDS,
        "properties": {"year": {"type": "string"}, **{f: {"type": "number"} for f in FIELDS}}}}},
}

INSTRUCTIONS = """לפניך הנתונים הכספיים הגולמיים של עמותה. חשב לכל שנה:
income_total, expense_total, surplus (הכנסות פחות הוצאות),
income_growth_pct / expense_growth_pct / donors_growth_pct (שינוי באחוזים לעומת השנה הקודמת, 0 לשנה הראשונה),
overhead_pct (הנהלה וכלליות + גיוס משאבים, באחוזים מסך ההוצאות), program_expense_pct (תוכניות ופעילות באחוזים מסך ההוצאות),
avg_individual_donation (תרומות מיחידים חלקי מספר התורמים), cost_per_beneficiary (סך הוצאות חלקי מוטבים),
grants_total (סכום כל המענקים), largest_grant_amount.
אחוזים — עם ספרה אחת אחרי הנקודה. סכומים — מעוגלים לשקל. החזר JSON בלבד."""


def request(fin: dict, structured: bool = True) -> llm.Req:
    return llm.Req(custom_id=f"naive_finance__{fin['org_id']}", model=model_for("naive"),
                   user=f"{INSTRUCTIONS}\n\n```json\n{json.dumps(fin, ensure_ascii=False, indent=1)}\n```",
                   max_tokens=6000, effort="medium", json_schema=SCHEMA if structured else None,
                   org_id=fin["org_id"])


def expected(metrics: dict) -> dict[str, dict]:
    """The code's answer, in the same shape as the model's."""
    out = {}
    for y, d in metrics["by_year"].items():
        g = d.get("growth_pct", {})
        out[y] = {
            "income_total": d["income_total"], "expense_total": d["expense_total"], "surplus": d["surplus"],
            "income_growth_pct": g.get("income_total", 0) or 0, "expense_growth_pct": g.get("expense_total", 0) or 0,
            "donors_growth_pct": g.get("donors", 0) or 0, "overhead_pct": d["overhead_pct"],
            "program_expense_pct": d["program_expense_pct"], "avg_individual_donation": d["avg_individual_donation"],
            "cost_per_beneficiary": d["cost_per_beneficiary"], "grants_total": d["grants_total"],
            "largest_grant_amount": d["largest_grant"]["amount"] if d["largest_grant"] else 0,
        }
    return out


def compare(model_out: dict, metrics: dict) -> list[dict]:
    exp = expected(metrics)
    rows = []
    for item in model_out["years"]:
        y = str(item["year"])
        if y not in exp:
            continue
        for f in FIELDS:
            want, got = exp[y][f], item[f]
            tol = 0.05 if f.endswith("pct") else 1.0
            rows.append({"year": y, "field": f, "code": want, "ai": got, "ok": abs(float(got) - float(want)) <= tol})
    return rows
