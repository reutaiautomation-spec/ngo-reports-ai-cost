"""Reads documents from disk — the one place to change when swapping synthetic data for real files.

Expected layout (same for synthetic and real data):

    <data_dir>/<org_id>/profile.json        name, field, city, ...
    <data_dir>/<org_id>/finance.json        see README for the format
    <data_dir>/<org_id>/docs/*.md|pdf|docx  documents

Markdown files may start with a YAML front matter (title, type, date). For PDF/Word,
metadata comes from an optional sidecar `<file>.meta.json`; otherwise title = file name,
date = file modification date, type = "other".
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

SUPPORTED = {".md", ".txt", ".pdf", ".docx"}


@dataclass
class Document:
    id: str
    org_id: str
    title: str
    doc_type: str
    doc_date: str
    text: str
    source_path: str


def _read_pdf(p: Path) -> str:
    from pypdf import PdfReader
    return "\n\n".join((page.extract_text() or "") for page in PdfReader(p).pages)


def _read_docx(p: Path) -> str:
    import docx
    d = docx.Document(p)
    parts = []
    for para in d.paragraphs:
        if not para.text.strip():
            continue
        style = (para.style.name or "").lower()
        prefix = "## " if style.startswith("heading") else ""
        parts.append(prefix + para.text.strip())
    for table in d.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n\n".join(parts)


def front_matter(meta: dict) -> str:
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n"


def _split_front_matter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        return yaml.safe_load(fm) or {}, body.strip()
    return {}, raw.strip()


def load_document(p: Path, org_id: str) -> Document:
    meta: dict = {}
    if p.suffix in (".md", ".txt"):
        meta, text = _split_front_matter(p.read_text(encoding="utf-8"))
    elif p.suffix == ".pdf":
        text = _read_pdf(p)
    elif p.suffix == ".docx":
        text = _read_docx(p)
    else:
        raise ValueError(f"Unsupported file type: {p}")
    sidecar = p.with_name(p.name + ".meta.json")
    if sidecar.exists():
        meta.update(json.loads(sidecar.read_text(encoding="utf-8")))
    d = meta.get("date") or datetime.fromtimestamp(p.stat().st_mtime).date()
    stem = meta.get("slot") or p.stem
    return Document(
        id=f"{org_id}__{stem}",
        org_id=org_id,
        title=str(meta.get("title") or p.stem),
        doc_type=str(meta.get("type") or "other"),
        doc_date=d.isoformat() if isinstance(d, date) else str(d),
        text=text,
        source_path=str(p),
    )


def org_ids(data_dir: Path) -> list[str]:
    return sorted(p.name for p in data_dir.iterdir() if (p / "docs").is_dir())


def load_org_documents(data_dir: Path, org_id: str) -> list[Document]:
    files = sorted(f for f in (data_dir / org_id / "docs").iterdir() if f.suffix.lower() in SUPPORTED)
    docs = [load_document(f, org_id) for f in files]
    return sorted(docs, key=lambda d: d.doc_date)


def load_json(data_dir: Path, org_id: str, name: str):
    f = data_dir / org_id / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
