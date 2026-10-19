"""Stage 5: run the 5 sample questions per org through RAG (Haiku), with naive/middle estimates
and a source check (did the answer cite the document the fact was planted in?).

    python scripts/05_chat.py
"""
import argparse
import json

import _bootstrap  # noqa: F401

from src import chat, db, llm, naive
from src.ledger import ensure_budget
from src.loaders import load_json, load_org_documents, org_ids
from src.settings import ROOT, config, path

RESULTS = ROOT / "data" / "results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    args = ap.parse_args()
    data_dir = (ROOT / args.data) if args.data else path("synthetic_dir")
    per_session = config()["middle"]["chat_questions_per_session"]

    ensure_budget(0.05, "25 chat questions (Haiku)")
    out = []
    for org_id in org_ids(data_dir):
        docs = load_org_documents(data_dir, org_id)
        questions = load_json(data_dir, org_id, "questions.json") or []
        print(f"\n== {org_id}")
        for i, q in enumerate(questions):
            ref = f"chat__{org_id}__q{i + 1}"
            ans = chat.ask(org_id, q["question"], ref=ref)
            nreq = chat.naive_request(org_id, q["question"], docs, ref)
            est = naive.estimate(nreq, ans.usage["output_tokens"], chat.COMPONENT, ref=ref)
            q_tokens = llm.count_tokens(llm.Req(custom_id="q", model=nreq.model, user=f"שאלה: {q['question']}"))
            mid = naive.middle(nreq, est["input_tokens"], ans.usage["output_tokens"], chat.COMPONENT, batch=False,
                               cached_prefix_tokens=est["input_tokens"] - q_tokens,
                               cache="write" if i % per_session == 0 else "read", ref=ref)
            expected_doc = f"{org_id}__{q['source_slot']}" if q.get("source_slot") else None
            retrieved = expected_doc in {h.doc_id for h in ans.sources}
            cited = expected_doc in {h.doc_id for h in ans.cited}
            out.append({"org_id": org_id, "question": q["question"], "answer": ans.text, "expected": q.get("expected"),
                        "expected_doc": expected_doc, "retrieved_expected": retrieved, "cited_expected": cited,
                        "sources": [{"title": h.title, "date": h.doc_date, "doc_id": h.doc_id} for h in ans.cited],
                        "cost": ans.cost, "naive_cost": est["naive_cost"], "middle_cost": mid,
                        "input_tokens": ans.usage["input_tokens"] + ans.usage["cache_read_tokens"] + ans.usage["cache_write_tokens"],
                        "naive_input_tokens": est["input_tokens"]})
            print(f"Q{i + 1}: {q['question']}\n    {ans.text[:220]}\n"
                  f"    retrieved={retrieved} cited={cited} | ${ans.cost:.6f} vs naive ${est['naive_cost']:.4f} / middle ${mid:.4f}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    # real data gets its own file, so the synthetic quality results on the home screen stay intact
    out_name = "chat_samples.json" if not args.data else f"chat_samples_{data_dir.name}.json"
    (RESULTS / out_name).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(out)
    print(f"\n{n} questions | retrieved expected source {sum(r['retrieved_expected'] for r in out)}/{n} | "
          f"cited it {sum(r['cited_expected'] for r in out)}/{n} | actual ${sum(r['cost'] for r in out):.4f} | "
          f"naive ${sum(r['naive_cost'] for r in out):.4f} | middle ${sum(r['middle_cost'] for r in out):.4f}")
    print(f"ledger rows synced: {db.sync_ledger()}")


if __name__ == "__main__":
    main()
