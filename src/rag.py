"""Retrieval: question(s) -> embedding -> pgvector search filtered by org_id -> chunks with sources."""
from __future__ import annotations

from dataclasses import dataclass

from . import db
from .embeddings import embed


@dataclass
class Hit:
    doc_id: str
    title: str
    doc_date: str
    chunk_index: int
    content: str
    similarity: float


def retrieve(org_id: str, queries: list[str], k: int, component: str, ref: str | None = None) -> tuple[list[Hit], float]:
    """Top-k chunks of ONE org for one or more queries (merged by best similarity). Returns (hits, embed cost)."""
    vectors, _, cost = embed(queries, "query", component, org_id, ref=ref)
    titles = {d["id"]: d for d in db.documents(org_id)}
    best: dict[int, dict] = {}
    for v in vectors:
        for row in db.match_chunks(org_id, v, k):
            if row["doc_id"] not in titles:                 # defence in depth: never another org's chunk
                raise RuntimeError(f"isolation violation: chunk {row['id']} not in org {org_id}")
            if row["id"] not in best or row["similarity"] > best[row["id"]]["similarity"]:
                best[row["id"]] = row
    top = sorted(best.values(), key=lambda r: -r["similarity"])[:k]
    hits = [Hit(r["doc_id"], titles[r["doc_id"]]["title"], str(titles[r["doc_id"]]["doc_date"]),
                r["chunk_index"], r["content"], r["similarity"]) for r in top]
    return hits, cost


def format_hits(hits: list[Hit]) -> str:
    return "\n\n".join(
        f"<excerpt id=\"{i + 1}\" source=\"{h.title}\" date=\"{h.doc_date}\">\n{h.content}\n</excerpt>"
        for i, h in enumerate(hits))
