"""Reconciles the cost ledger against Anthropic's own records. Free: reads only, no model calls.

1. Batches: re-downloads every batch's results from Anthropic (kept 29 days), compares the
   provider's per-request token counts to the ledger row by row, and stamps each ledger row
   with its batch_id and message_id.
2. Writes data/results/reconciliation.json: the per-batch check, plus ledger totals per UTC day
   and model to compare with the Console's Usage and Cost pages (the check for live calls,
   which Anthropic does not let anyone re-download).
"""
import _bootstrap  # noqa: F401

import json
from collections import defaultdict
from datetime import datetime, timezone

from src import db, ledger
from src.llm import BATCH_DIR, client
from src.pricing import Usage, claude_cost
from src.settings import ROOT

OUT = ROOT / "data" / "results" / "reconciliation.json"
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens")


def check_batches(rows: list[dict]) -> list[dict]:
    claimed: set[str] = set()
    report = []
    for state in sorted(BATCH_DIR.glob("*.json")):
        info = json.loads(state.read_text())
        batch_id = info["batch_id"]
        b = client().messages.batches.retrieve(batch_id)
        provider = {k: 0 for k in TOKEN_KEYS}
        ledger_sum = {k: 0 for k in TOKEN_KEYS}
        provider_cost = ledger_cost = 0.0
        n_results = matched = 0
        models: set[str] = set()
        for item in client().messages.batches.results(batch_id):
            if item.result.type != "succeeded":
                continue
            n_results += 1
            msg = item.result.message
            usage = Usage.from_api(msg.usage).dict()
            models.add(msg.model)
            for k in TOKEN_KEYS:
                provider[k] += usage[k]
            provider_cost += claude_cost(msg.model, Usage(**usage), batch=True)
            # the ledger row for this request: same custom_id and identical token counts
            row = next((r for r in rows if r["batch"] and r["uid"] not in claimed and r.get("ref") == item.custom_id
                        and all(r.get(k, 0) == usage[k] for k in TOKEN_KEYS)), None)
            if row is None:
                continue
            claimed.add(row["uid"])
            matched += 1
            row["batch_id"], row["message_id"] = batch_id, msg.id
            for k in TOKEN_KEYS:
                ledger_sum[k] += row[k]
            ledger_cost += row["cost_usd"]
        report.append({
            "label": state.stem, "batch_id": batch_id, "component": info.get("component"),
            "created_at": b.created_at.isoformat(), "ended_at": b.ended_at.isoformat() if b.ended_at else None,
            "models": sorted(models), "requests_at_anthropic": n_results, "ledger_rows_matched": matched,
            "tokens_at_anthropic": provider, "tokens_in_ledger": ledger_sum,
            "cost_from_anthropic_usage": round(provider_cost, 6), "cost_in_ledger": round(ledger_cost, 6),
            "match": matched == n_results and provider == ledger_sum,
        })
        print(f"{state.stem:<24} {batch_id}  {matched}/{n_results} rows  "
              f"${provider_cost:.4f} vs ${ledger_cost:.4f}  {'OK' if report[-1]['match'] else 'MISMATCH'}")
    unmatched = [r["ref"] for r in rows if r["batch"] and r["kind"] in ledger.SPENT_KINDS
                 and r.get("model", "").startswith("claude") and r["uid"] not in claimed]
    if unmatched:
        print(f"[warn] {len(unmatched)} batch rows in the ledger have no matching Anthropic result: {unmatched[:5]}")
    return report


def daily_totals(rows: list[dict]) -> list[dict]:
    """What the Console's Usage and Cost pages should show, per UTC day and model."""
    agg: dict = defaultdict(lambda: {"requests": 0, "batch_requests": 0, "cost_usd": 0.0, **{k: 0 for k in TOKEN_KEYS}})
    for r in rows:
        if r["kind"] not in ledger.SPENT_KINDS or not r["model"].startswith("claude"):
            continue
        a = agg[(r["ts"][:10], r["model"])]
        a["requests"] += 1
        a["batch_requests"] += bool(r["batch"])
        a["cost_usd"] += r["cost_usd"]
        for k in TOKEN_KEYS:
            a[k] += r.get(k, 0)
    return [{"date": d, "model": m, **v, "cost_usd": round(v["cost_usd"], 6)} for (d, m), v in sorted(agg.items())]


if __name__ == "__main__":
    rows = ledger.rows()
    batches = check_batches(rows)
    ledger.write_all(rows)                      # persist the backfilled batch_id / message_id
    days = daily_totals(rows)
    spent = [r for r in rows if r["kind"] in ledger.SPENT_KINDS and r["model"].startswith("claude")]
    verified = {r["uid"] for r in spent if r.get("batch_id")}
    OUT.write_text(json.dumps({
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "batches": batches,
        "daily": days,
        "summary": {
            "claude_spend_usd": round(sum(r["cost_usd"] for r in spent), 6),
            "verified_by_batch_usd": round(sum(r["cost_usd"] for r in spent if r["uid"] in verified), 6),
            "with_request_id_usd": round(sum(r["cost_usd"] for r in spent if r.get("request_id")), 6),
            "all_batches_match": all(b["match"] for b in batches),
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    try:
        print(f"synced {db.sync_ledger()} ledger rows to Supabase")
    except Exception as e:  # the file is the source of truth; the table is a mirror
        print(f"[warn] Supabase sync failed: {e}")
