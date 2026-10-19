"""Component 4: the professional report (~2 pages, Hebrew).

Correct : Sonnet gets computed financials + org card + 8–10 RAG excerpts; the fixed
          instructions are cached; all orgs' reports go through one Batch.
Naive   : Sonnet gets every full document + the raw financial data; no caching, no Batch.
"""
from __future__ import annotations

import json

from . import finance, llm, rag
from .loaders import Document
from .settings import config, model_for

COMPONENT = "report"

REPORT_QUERIES = [
    "הישגים מרכזיים ונתוני השפעה בשנה האחרונה",
    "החלטות ועד מנהל ושינויים בפעילות",
    "אתגרים, סיכונים וקשיים תקציביים",
    "תוכניות ויעדים לשנה הבאה, בקשות מענק",
]

REPORT_SYSTEM = """אתה אנליסט בכיר במגזר השלישי בישראל. תפקידך לכתוב דוח מקצועי ותמציתי על עמותה,
המיועד לתורמים מוסדיים, לקרנות ולוועד המנהל. הדוח נקרא על ידי אנשים עסוקים שמחליטים על כסף —
הוא צריך להיות מדויק, מאוזן, מבוסס נתונים, ולהצביע גם על חוזקות וגם על סיכונים.

מבנה הדוח (כותרות Markdown בדיוק כך):
# דוח עמותה: <שם העמותה>
## תקציר מנהלים
3–4 משפטים: מי העמותה, מה המצב הכספי והתפעולי, והמסקנה המרכזית.
## מצב כספי ומגמות
הכנסות, הוצאות, עודף/גירעון, תמהיל מקורות ההכנסה ושינויים בו, ריכוזיות מקורות, תלות במענקים,
מספר התורמים ומגמתו, ושיעור הוצאות הנהלה וגיוס. הסבר מה המגמות אומרות — לא רק מה הן.
## פעילות והשפעה
התוכניות, מספר המוטבים ומגמתו, ותוצאות השפעה מדידות מהמסמכים.
## ממשל ואירועים מרכזיים
החלטות ועד חשובות, שינויים ארגוניים ואירועים מהתקופה האחרונה.
## סיכונים ונקודות לתשומת לב
2–4 סיכונים קונקרטיים, כל אחד עם הנימוק שלו מתוך הנתונים.
## המלצות
3–4 המלצות מעשיות לעמותה או לתורם.

כללי דיוק — מחייבים:
1. השתמש במספרים שמופיעים בחומר שקיבלת בדיוק כפי שהם. אם קיבלת אחוזים ומגמות שכבר חושבו —
   השתמש בהם ואל תחשב אחרים. אם קיבלת רק נתונים גולמיים — חשב בזהירות רק את מה שנחוץ.
   אם נתון חסר — כתוב שהוא לא זמין.
2. כל סכום כספי — במלואו ובש"ח (למשל 5,189,000 ש"ח), לא בעיגול למיליונים.
3. עובדות מהמסמכים (החלטות, אירועים, נתוני השפעה) — רק ממה שמופיע בחומר, עם ציון המקור בסוגריים
   בפעם הראשונה שהן מוזכרות, למשל: (פרוטוקול ועד, 2025-06-09).
4. אל תמציא שמות, תאריכים, תוכניות או מספרים. עדיף לכתוב פחות מאשר לכתוב משהו לא מבוסס.
5. אורך: כ־2 עמודים (700–900 מילים). עברית מקצועית, ישירה, בלי סופרלטיבים ריקים.
6. החזר רק את הדוח עצמו, בלי הקדמה ובלי הערות.
"""


def correct_request(org: dict, fin: dict, card: str, hits: list[rag.Hit]) -> llm.Req:
    m = finance.metrics(fin)
    user = (f"## עמותה\n{org['name']} — {org.get('field', '')}\n\n"
            f"## נתונים כספיים (חושבו מראש — השתמש בהם כפי שהם)\n{finance.summary_text(m)}\n\n"
            f"## כרטיס העמותה (סיכום מצטבר של כל המסמכים)\n{card}\n\n"
            f"## קטעים רלוונטיים מהמסמכים\n{rag.format_hits(hits)}\n\n"
            f"כתוב את הדוח.")
    return llm.Req(custom_id=f"report__{org['id']}", model=model_for("report"), system=REPORT_SYSTEM,
                   cache_system=True, user=user, max_tokens=12000, effort="medium", org_id=org["id"])


def retrieve_for_report(org_id: str) -> tuple[list[rag.Hit], float]:
    return rag.retrieve(org_id, REPORT_QUERIES, config()["rag"]["report_k"], COMPONENT, ref=f"report__{org_id}")


def naive_request(org: dict, fin: dict, docs: list[Document]) -> llm.Req:
    all_docs = "\n\n".join(f"<document title=\"{d.title}\" date=\"{d.doc_date}\">\n{d.text}\n</document>" for d in docs)
    user = (f"## עמותה\n{org['name']} — {org.get('field', '')}\n\n"
            f"## נתונים כספיים גולמיים (חשב בעצמך מגמות ואחוזים)\n```json\n"
            f"{json.dumps(fin, ensure_ascii=False, indent=1)}\n```\n\n"
            f"## כל מסמכי העמותה\n{all_docs}\n\nכתוב את הדוח.")
    return llm.Req(custom_id=f"naive_report__{org['id']}", model=model_for("naive"), system=REPORT_SYSTEM,
                   user=user, max_tokens=12000, effort="medium", org_id=org["id"])
