"""Deterministic 3-year financial data for each synthetic org.

Output format (finance.json) is the same one real data must follow — see README.
"""
from __future__ import annotations

import random

YEARS = [2023, 2024, 2025]
GRANT_SOURCES = {"foundation": "קרנות ופילנתרופיה", "government": "מענקים ממשלתיים ורשויות"}
GRANT_PURPOSES = ["הרחבת פעילות", "תמיכה שוטפת", "פיתוח תוכנית חדשה", "הכשרת צוות", "ציוד ותשתיות"]


def _r(x: float) -> int:
    return int(round(x / 1000.0)) * 1000


def _split(total: int, n: int, rng: random.Random) -> list[int]:
    weights = [rng.uniform(0.6, 1.6) for _ in range(n)]
    s = sum(weights)
    parts = [_r(total * w / s) for w in weights]
    parts[0] += total - sum(parts)          # keep the exact total
    return parts


def generate(org: dict) -> dict:
    f = org["finance"]
    rng = random.Random(org["id"])
    income_total = f["base_income"]
    years = {}
    for i, year in enumerate(YEARS):
        if i > 0:
            income_total = income_total * (1 + f["growth"][i - 1])
        income = {src: _r(income_total * share * rng.uniform(0.98, 1.02)) for src, share in f["mix"].items()}
        total_in = sum(income.values())
        expense_total = total_in * f["expense_ratio"][i]
        expenses = {cat: _r(expense_total * share * rng.uniform(0.97, 1.03)) for cat, share in f["expense_mix"].items()}

        grants = []
        for kind, source in GRANT_SOURCES.items():
            grantors = [g for g, k in f["grantors"] if k == kind]
            # each grant-funded income line is split across that kind's grantors
            for (grantor, amount) in zip(grantors, _split(income[source], len(grantors), rng)):
                grants.append({"grantor": grantor, "type": kind, "amount": amount,
                               "purpose": rng.choice(GRANT_PURPOSES)})
        grants.sort(key=lambda g: -g["amount"])

        years[str(year)] = {
            "income": income,
            "expenses": expenses,
            "donors": f["donors"][i],
            "beneficiaries": org["beneficiaries"][year],
            "grants": grants,
        }
    return {"org_id": org["id"], "currency": "ILS", "years": years}
