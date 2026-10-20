"""Records every API call (real, estimated or validation) in a local JSONL ledger.

The ledger is the source of truth for the budget guard; it is also synced to the
Supabase `api_calls` table so the UI can query it.

kind:
  actual            - a real call made by the correct architecture
  naive_estimate    - what the naive version would have cost (count_tokens, not run)
  middle_estimate   - Sonnet with full documents but with caching + batch (not run)
  naive_validation  - a real naive call, run once per component to validate estimates
  setup             - one-off cost of generating the synthetic data (not part of the comparison)

Real calls also carry Anthropic's own identifiers (request_id for live calls, batch_id for
batch results, message_id for both) so each row can be traced back to the provider's records.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from .settings import config, path

SPENT_KINDS = {"actual", "naive_validation", "setup", "discarded"}


class BudgetExceeded(RuntimeError):
    pass


def record(*, component: str, org_id: str | None, model: str, kind: str, batch: bool,
           usage: dict, cost_usd: float, note: str = "", ref: str | None = None,
           ids: dict | None = None) -> dict:
    row = {
        "uid": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "component": component,
        "org_id": org_id,
        "model": model,
        "kind": kind,
        "batch": batch,
        **usage,
        "cost_usd": round(cost_usd, 8),
        "ref": ref,
        "note": note,
        **(ids or {}),
    }
    f = path("ledger_file")
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def rows() -> list[dict]:
    f = path("ledger_file")
    if not f.exists():
        return []
    out = []
    for i, line in enumerate(l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()):
        r = json.loads(line)
        # rows written before uids existed get a stable one from their content and position
        r.setdefault("uid", hashlib.sha1(f"{i}:{line}".encode()).hexdigest()[:32])
        out.append(r)
    return out


def write_all(rs: list[dict]) -> None:
    path("ledger_file").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs), encoding="utf-8")


def mark_discarded(component: str, ref_prefix: str, note: str) -> int:
    """Re-label a superseded run: still counted as spend, excluded from comparisons."""
    rs = rows()
    n = 0
    for r in rs:
        if r["component"] == component and (r.get("ref") or "").startswith(ref_prefix) and                 r["kind"] in ("actual", "naive_estimate", "middle_estimate"):
            r["kind"] = "discarded" if r["kind"] == "actual" else "discarded_estimate"
            r["note"] = f"{r.get('note') or ''} | {note}".strip(" |")
            n += 1
    write_all(rs)
    return n


def spent_usd() -> float:
    return sum(r["cost_usd"] for r in rows() if r["kind"] in SPENT_KINDS)


def ensure_budget(estimated_usd: float, label: str) -> None:
    """Stop before a step whose estimate would push total spend past the stop line."""
    limit = config()["budget"]["stop_at_usd"]
    spent = spent_usd()
    if spent + estimated_usd > limit:
        raise BudgetExceeded(
            f"{label}: spent ${spent:.3f} + estimate ${estimated_usd:.3f} "
            f"> stop line ${limit:.2f}. Stopping — please confirm before continuing."
        )
    print(f"[budget] {label}: estimate ${estimated_usd:.4f}, spent so far ${spent:.4f}, stop line ${limit:.2f}")
