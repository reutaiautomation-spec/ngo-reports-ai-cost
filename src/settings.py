"""Loads config.yaml, pricing.yaml and .env once, for the whole project."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@lru_cache
def config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@lru_cache
def pricing() -> dict:
    return yaml.safe_load((ROOT / "pricing.yaml").read_text(encoding="utf-8"))


def model_for(role: str) -> str:
    return pricing()["roles"][role]


def path(key: str) -> Path:
    return ROOT / config()["data"][key]


def env(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name) or None
    if required and not value:
        raise RuntimeError(f"Missing {name} in .env (see .env.example)")
    return value
