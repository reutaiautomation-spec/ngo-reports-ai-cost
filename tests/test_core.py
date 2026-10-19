import json
from pathlib import Path

from src import evals, finance
from src.chunking import chunk_document
from src.pricing import Usage, claude_cost
from src.synthetic import finance_gen
from src.synthetic.profiles import ORGS_BY_ID

FIN = finance_gen.generate(ORGS_BY_ID["youth"])
M = finance.metrics(FIN)


def test_finance_totals_and_growth():
    y = FIN["years"]["2025"]
    d = M["by_year"]["2025"]
    assert d["income_total"] == sum(y["income"].values())
    assert d["expense_total"] == sum(y["expenses"].values())
    prev = M["by_year"]["2024"]["income_total"]
    assert d["growth_pct"]["income_total"] == round(100 * (d["income_total"] - prev) / prev, 1)
    assert abs(sum(d["income_share_pct"].values()) - 100) < 0.3


def test_pricing_batch_and_cache():
    u = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert claude_cost("claude-sonnet-5-5", u) == 12.0
    assert claude_cost("claude-sonnet-5-5", u, batch=True) == 6.0
    c = Usage(cache_read_tokens=1_000_000)
    assert abs(claude_cost("claude-sonnet-5-5", c) - 0.2) < 1e-9
    # Haiku long-context tier above 100K input tokens
    big = Usage(input_tokens=150_000)
    assert abs(claude_cost("claude-haiku-5-5", big) - 0.075) < 1e-9


def test_number_extraction_hebrew():
    nums = evals.numbers('ההכנסות הגיעו ל־5,189,000 ש"ח, עלייה של 15.6%, ירידה של -6.5% ו־5.2 מיליון')
    vals = [(n.value, n.pct) for n in nums]
    assert (5189000.0, False) in vals and (15.6, True) in vals and (-6.5, True) in vals
    assert (5200000.0, False) in vals


def test_eval_facts_and_unsupported():
    facts = [
        {"id": "a", "type": "ils", "value": 5189000},
        {"id": "b", "type": "pct", "value": -6.5},
        {"id": "c", "type": "grant", "value": 1094000, "grantor": 'עיריית באר שבע'},
    ]
    report = 'סך ההכנסות 5,189,000 ש"ח, ירידה של 6.5%. המענק מעיריית באר שבע: 1,094,000 ש"ח. נתון מומצא: 777,000 ש"ח.'
    r = evals.evaluate(report, facts, {"x": 5189000, "y_pct": -6.5, "z": 1094000}, [])
    assert r["facts_found"] == 3
    assert r["unsupported_numbers"] == ["777,000"]


def test_chunking_keeps_sections_and_title():
    text = "# כותרת\n\n## סעיף א\n\n" + ("מילה " * 900) + "\n\n## סעיף ב\n\nפסקה קצרה."
    chunks = chunk_document("מסמך בדיקה", text)
    assert len(chunks) >= 2
    assert all(c.text.startswith("[מסמך בדיקה]") for c in chunks)
    assert chunks[-1].section == "סעיף ב"
