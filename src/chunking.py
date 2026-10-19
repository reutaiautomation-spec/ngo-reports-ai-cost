"""Splits a document into retrieval chunks along headings and paragraphs.

Each chunk is prefixed with the document title and its section heading, so a chunk
is understandable (and citable) on its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .settings import config


@dataclass
class Chunk:
    index: int
    text: str           # what gets embedded and shown to the model
    section: str


def _chars_budget() -> tuple[int, int]:
    c = config()["chunking"]
    cpt = c.get("chars_per_token", 2.6)
    return int(c["target_tokens"] * cpt), int(c["overlap_tokens"] * cpt)


def _blocks(text: str) -> list[tuple[str, str]]:
    """(section heading, paragraph) pairs."""
    section, out = "", []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        m = re.match(r"^#{1,6}\s+(.*)", para)
        if m and "\n" not in para:
            section = m.group(1).strip()
            continue
        if m:  # heading followed by text in the same block
            section = m.group(1).strip()
            para = para.split("\n", 1)[1].strip()
        out.append((section, para))
    return out


def chunk_document(title: str, text: str) -> list[Chunk]:
    size, overlap = _chars_budget()
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_section = ""

    def flush():
        nonlocal buf
        if buf:
            body = "\n\n".join(buf)
            header = f"[{title}]" + (f" — {buf_section}" if buf_section else "")
            chunks.append(Chunk(len(chunks), f"{header}\n{body}", buf_section))
            tail = body[-overlap:] if overlap else ""
            buf = [tail.split(" ", 1)[-1]] if tail else []

    for section, para in _blocks(text):
        if section != buf_section and buf:
            flush()
            buf = []                     # no overlap across sections
        buf_section = section
        if sum(len(b) for b in buf) + len(para) > size and buf:
            flush()
        while len(para) > size:          # very long paragraph
            buf.append(para[:size])
            para = para[size:]
            flush()
        buf.append(para)
    flush()
    return chunks
