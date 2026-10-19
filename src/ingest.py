"""Component 2 (correct version): every document is processed exactly once.

  1. Haiku extracts structured JSON (Batch API, 50% off)
  2. the document is split into chunks
  3. each chunk is embedded (Voyage) and stored in pgvector with its org_id
"""
from __future__ import annotations

from . import db, llm
from .chunking import chunk_document
from .embeddings import embed
from .loaders import Document
from .settings import model_for

COMPONENT = "ingest"

EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "doc_type", "doc_date", "key_numbers", "decisions", "programs",
                 "people", "challenges", "grant_requests"],
    "properties": {
        "summary": {"type": "string", "description": "2–3 משפטים בעברית"},
        "doc_type": {"type": "string", "enum": ["annual_report", "board_protocol", "grant_application",
                                                "impact_update", "other"]},
        "doc_date": {"type": "string", "description": "YYYY-MM-DD או ריק"},
        "key_numbers": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["label", "value", "unit"],
            "properties": {"label": {"type": "string"}, "value": {"type": "number"}, "unit": {"type": "string"}}}},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "programs": {"type": "array", "items": {"type": "string"}},
        "people": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "role"],
            "properties": {"name": {"type": "string"}, "role": {"type": "string"}}}},
        "challenges": {"type": "array", "items": {"type": "string"}},
        "grant_requests": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["grantor", "amount", "purpose"],
            "properties": {"grantor": {"type": "string"}, "amount": {"type": "number"}, "purpose": {"type": "string"}}}},
    },
}

EXTRACTION_SYSTEM = """אתה מחלץ מידע מובנה ממסמכים של עמותות ישראליות (דוחות שנתיים, פרוטוקולי ועד,
בקשות מענק ועדכוני השפעה). החזר JSON לפי הסכמה בלבד.
- summary: 2–3 משפטים בעברית שמסכמים את עיקר המסמך.
- key_numbers: עד 15 המספרים החשובים במסמך (כספים, מוטבים, מתנדבים, אחוזים, יעדים), בדיוק כפי שהם
  מופיעים — אל תחשב ואל תעגל. unit: ש"ח / % / אנשים / יחידות וכד'.
- decisions: החלטות שהתקבלו (בעיקר בפרוטוקולים), כל החלטה במשפט אחד.
- people: אנשים בשמם ותפקידם. challenges: קשיים וסיכונים שעולים במסמך.
- grant_requests: בקשות מענק שמוזכרות (גוף, סכום, מטרה).
אם שדה לא רלוונטי — רשימה ריקה. אל תמציא מידע שלא מופיע במסמך."""


def extraction_request(doc: Document) -> llm.Req:
    return llm.Req(
        custom_id=f"ext__{doc.id}",
        model=model_for("simple"),
        system=EXTRACTION_SYSTEM,
        cache_system=True,
        user=f"# {doc.title}\nתאריך: {doc.doc_date}\n\n{doc.text}",
        max_tokens=3000,
        effort="low",
        thinking_off=True,
        json_schema=EXTRACTION_SCHEMA,
        org_id=doc.org_id,
        meta={"doc_id": doc.id},
    )


def extract_all(docs: list[Document], label: str) -> dict[str, dict]:
    """Batch-extract every document. Returns {doc_id: {"data": ..., "cost": ...}}."""
    reqs = [extraction_request(d) for d in docs]
    results = llm.run_batch(label, reqs, component=COMPONENT)
    out = {}
    for r in reqs:
        res = results.get(r.custom_id)
        if res is None:
            continue
        out[r.meta["doc_id"]] = {"data": res.json(), "cost": res.cost_usd, "usage": res.usage.dict()}
    return out


def chunk_and_embed(doc: Document) -> dict:
    chunks = chunk_document(doc.title, doc.text)
    vectors, tokens, cost = embed([c.text for c in chunks], "document", COMPONENT, doc.org_id, ref=doc.id)
    rows = [{"chunk_index": c.index, "content": c.text, "n_tokens": None, "embedding": v}
            for c, v in zip(chunks, vectors)]
    db.replace_chunks(doc.org_id, doc.id, rows)
    return {"chunks": len(chunks), "embed_tokens": tokens, "embed_cost": cost}
