"""Stage 6: run each naive version FOR REAL, once, on one org — to validate the estimates.

For every component it compares: estimated input (count_tokens) vs billed input,
assumed output vs real output, and estimated vs real cost. For component 1 it also
compares the AI's financial numbers with the code's; for component 4 it scores the
naive report with the same evals as the correct one.

    python scripts/06_validate_naive.py --org environment
"""
import argparse
import json

import _bootstrap  # noqa: F401

from src import chat, db, evals, finance, finance_naive, ledger, llm, org_card, report
from src.ledger import ensure_budget
from src.loaders import load_json, load_org_documents
from src.settings import ROOT, path

RESULTS = ROOT / "data" / "results"


def estimate_row(ref: str, component: str) -> dict:
    rows = [r for r in ledger.rows() if r["kind"] == "naive_estimate" and r["component"] == component and r["ref"] == ref]
    if not rows:
        raise SystemExit(f"no naive estimate for {component}/{ref} — run stages 3–5 first")
    return rows[-1]


def compare(component: str, est: dict, res: llm.Result) -> dict:
    real_in = res.usage.total_input
    row = {
        "component": component,
        "est_input": est["input_tokens"], "real_input": real_in,
        "input_diff_pct": round(100 * (real_in - est["input_tokens"]) / est["input_tokens"], 2),
        "assumed_output": est["output_tokens"], "real_output": res.usage.output_tokens,
        "est_cost": est["cost_usd"], "real_cost": res.cost_usd,
        "cost_diff_pct": round(100 * (res.cost_usd - est["cost_usd"]) / est["cost_usd"], 1),
    }
    print(f"[{component}] input est {row['est_input']:,} vs billed {real_in:,} ({row['input_diff_pct']:+}%) | "
          f"output assumed {row['assumed_output']:,} vs real {row['real_output']:,} | "
          f"cost est ${row['est_cost']:.4f} vs real ${row['real_cost']:.4f} ({row['cost_diff_pct']:+}%)")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", default="environment")
    ap.add_argument("--data", default=None)
    args = ap.parse_args()
    data_dir = (ROOT / args.data) if args.data else path("synthetic_dir")
    org_id = args.org

    org_row = next(o for o in db.list_orgs() if o["id"] == org_id)
    org = {"id": org_id, "name": org_row["name"], "field": org_row["field"]}
    fin = db.load_finance(org_id)
    m = finance.metrics(fin)
    docs = load_org_documents(data_dir, org_id)
    questions = load_json(data_dir, org_id, "questions.json")

    reqs = {
        "finance": finance_naive.request(fin),
        "card": org_card.naive_request(docs),
        "report": report.naive_request(org, fin, docs),
        "chat": chat.naive_request(org_id, questions[0]["question"], docs, f"chat__{org_id}__q1"),
    }
    counts = {k: llm.count_tokens(r) for k, r in reqs.items()}
    worst = sum(llm.estimate_cost(r, counts[k], r.max_tokens, batch=False) for k, r in reqs.items())
    print(f"validation on '{org_id}': worst case ${worst:.3f}")
    ensure_budget(worst, "naive validation runs")

    out = {"org_id": org_id, "rows": []}

    # component 1 — cost + accuracy
    res = llm.call(reqs["finance"], component=finance_naive.COMPONENT, kind="naive_validation")
    out["rows"].append(compare("finance", estimate_row(reqs["finance"].custom_id, "finance"), res))
    cmp = finance_naive.compare(res.json(), m)
    wrong = [c for c in cmp if not c["ok"]]
    out["finance_accuracy"] = {"checked": len(cmp), "wrong": wrong}
    print(f"[finance] AI numbers: {len(cmp) - len(wrong)}/{len(cmp)} correct")
    for w in wrong:
        print(f"    {w['year']} {w['field']}: code={w['code']} AI={w['ai']}")

    # component 3
    res = llm.call(reqs["card"], component=org_card.COMPONENT, kind="naive_validation")
    out["rows"].append(compare("card", estimate_row(f"card__{docs[-1].id}", "card"), res))

    # component 4 — cost + quality
    res = llm.call(reqs["report"], component=report.COMPONENT, kind="naive_validation")
    out["rows"].append(compare("report", estimate_row(reqs["report"].custom_id, "report"), res))
    facts = load_json(data_dir, org_id, "facts.json")
    card = db.latest_card(org_id)
    ev = evals.evaluate(res.text, facts, m, [d.text for d in docs] + [card["content"] if card else ""])
    rid = db.save_report(org_id, res.text, reqs["report"].model, res.cost_usd, {"usage": res.usage.dict()},
                         variant="naive_validation")
    db.save_eval(org_id, rid, ev["score"], ev)
    correct = db.latest_report(org_id)
    correct_eval = db.latest_eval(org_id, correct["id"]) if correct else None
    out["report_quality"] = {"naive_score": ev["score"], "naive_unsupported": ev["unsupported_numbers"],
                             "correct_score": correct_eval["score"] if correct_eval else None}
    print(f"[report] quality: naive {ev['score']} vs correct {out['report_quality']['correct_score']}")

    # component 5
    res = llm.call(reqs["chat"], component=chat.COMPONENT, kind="naive_validation")
    out["rows"].append(compare("chat", estimate_row(f"chat__{org_id}__q1", "chat"), res))
    out["chat_answer"] = res.text

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "validation.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ledger rows synced: {db.sync_ledger()}")


if __name__ == "__main__":
    main()
