"""Single entry point for every Claude call: real calls, batches and token counting.

Every real call is priced from its `usage` field and written to the ledger.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from . import ledger
from .pricing import Usage, claude_cost, rates
from .settings import ROOT

BATCH_DIR = ROOT / "data" / "batches"

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=4)
    return _client


@dataclass
class Req:
    """One Messages API request, independent of whether it runs live or in a batch."""
    custom_id: str
    model: str
    user: str | list
    system: str | None = None
    cache_system: bool = False          # put a cache breakpoint on the (stable) system prompt
    max_tokens: int = 4000
    effort: str | None = None
    thinking_off: bool = False          # Haiku 5.5 only (allowed at effort <= high)
    json_schema: dict | None = None
    org_id: str | None = None
    meta: dict = field(default_factory=dict)

    def system_blocks(self):
        if self.system is None:
            return None
        block = {"type": "text", "text": self.system}
        if self.cache_system:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def messages(self) -> list[dict]:
        return [{"role": "user", "content": self.user}]

    def params(self) -> dict:
        p: dict = {"model": self.model, "max_tokens": self.max_tokens, "messages": self.messages()}
        if self.system is not None:
            p["system"] = self.system_blocks()
        output_config: dict = {}
        if self.effort:
            output_config["effort"] = self.effort
        if self.json_schema:
            output_config["format"] = {"type": "json_schema", "schema": self.json_schema}
        if output_config:
            p["output_config"] = output_config
        if self.thinking_off:
            p["thinking"] = {"type": "disabled"}
        return p


@dataclass
class Result:
    custom_id: str
    text: str
    usage: Usage
    cost_usd: float
    stop_reason: str | None

    def json(self) -> dict:
        return json.loads(self.text)


def _text_of(message) -> str:
    return "".join(b.text for b in message.content if b.type == "text")


def _check_stop(custom_id: str, stop_reason: str | None) -> None:
    if stop_reason == "refusal":
        print(f"[warn] {custom_id}: model refused")
    elif stop_reason == "max_tokens":
        print(f"[warn] {custom_id}: hit max_tokens, output truncated")


def count_tokens(req: Req) -> int:
    """Exact input-token count for a request, without running it (free endpoint)."""
    p = req.params()
    # output_config matters: a JSON schema adds input tokens (validated: 1,632 without vs 2,280 billed)
    kwargs = {k: p[k] for k in ("model", "messages", "system", "output_config", "thinking") if k in p}
    return client().messages.count_tokens(**kwargs).input_tokens


def estimate_cost(req: Req, input_tokens: int, output_tokens: int, batch: bool) -> float:
    return claude_cost(req.model, Usage(input_tokens=input_tokens, output_tokens=output_tokens), batch=batch)


def worst_case_cost(reqs: list[Req], input_tokens: list[int], batch: bool) -> float:
    """Upper bound for the budget guard: real input counts + every request using its full max_tokens."""
    return sum(estimate_cost(r, n, r.max_tokens, batch) for r, n in zip(reqs, input_tokens))


def call(req: Req, component: str, kind: str = "actual", note: str = "") -> Result:
    msg = client().messages.create(**req.params())
    usage = Usage.from_api(msg.usage)
    cost = claude_cost(req.model, usage, batch=False)
    _check_stop(req.custom_id, msg.stop_reason)
    ledger.record(component=component, org_id=req.org_id, model=req.model, kind=kind, batch=False,
                  usage=usage.dict(), cost_usd=cost, note=note, ref=req.custom_id)
    return Result(req.custom_id, _text_of(msg), usage, cost, msg.stop_reason)


def run_batch(label: str, reqs: list[Req], component: str, kind: str = "actual",
              poll_seconds: int = 20) -> dict[str, Result]:
    """Submit (or resume) a batch, wait, price each result and log it once.

    State lives in data/batches/<label>.json so an interrupted script resumes the
    same batch instead of paying twice.
    """
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    state_file = BATCH_DIR / f"{label}.json"
    results_file = BATCH_DIR / f"{label}.results.jsonl"
    by_id = {r.custom_id: r for r in reqs}

    if results_file.exists():
        print(f"[batch] {label}: already done, loading saved results")
        return _load_results(results_file)

    if state_file.exists():
        batch_id = json.loads(state_file.read_text())["batch_id"]
        print(f"[batch] {label}: resuming {batch_id}")
    else:
        batch = client().messages.batches.create(requests=[
            Request(custom_id=r.custom_id, params=MessageCreateParamsNonStreaming(**r.params())) for r in reqs
        ])
        batch_id = batch.id
        state_file.write_text(json.dumps({"batch_id": batch_id, "component": component}))
        print(f"[batch] {label}: submitted {batch_id} ({len(reqs)} requests)")

    not_found = 0
    while True:
        try:
            b = client().messages.batches.retrieve(batch_id)
        except anthropic.NotFoundError:
            # a just-created batch can briefly 404 on read; give it a few minutes before failing
            not_found += 1
            if not_found > 10:
                raise
            time.sleep(poll_seconds)
            continue
        if b.processing_status == "ended":
            break
        c = b.request_counts
        print(f"[batch] {label}: processing={c.processing} succeeded={c.succeeded} errored={c.errored}")
        time.sleep(poll_seconds)

    out: dict[str, Result] = {}
    with results_file.open("w", encoding="utf-8") as fh:
        for item in client().messages.batches.results(batch_id):
            req = by_id[item.custom_id]
            if item.result.type != "succeeded":
                print(f"[batch] {item.custom_id}: {item.result.type}")
                continue
            msg = item.result.message
            usage = Usage.from_api(msg.usage)
            cost = claude_cost(req.model, usage, batch=True)
            _check_stop(item.custom_id, msg.stop_reason)
            ledger.record(component=component, org_id=req.org_id, model=req.model, kind=kind, batch=True,
                          usage=usage.dict(), cost_usd=cost, ref=item.custom_id)
            res = Result(item.custom_id, _text_of(msg), usage, cost, msg.stop_reason)
            out[item.custom_id] = res
            fh.write(json.dumps({"custom_id": res.custom_id, "text": res.text, "usage": usage.dict(),
                                 "cost_usd": cost, "stop_reason": res.stop_reason}, ensure_ascii=False) + "\n")
    missing = set(by_id) - set(out)
    if missing:
        print(f"[batch] {label}: {len(missing)} requests failed: {sorted(missing)[:5]}...")
    return out


def _load_results(f) -> dict[str, Result]:
    out = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        out[d["custom_id"]] = Result(d["custom_id"], d["text"], Usage(**d["usage"]), d["cost_usd"], d["stop_reason"])
    return out


__all__ = ["Req", "Result", "call", "run_batch", "count_tokens", "estimate_cost", "worst_case_cost", "rates"]
