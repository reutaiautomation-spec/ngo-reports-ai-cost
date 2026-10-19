"""Automatic report quality checks.

1. Known facts: the 5 facts per org must appear in the report with the right value.
2. Unsupported numbers: every number in the report must exist somewhere in the org's data
   (computed financials, documents, card). Numbers < 10 and years are ignored.

score = 100 × (facts found / 5) × (supported numbers / all checked numbers)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NUM_RE = re.compile(
    r"(?<![\d.,])([+\-−–]?)(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"(\s*%|\s*(?:מיליון|מיליארד|אלף|אלפי)(?![א-ת]))?")
MULT = {"מיליון": 1e6, "מיליארד": 1e9, "אלף": 1e3, "אלפי": 1e3}


@dataclass
class Num:
    value: float
    pct: bool
    scaled: bool      # written as "5.2 מיליון" — compare approximately
    raw: str


def numbers(text: str) -> list[Num]:
    out = []
    for m in NUM_RE.finditer(text):
        sign, digits, suffix = m.group(1), m.group(2), (m.group(3) or "").strip()
        v = float(digits.replace(",", ""))
        if sign in ("-", "−", "–") and suffix == "%":
            v = -v
        scaled = suffix in MULT
        if scaled:
            v *= MULT[suffix]
        out.append(Num(v, suffix == "%", scaled, m.group(0).strip()))
    return out


def _ignorable(n: Num) -> bool:
    if n.pct:
        return False
    v = abs(n.value)
    return v < 10 or (1990 <= v <= 2035 and float(v).is_integer() and "," not in n.raw)


def _close(a: Num, b: float, b_pct: bool) -> bool:
    if a.pct != b_pct:
        return False
    if a.pct:
        return abs(abs(a.value) - abs(b)) <= 0.051
    if a.scaled:
        return b != 0 and abs(a.value - b) / abs(b) <= 0.01
    return abs(a.value - b) < 0.5


def _flatten_metrics(obj, out: list[tuple[float, bool]], key: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_metrics(v, out, k if not key.endswith("pct") else key)
    elif isinstance(obj, list):
        for v in obj:
            _flatten_metrics(v, out, key)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        is_pct = "pct" in key or "share" in key or "growth" in key
        out.append((float(obj), is_pct))


def allowed_numbers(metrics: dict, texts: list[str]) -> list[tuple[float, bool]]:
    allowed: list[tuple[float, bool]] = []
    _flatten_metrics(metrics, allowed)
    for t in texts:
        allowed += [(n.value, n.pct) for n in numbers(t)]
    return allowed


def _norm(s: str) -> str:
    return s.replace("״", '"').replace("”", '"').replace("“", '"').replace("׳", "'")


def check_facts(report: str, facts: list[dict]) -> list[dict]:
    nums = numbers(report)
    text = _norm(report)
    results = []
    for f in facts:
        is_pct = f["type"] == "pct"
        found = any(_close(n, f["value"], is_pct) for n in nums)
        if f["type"] == "grant":
            found = found and _norm(f["grantor"]) in text
        results.append({**f, "found": found})
    return results


def check_unsupported(report: str, allowed: list[tuple[float, bool]]) -> tuple[int, list[str]]:
    checked, bad = 0, []
    for n in numbers(report):
        if _ignorable(n):
            continue
        checked += 1
        if not any(_close(n, v, p) for v, p in allowed):
            bad.append(n.raw)
    return checked, bad


def evaluate(report: str, facts: list[dict], metrics: dict, source_texts: list[str]) -> dict:
    fact_results = check_facts(report, facts)
    checked, bad = check_unsupported(report, allowed_numbers(metrics, source_texts))
    facts_ratio = sum(r["found"] for r in fact_results) / len(fact_results)
    supported_ratio = (checked - len(bad)) / checked if checked else 1.0
    return {
        "score": round(100 * facts_ratio * supported_ratio, 1),
        "facts": fact_results,
        "facts_found": sum(r["found"] for r in fact_results),
        "numbers_checked": checked,
        "unsupported_numbers": bad,
        "supported_ratio": round(supported_ratio, 3),
    }
