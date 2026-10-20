"""Supabase access. Every org-scoped function takes org_id and filters by it — no exceptions.

The service key bypasses RLS, so this module is the application-level isolation layer;
RLS policies in sql/schema.sql protect direct access by end users.
"""
from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from . import ledger
from .settings import env


@lru_cache
def sb() -> Client:
    return create_client(env("SUPABASE_URL"), env("SUPABASE_SERVICE_KEY"))


def _need(org_id: str | None) -> str:
    if not org_id:
        raise ValueError("org_id is required for every org-scoped query")
    return org_id


# ─────────── orgs & finance ───────────
def upsert_org(profile: dict) -> None:
    sb().table("orgs").upsert({"id": _need(profile["id"]), "name": profile["name"],
                               "field": profile.get("field"), "profile": profile}).execute()


def list_orgs() -> list[dict]:
    return sb().table("orgs").select("id,name,field,profile").order("id").execute().data


def upsert_finance(fin: dict) -> None:
    org_id = _need(fin["org_id"])
    lines, stats, grants = [], [], []
    for y, d in fin["years"].items():
        lines += [{"org_id": org_id, "year": int(y), "kind": "income", "category": k, "amount": v} for k, v in d["income"].items()]
        lines += [{"org_id": org_id, "year": int(y), "kind": "expense", "category": k, "amount": v} for k, v in d["expenses"].items()]
        stats.append({"org_id": org_id, "year": int(y), "donors": d.get("donors"), "beneficiaries": d.get("beneficiaries")})
        grants += [{"org_id": org_id, "year": int(y), **g} for g in d.get("grants", [])]
    sb().table("financial_lines").upsert(lines, on_conflict="org_id,year,kind,category").execute()
    sb().table("org_year_stats").upsert(stats).execute()
    sb().table("grants").delete().eq("org_id", org_id).execute()
    if grants:
        sb().table("grants").insert(grants).execute()


def load_finance(org_id: str) -> dict:
    """Rebuilds finance.json shape from the database (so reports run off Supabase, not files)."""
    _need(org_id)
    years: dict = {}
    for r in sb().table("financial_lines").select("*").eq("org_id", org_id).execute().data:
        y = years.setdefault(str(r["year"]), {"income": {}, "expenses": {}, "grants": []})
        y["income" if r["kind"] == "income" else "expenses"][r["category"]] = int(r["amount"])
    for r in sb().table("org_year_stats").select("*").eq("org_id", org_id).execute().data:
        years[str(r["year"])].update(donors=r["donors"], beneficiaries=r["beneficiaries"])
    for r in sb().table("grants").select("*").eq("org_id", org_id).order("amount", desc=True).execute().data:
        years[str(r["year"])]["grants"].append({k: r[k] for k in ("grantor", "type", "purpose")} | {"amount": int(r["amount"])})
    return {"org_id": org_id, "currency": "ILS", "years": dict(sorted(years.items()))}


# ─────────── documents, extractions, chunks ───────────
def upsert_document(doc, n_tokens: int) -> None:
    sb().table("documents").upsert({
        "id": doc.id, "org_id": _need(doc.org_id), "doc_type": doc.doc_type, "title": doc.title,
        "doc_date": doc.doc_date, "source_path": doc.source_path, "content": doc.text, "n_tokens": n_tokens,
    }).execute()


def documents(org_id: str, columns: str = "id,title,doc_type,doc_date,n_tokens") -> list[dict]:
    return sb().table("documents").select(columns).eq("org_id", _need(org_id)).order("doc_date").execute().data


def upsert_extraction(org_id: str, doc_id: str, data: dict) -> None:
    sb().table("doc_extractions").upsert({"doc_id": doc_id, "org_id": _need(org_id), "data": data}).execute()


def extractions(org_id: str) -> dict[str, dict]:
    rows = sb().table("doc_extractions").select("doc_id,data").eq("org_id", _need(org_id)).execute().data
    return {r["doc_id"]: r["data"] for r in rows}


def replace_chunks(org_id: str, doc_id: str, rows: list[dict]) -> None:
    _need(org_id)
    sb().table("chunks").delete().eq("org_id", org_id).eq("doc_id", doc_id).execute()
    for i in range(0, len(rows), 50):
        sb().table("chunks").insert([{**r, "org_id": org_id, "doc_id": doc_id} for r in rows[i:i + 50]]).execute()


def chunk_counts(org_id: str) -> dict[str, int]:
    rows = sb().table("chunks").select("doc_id").eq("org_id", _need(org_id)).execute().data
    out: dict[str, int] = {}
    for r in rows:
        out[r["doc_id"]] = out.get(r["doc_id"], 0) + 1
    return out


def match_chunks(org_id: str, embedding: list[float], k: int) -> list[dict]:
    return sb().rpc("match_chunks", {"p_org_id": _need(org_id), "p_query": embedding, "p_k": k}).execute().data


# ─────────── cards, reports, evals ───────────
def save_card(org_id: str, version: int, after_doc: str | None, content: str) -> None:
    sb().table("org_cards").upsert({"org_id": _need(org_id), "version": version, "after_doc": after_doc,
                                    "content": content, "n_words": len(content.split())},
                                   on_conflict="org_id,version").execute()


def latest_card(org_id: str) -> dict | None:
    rows = (sb().table("org_cards").select("*").eq("org_id", _need(org_id))
            .order("version", desc=True).limit(1).execute().data)
    return rows[0] if rows else None


def save_report(org_id: str, content: str, model: str, cost_usd: float, meta: dict, variant: str = "correct") -> int:
    row = sb().table("reports").insert({"org_id": _need(org_id), "variant": variant, "content": content,
                                        "model": model, "cost_usd": cost_usd, "meta": meta}).execute().data[0]
    return row["id"]


def latest_report(org_id: str, variant: str = "correct") -> dict | None:
    rows = (sb().table("reports").select("*").eq("org_id", _need(org_id)).eq("variant", variant)
            .order("created_at", desc=True).limit(1).execute().data)
    return rows[0] if rows else None


def save_eval(org_id: str, report_id: int, score: float, details: dict) -> None:
    sb().table("eval_results").insert({"org_id": _need(org_id), "report_id": report_id,
                                       "score": score, "details": details}).execute()


def latest_eval(org_id: str, report_id: int) -> dict | None:
    rows = (sb().table("eval_results").select("*").eq("org_id", _need(org_id)).eq("report_id", report_id)
            .order("created_at", desc=True).limit(1).execute().data)
    return rows[0] if rows else None


# ─────────── cost ledger ───────────
def sync_ledger() -> int:
    rows = ledger.rows()
    cols = ("uid", "ts", "component", "org_id", "model", "kind", "batch", "input_tokens", "output_tokens",
            "cache_write_tokens", "cache_read_tokens", "cost_usd", "ref", "note",
            "request_id", "message_id", "batch_id")
    payload = [{c: r.get(c) for c in cols} for r in rows]
    for i in range(0, len(payload), 200):
        sb().table("api_calls").upsert(payload[i:i + 200], on_conflict="uid").execute()
    return len(payload)


def api_calls() -> list[dict]:
    """The synced ledger, for deployments that don't have the local JSONL file."""
    out, page = [], 1000
    while True:
        batch = sb().table("api_calls").select("*").order("id").range(len(out), len(out) + page - 1).execute().data
        out += batch
        if len(batch) < page:
            return out
