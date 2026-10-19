"""Stage 3: build each org card incrementally, document by document (Haiku, live calls).

For every update it also records what the naive alternative (Sonnet re-reading the full
history) and the middle alternative would have cost, via count_tokens.

    python scripts/03_build_cards.py [--orgs youth,health]
"""
import argparse

import _bootstrap  # noqa: F401

from src import db, llm, naive, org_card
from src.ledger import ensure_budget
from src.loaders import load_org_documents, org_ids
from src.settings import ROOT, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    ap.add_argument("--orgs", default=None)
    args = ap.parse_args()
    data_dir = (ROOT / args.data) if args.data else path("synthetic_dir")
    orgs = args.orgs.split(",") if args.orgs else org_ids(data_dir)

    # budget upper bound: 50 Haiku updates (+ compactions) x (~16K input + 10K max output)
    ensure_budget(0.45, "org cards")
    summary = []
    for org_id in orgs:
        docs = load_org_documents(data_dir, org_id)
        latest = db.latest_card(org_id)
        start = latest["version"] if latest else 0
        card = latest["content"] if latest else None
        print(f"\n{org_id}: {len(docs)} docs, resuming from version {start}")
        for i, doc in enumerate(docs):
            version = i + 1
            if version <= start:
                continue
            results = org_card.update(card, doc)
            card = results[-1].text.strip()
            db.save_card(org_id, version, doc.id, card)
            first = results[0]
            cost = sum(r.cost_usd for r in results)
            compacted = f" (compacted from {org_card.words(first.text)})" if len(results) > 1 else ""

            # naive equivalent: Sonnet rebuilds the card from the full history; output = the update's output
            nreq = org_card.naive_request(docs[:version])
            est = naive.estimate(nreq, first.usage.output_tokens, org_card.COMPONENT, ref=f"card__{doc.id}")
            mid = naive.middle(nreq, est["input_tokens"], first.usage.output_tokens, org_card.COMPONENT,
                               batch=True, ref=f"card__{doc.id}")
            words = org_card.words(card)
            summary.append((org_id, version, first.usage.total_input, first.usage.output_tokens, cost,
                            est["input_tokens"], est["naive_cost"], mid, words, len(results) > 1))
            print(f"  v{version:<2} {doc.id:<26} in={first.usage.total_input:>6} out={first.usage.output_tokens:>5} "
                  f"${cost:.5f} | naive in={est['input_tokens']:>7} ${est['naive_cost']:.4f} "
                  f"| middle ${mid:.4f} | card {words} words{compacted}")

    if summary:
        act = sum(s[4] for s in summary)
        nav = sum(s[6] for s in summary)
        mid = sum(s[7] for s in summary)
        print(f"\n{len(summary)} updates | actual ${act:.4f} (avg ${act / len(summary):.5f}/update) | "
              f"naive ${nav:.4f} | middle ${mid:.4f} | max card {max(s[8] for s in summary)} words | "
              f"compactions {sum(s[9] for s in summary)}")
    print(f"ledger rows synced: {db.sync_ledger()}")


if __name__ == "__main__":
    main()
