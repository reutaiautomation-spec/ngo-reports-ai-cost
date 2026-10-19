"""Naive and "middle" cost estimates — measured with count_tokens, never run (except validation).

naive_estimate : Sonnet, full documents / raw data, no Batch, no caching.
middle_estimate: Sonnet, the SAME full-document input, but with Batch (for async work) and prompt
                 caching where requests realistically repeat within the cache TTL. It isolates how
                 much of the saving comes from RAG + cards + Haiku vs. from Batch/caching alone.

Output tokens for both are assumed equal to the real output of the correct version.
"""
from __future__ import annotations

from . import ledger, llm
from .pricing import Usage, claude_cost
from .settings import config


def middle_cfg() -> dict:
    return config()["middle"]


def estimate(req: llm.Req, output_tokens: int, component: str, ref: str | None = None,
             input_tokens: int | None = None) -> dict:
    """Records naive_estimate (+ middle_estimate) rows. Returns the numbers for display."""
    n = input_tokens if input_tokens is not None else llm.count_tokens(req)
    usage = Usage(input_tokens=n, output_tokens=output_tokens)
    naive_cost = claude_cost(req.model, usage)
    ledger.record(component=component, org_id=req.org_id, model=req.model, kind="naive_estimate", batch=False,
                  usage=usage.dict(), cost_usd=naive_cost, ref=ref or req.custom_id,
                  note="count_tokens input; output = actual output")
    return {"input_tokens": n, "output_tokens": output_tokens, "naive_cost": naive_cost}


def middle(req: llm.Req, input_tokens: int, output_tokens: int, component: str, *, batch: bool,
           cached_prefix_tokens: int = 0, cache: str = "none", ref: str | None = None) -> float:
    """cache: 'none' | 'write' (first call of a session) | 'read' (later calls in the same session)."""
    uncached = input_tokens - (cached_prefix_tokens if cache != "none" else 0)
    usage = Usage(input_tokens=uncached, output_tokens=output_tokens,
                  cache_write_tokens=cached_prefix_tokens if cache == "write" else 0,
                  cache_read_tokens=cached_prefix_tokens if cache == "read" else 0)
    cost = claude_cost(req.model, usage, batch=batch)
    ledger.record(component=component, org_id=req.org_id, model=req.model, kind="middle_estimate", batch=batch,
                  usage=usage.dict(), cost_usd=cost, ref=ref or req.custom_id,
                  note=f"full docs + {'batch' if batch else 'live'} + cache:{cache}")
    return cost
