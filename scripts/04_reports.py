"""Stage 4: components 1 + 4 — financial calculations in code, then all reports in one Sonnet batch.

Also records, per org, the naive and middle estimates for components 1 and 4, and runs
the quality evals on every report.

    python scripts/04_reports.py --dry-run
    python scripts/04_reports.py
"""
import argparse
import json

import _bootstrap  # noqa: F401

from src import db, evals, finance, finance_naive, ledger, llm, naive, report
from src.ledger import ensure_budget
from src.loaders import load_json, load_org_documents, org_ids
from src.settings import ROOT, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--label", default="reports_v1")
    args = ap.parse_args()
    data_dir = (ROOT / args.data) if args.data else path("synthetic_dir")

    orgs = {o["id"]: o for o in db.list_orgs()}
    prepared = []
    for org_id in org_ids(data_dir):
        org = {"id": org_id, "name": orgs[org_id]["name"], "field": orgs[org_id]["field"]}
        fin = db.load_finance(org_id)
        card = db.latest_card(org_id)
        if not card:
            raise SystemExit(f"{org_id}: no org card yet — run 03_build_cards.py first")
        hits, embed_cost = report.retrieve_for_report(org_id)
        req = report.correct_request(org, fin, card["content"], hits)
        prepared.append((org, fin, card, hits, req, embed_cost))

    counts = [llm.count_tokens(p[4]) for p in prepared]
    worst = llm.worst_case_cost([p[4] for p in prepared], counts, batch=True)
    print("correct-version input tokens per report: " + ", ".join(f"{p[0]['id']}={n:,}" for p, n in zip(prepared, counts)))
    print(f"worst case ${worst:.3f}")
    if args.dry_run:
        return

    ensure_budget(worst, "reports batch")
    results = llm.run_batch(args.label, [p[4] for p in prepared], component=report.COMPONENT)

    print("\norg          in      out     actual$  | naive in   naive$  | middle$ | score  facts  unsupported")
    for org, fin, card, hits, req, embed_cost in prepared:
        res = results.get(req.custom_id)
        if res is None:
            print(f"{org['id']}: failed")
            continue
        m = finance.metrics(fin)

        # component 1: code = $0 (logged so it appears in the cost table); naive = Sonnet computing from raw data
        ledger.record(component=finance_naive.COMPONENT, org_id=org["id"], model="code", kind="actual", batch=False,
                      usage={"input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0},
                      cost_usd=0.0, ref=f"finance__{org['id']}", note="calculated in Python")
        freq = finance_naive.request(fin)
        f_out = llm.count_tokens(llm.Req(custom_id="x", model=freq.model,
                                         user=json.dumps({"years": list(finance_naive.expected(m).values())}, ensure_ascii=False)))
        f_est = naive.estimate(freq, f_out, finance_naive.COMPONENT)
        naive.middle(freq, f_est["input_tokens"], f_out, finance_naive.COMPONENT, batch=True)

        # component 4
        docs = load_org_documents(data_dir, org["id"])
        nreq = report.naive_request(org, fin, docs)
        est = naive.estimate(nreq, res.usage.output_tokens, report.COMPONENT)
        mid = naive.middle(nreq, est["input_tokens"], res.usage.output_tokens, report.COMPONENT, batch=True)

        facts = load_json(data_dir, org["id"], "facts.json") or []
        sources = [d.text for d in docs] + [card["content"]]
        ev = evals.evaluate(res.text, facts, m, sources)
        meta = {"usage": res.usage.dict(), "llm_cost": res.cost_usd, "embed_cost": embed_cost,
                "naive_cost": est["naive_cost"], "naive_input_tokens": est["input_tokens"], "middle_cost": mid,
                "sources": [{"title": h.title, "date": h.doc_date, "similarity": round(h.similarity, 3)} for h in hits],
                "card_version": card["version"]}
        rid = db.save_report(org["id"], res.text, req.model, res.cost_usd + embed_cost, meta)
        db.save_eval(org["id"], rid, ev["score"], ev)
        print(f"{org['id']:<12} {res.usage.total_input:>6} {res.usage.output_tokens:>6}  ${res.cost_usd + embed_cost:.4f} "
              f"| {est['input_tokens']:>8,} ${est['naive_cost']:.4f} | ${mid:.4f} | {ev['score']:>5} "
              f"{ev['facts_found']}/5   {ev['unsupported_numbers']}")
        print(f"             cache: write={res.usage.cache_write_tokens} read={res.usage.cache_read_tokens}")
    print(f"ledger rows synced: {db.sync_ledger()}")


if __name__ == "__main__":
    main()
