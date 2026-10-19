"""Stage 2: load orgs + finance + documents into Supabase, extract (Haiku batch), chunk and embed.

    python scripts/02_ingest.py --dry-run      # token counts + cost estimate only
    python scripts/02_ingest.py                # run (safe to re-run; skips docs already embedded)
    python scripts/02_ingest.py --data data/real   # same pipeline on real documents
"""
import argparse
import statistics

import _bootstrap  # noqa: F401

from src import db, ingest, llm
from src.ledger import ensure_budget
from src.loaders import load_json, load_org_documents, org_ids
from src.settings import ROOT, model_for, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="data dir (default: synthetic)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-embed", action="store_true")
    args = ap.parse_args()
    data_dir = (ROOT / args.data) if args.data else path("synthetic_dir")

    all_docs = []
    for org_id in org_ids(data_dir):
        docs = load_org_documents(data_dir, org_id)
        all_docs += docs
        print(f"{org_id}: {len(docs)} documents")
    naive_model = model_for("naive")

    # exact Claude token count of every full document (used later for naive estimates)
    n_tokens = {d.id: llm.count_tokens(llm.Req(custom_id=d.id, model=naive_model, user=d.text)) for d in all_docs}
    reqs = [ingest.extraction_request(d) for d in all_docs]
    ext_in = [llm.count_tokens(r) for r in reqs]
    worst = llm.worst_case_cost(reqs, ext_in, batch=True)
    print(f"document tokens (Sonnet tokenizer): total {sum(n_tokens.values()):,}, "
          f"mean {statistics.mean(n_tokens.values()):,.0f}, min {min(n_tokens.values()):,}, max {max(n_tokens.values()):,}")
    print(f"extraction input {sum(ext_in):,} tokens, worst case ${worst:.4f}")
    if args.dry_run:
        return

    for org_id in org_ids(data_dir):
        profile = load_json(data_dir, org_id, "profile.json") or {"id": org_id, "name": org_id}
        db.upsert_org(profile)
        fin = load_json(data_dir, org_id, "finance.json")
        if fin:
            db.upsert_finance(fin)
    for d in all_docs:
        db.upsert_document(d, n_tokens[d.id])

    ensure_budget(worst + 0.01, "extraction + embeddings")
    label = "ingest_extract_v1" if not args.data else f"ingest_extract_{data_dir.name}"
    extracted = ingest.extract_all(all_docs, label)
    for d in all_docs:
        if d.id in extracted:
            db.upsert_extraction(d.org_id, d.id, extracted[d.id]["data"])

    rows = []
    existing = {}
    for d in all_docs:
        if d.org_id not in existing:
            existing[d.org_id] = db.chunk_counts(d.org_id)
        if existing[d.org_id].get(d.id) and not args.force_embed:
            info = {"chunks": existing[d.org_id][d.id], "embed_tokens": 0, "embed_cost": 0.0}
        else:
            info = ingest.chunk_and_embed(d)
        ext = extracted.get(d.id, {})
        rows.append((d, n_tokens[d.id], info, ext.get("cost", 0.0)))

    print("\ndoc                          tokens  chunks  extract$   embed$    total$")
    for d, n, info, ec in rows:
        print(f"{d.id:<28} {n:>6} {info['chunks']:>7}  {ec:.6f}  {info['embed_cost']:.6f}  {ec + info['embed_cost']:.6f}")
    tot_ext = sum(r[3] for r in rows)
    tot_emb = sum(r[2]["embed_cost"] for r in rows)
    print(f"\n{len(rows)} docs | extraction ${tot_ext:.4f} + embeddings ${tot_emb:.4f} = ${tot_ext + tot_emb:.4f} "
          f"| per doc ${(tot_ext + tot_emb) / len(rows):.6f} | chunks {sum(r[2]['chunks'] for r in rows)}")
    print(f"ledger rows synced to Supabase: {db.sync_ledger()}")


if __name__ == "__main__":
    main()
