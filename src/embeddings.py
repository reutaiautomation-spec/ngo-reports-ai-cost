"""Voyage embeddings, with cost recorded in the ledger like every other API call.

Throttled to fit Voyage's reduced limits for accounts without a payment method
(3 requests/min, 10K tokens/min); set `embeddings.throttle: false` in config.yaml once
standard limits apply.
"""
from __future__ import annotations

import time
from functools import lru_cache

import voyageai
import voyageai.error

from . import ledger
from .pricing import embedding_cost
from .settings import config, env, model_for

MAX_BATCH = 128
_last_call = 0.0


@lru_cache
def _client() -> voyageai.Client:
    env("VOYAGE_API_KEY")
    return voyageai.Client(max_retries=0)


def _limits() -> tuple[bool, int, float]:
    c = config()["embeddings"]
    return c.get("throttle", True), c.get("max_tokens_per_request", 8000), c.get("min_seconds_between_requests", 21)


def _batches(texts: list[str], max_tokens: int) -> list[list[str]]:
    """Group texts so each request stays under the token cap (conservative estimate: 1.2 chars/token)."""
    out, cur, cur_tok = [], [], 0
    for t in texts:
        est = len(t) / 1.2
        if cur and (cur_tok + est > max_tokens or len(cur) >= MAX_BATCH):
            out.append(cur)
            cur, cur_tok = [], 0
        cur.append(t)
        cur_tok += est
    if cur:
        out.append(cur)
    return out


def _embed_once(batch: list[str], model: str, input_type: str):
    global _last_call
    throttle, _, gap = _limits()
    for attempt in range(12):
        if throttle:
            wait = gap - (time.time() - _last_call)
            if wait > 0:
                time.sleep(wait)
        _last_call = time.time()
        try:
            return _client().embed(batch, model=model, input_type=input_type,
                                   output_dimension=config()["embeddings"]["dimension"])
        except (voyageai.error.RateLimitError, voyageai.error.ServiceUnavailableError, voyageai.error.Timeout):
            time.sleep(30 + 10 * attempt)
    raise RuntimeError("Voyage: rate limited too many times")


def embed(texts: list[str], input_type: str, component: str, org_id: str | None,
          kind: str = "actual", ref: str | None = None) -> tuple[list[list[float]], int, float]:
    """Returns (vectors, tokens, cost)."""
    model = model_for("embeddings")
    throttle, max_tokens, _ = _limits()
    vectors, tokens = [], 0
    for batch in (_batches(texts, max_tokens) if throttle else [texts[i:i + MAX_BATCH] for i in range(0, len(texts), MAX_BATCH)]):
        r = _embed_once(batch, model, input_type)
        vectors += r.embeddings
        tokens += r.total_tokens
    cost = embedding_cost(model, tokens)
    ledger.record(component=component, org_id=org_id, model=model, kind=kind, batch=False,
                  usage={"input_tokens": tokens, "output_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0},
                  cost_usd=cost, ref=ref, note=f"{len(texts)} texts, {input_type}")
    return vectors, tokens, cost
