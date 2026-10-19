"""Component 5: free-form questions about one org.

Correct : question -> embedding -> pgvector search filtered by org_id -> Haiku answers from the
          retrieved excerpts only, citing the source document.
Naive   : the question + every full document of the org, to Sonnet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import llm, rag
from .loaders import Document
from .settings import config, model_for

COMPONENT = "chat"

CHAT_SYSTEM = """אתה עוזר שעונה על שאלות לגבי עמותה אחת, על סמך קטעים ממסמכי העמותה בלבד.
- ענה בעברית, בקצרה ולעניין (2–5 משפטים), עם המספרים והשמות בדיוק כפי שהם מופיעים בקטעים.
- אחרי כל טענה, ציין את מספר הקטע שעליו היא מבוססת בסוגריים מרובעים, למשל [2].
- אם התשובה לא מופיעה בקטעים — אמור זאת במפורש ("המידע לא מופיע במסמכים שבידי") ואל תנחש.
- אל תשתמש בידע כללי או במידע על עמותות אחרות."""


@dataclass
class Answer:
    text: str
    sources: list[rag.Hit]
    cited: list[rag.Hit]
    llm_cost: float
    embed_cost: float
    usage: dict

    @property
    def cost(self) -> float:
        return self.llm_cost + self.embed_cost


def correct_request(org_id: str, question: str, hits: list[rag.Hit], ref: str) -> llm.Req:
    return llm.Req(custom_id=ref, model=model_for("simple"), system=CHAT_SYSTEM, cache_system=True,
                   user=f"<excerpts>\n{rag.format_hits(hits)}\n</excerpts>\n\nשאלה: {question}",
                   max_tokens=1500, effort="low", thinking_off=True, org_id=org_id)


def ask(org_id: str, question: str, ref: str = "chat", component: str = COMPONENT) -> Answer:
    """component: "chat" for the measured demo set, "chat_ui" for live questions (kept out of the tables)."""
    hits, embed_cost = rag.retrieve(org_id, [question], config()["rag"]["chat_k"], component, ref=ref)
    res = llm.call(correct_request(org_id, question, hits, ref), component=component)
    ids = {int(x) for x in re.findall(r"\[(\d+)\]", res.text)}
    cited = [h for i, h in enumerate(hits) if i + 1 in ids]
    return Answer(res.text.strip(), hits, cited, res.cost_usd, embed_cost, res.usage.dict())


def naive_request(org_id: str, question: str, docs: list[Document], ref: str) -> llm.Req:
    all_docs = "\n\n".join(f"<document title=\"{d.title}\" date=\"{d.doc_date}\">\n{d.text}\n</document>" for d in docs)
    return llm.Req(custom_id=f"naive_{ref}", model=model_for("naive"),
                   system=CHAT_SYSTEM.replace("קטעים", "מסמכים").replace("מספר הקטע", "שם המסמך"),
                   user=f"<documents>\n{all_docs}\n</documents>\n\nשאלה: {question}",
                   max_tokens=1500, org_id=org_id)
