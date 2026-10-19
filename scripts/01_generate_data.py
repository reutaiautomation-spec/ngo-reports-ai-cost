"""Stage 1: synthetic data — finance (code, $0), 50 documents (Haiku via Batch API), facts and questions.

    python scripts/01_generate_data.py --dry-run   # exact input token counts + cost estimate, no generation
    python scripts/01_generate_data.py             # generate (resumes an interrupted batch)
"""
import argparse
import json
import re
import statistics

import _bootstrap  # noqa: F401

from src import finance, llm, loaders
from src.ledger import ensure_budget
from src.settings import config, model_for, path
from src.synthetic import doc_plan, finance_gen
from src.synthetic.profiles import ORGS

BATCH_LABEL = "gen_docs_v1"


def write_base_files(org: dict) -> tuple[dict, dict]:
    d = path("synthetic_dir") / org["id"]
    (d / "docs").mkdir(parents=True, exist_ok=True)
    fin = finance_gen.generate(org)
    m = finance.metrics(fin)
    profile = {k: org[k] for k in ("id", "name", "field", "founded", "city", "region", "ceo", "chair", "treasurer", "mission")}
    profile["programs"] = [{"name": n, "description": t} for n, t in org["programs"]]
    files = {
        "profile.json": profile,
        "finance.json": fin,
        "facts.json": doc_plan.facts(org, m),
        "questions.json": doc_plan.questions(org),
    }
    for name, obj in files.items():
        (d / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return fin, m


def build_requests() -> list[llm.Req]:
    wpp = config()["data"]["words_per_page"]
    reqs = []
    for org in ORGS:
        fin, m = write_base_files(org)
        for slot, dtype, date, pages, years in doc_plan.org_slots(org["id"]):
            reqs.append(llm.Req(
                custom_id=f"{org['id']}__{slot}",
                model=model_for("simple"),
                system=doc_plan.SYSTEM,
                cache_system=True,
                user=doc_plan.user_prompt(org, fin, m, slot, dtype, date, pages, years, wpp),
                max_tokens=min(pages * 2600, 32000),   # Hebrew: ~4.1 output tokens per word (measured)
                effort="high",          # long, complete documents; thinking off to keep tokens for the text
                thinking_off=True,
                org_id=org["id"],
                meta={"slot": slot, "type": dtype, "date": date, "pages": pages,
                      "title": doc_plan.doc_title(org, slot, dtype, date)},
            ))
    return reqs


def front_matter(org_id: str, meta: dict) -> str:
    return loaders.front_matter({"org_id": org_id, "slot": meta["slot"], "type": meta["type"],
                                 "date": meta["date"], "title": meta["title"]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    reqs = build_requests()
    print(f"{len(reqs)} documents planned: " + ", ".join(
        f"{o['id']}={sum(r.org_id == o['id'] for r in reqs)}" for o in ORGS))

    counts = [llm.count_tokens(r) for r in reqs]
    worst = llm.worst_case_cost(reqs, counts, batch=True)
    # likely: ~2.5 output tokens per Hebrew word (to be replaced by the measured ratio)
    likely = sum(llm.estimate_cost(r, n, int(r.meta["pages"] * config()["data"]["words_per_page"] * 2.5), True)
                 for r, n in zip(reqs, counts))
    print(f"input tokens: {sum(counts):,} (exact, count_tokens) | "
          f"likely cost ${likely:.3f} | worst case (all max_tokens) ${worst:.3f}")
    if args.dry_run:
        return

    ensure_budget(worst, "generate synthetic documents")
    results = llm.run_batch(BATCH_LABEL, reqs, component="setup", kind="setup")

    by_id = {r.custom_id: r for r in reqs}
    words, ratios = [], []
    for i, (cid, res) in enumerate(sorted(results.items())):
        req = by_id[cid]
        slot_index = [s[0] for s in doc_plan.SLOTS].index(req.meta["slot"])
        out = path("synthetic_dir") / req.org_id / "docs" / f"{slot_index + 1:02d}_{req.meta['slot']}.md"
        out.write_text(front_matter(req.org_id, req.meta) + res.text.strip() + "\n", encoding="utf-8")
        n_words = len(re.findall(r"\S+", res.text))
        target = req.meta["pages"] * config()["data"]["words_per_page"]
        words.append((cid, n_words, target, res.stop_reason))
        ratios.append(res.usage.output_tokens / max(n_words, 1))

    print("\ndoc                         words  target  stop")
    for cid, n, t, stop in words:
        print(f"{cid:<26} {n:>6} {t:>7}  {stop}")
    total_cost = sum(r.cost_usd for r in results.values())
    print(f"\n{len(results)}/{len(reqs)} docs written | total words {sum(w[1] for w in words):,} | "
          f"output tokens per Hebrew word: {statistics.mean(ratios):.2f} | cost ${total_cost:.4f}")


if __name__ == "__main__":
    main()
