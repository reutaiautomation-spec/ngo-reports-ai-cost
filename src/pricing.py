"""Turns token usage into dollars, using pricing.yaml only."""
from __future__ import annotations

from dataclasses import dataclass, asdict

from .settings import pricing


@dataclass
class Usage:
    input_tokens: int = 0          # uncached input, billed at full price
    output_tokens: int = 0         # includes thinking tokens
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @classmethod
    def from_api(cls, u) -> "Usage":
        return cls(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    def dict(self) -> dict:
        return asdict(self)


def rates(model: str, total_input: int = 0) -> tuple[float, float]:
    """(input $/token, output $/token) for this model and prompt size."""
    m = pricing()["models"][model]
    inp, out = m["input"], m.get("output", 0.0)
    threshold = m.get("long_context_threshold")
    if threshold and total_input > threshold:
        inp, out = m["long_input"], m["long_output"]
    return inp / 1_000_000, out / 1_000_000


def claude_cost(model: str, usage: Usage, batch: bool = False, cache_ttl: str = "5m") -> float:
    mod = pricing()["modifiers"]
    inp, out = rates(model, usage.total_input)
    write_mult = mod["cache_write_1h"] if cache_ttl == "1h" else mod["cache_write_5m"]
    cost = (
        usage.input_tokens * inp
        + usage.cache_write_tokens * inp * write_mult
        + usage.cache_read_tokens * inp * mod["cache_read"]
        + usage.output_tokens * out
    )
    return cost * mod["batch_discount"] if batch else cost


def embedding_cost(model: str, tokens: int) -> float:
    return tokens * pricing()["models"][model]["input"] / 1_000_000
