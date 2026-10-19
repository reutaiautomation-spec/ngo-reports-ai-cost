"""Component 3 (correct version): an incrementally updated org card (<= ~1,500 words).

On each new document, Haiku gets ONLY the current card + the new document and returns
the updated card. Cost per update stays flat no matter how much history accumulates.
"""
from __future__ import annotations

from . import llm
from .loaders import Document
from .settings import config, model_for

COMPONENT = "card"

CARD_SYSTEM = f"""אתה מתחזק "כרטיס עמותה": סיכום חי ומצטבר של כל מה שידוע על עמותה, שנבנה מסמך אחר מסמך.
הכרטיס משמש בסיס לדוחות מקצועיים לתורמים ולוועד, ולכן הוא חייב להיות מדויק, תמציתי ומבוסס מקורות.

תקבל את הכרטיס הנוכחי (או "אין כרטיס עדיין") ומסמך חדש אחד. החזר את הכרטיס המעודכן המלא — רק אותו,
בלי הקדמה ובלי הסברים — במבנה הקבוע הבא (כותרות Markdown בדיוק כך):

## זהות ופעילות
## תוכניות
## נתונים מרכזיים
## החלטות ואירועים
## אתגרים וסיכונים
## אנשי מפתח
## ציר זמן

כללים:
1. מזג את המידע החדש לסעיף המתאים. אם המסמך החדש מעדכן נתון קיים — החלף אותו וציין את השנה.
   שמור נתונים היסטוריים חשובים (למשל מספר מוטבים לפי שנה) בשורה אחת כשהם מראים מגמה.
2. כל מספר, החלטה או אירוע — בדיוק כפי שהופיע במסמך, עם תגית מקור קצרה: [מקור: <סוג המסמך>, <YYYY-MM>],
   למשל [מקור: פרוטוקול ועד, 2025-06]. אל תחשב מספרים חדשים ואל תעגל.
3. אורך — זו מגבלה קשיחה, לא המלצה: הכרטיס כולו עד {config()['card']['target_words']} מילים, ולעולם לא יותר
   מ־{config()['card']['max_words']}. תקציב לפי סעיף (מילים, בערך):
   זהות ופעילות 70 · תוכניות 130 · נתונים מרכזיים 220 · החלטות ואירועים 300 · אתגרים וסיכונים 130 ·
   אנשי מפתח 70 · ציר זמן 200.
   כשסעיף עובר את התקציב — דחוס: אחד פריטים דומים, קצר ניסוחים, והשמט אירועים תפעוליים קטנים ישנים.
   לעולם אל תמחק החלטות ועד מהותיות, נתוני השפעה מרכזיים או אנשי מפתח.
4. "ציר זמן": שורה אחת לכל מסמך שנקלט, עד 12 מילים לשורה: תאריך — סוג — העיקר.
5. נקודות קצרות, בלי משפטי פתיחה וסיכום, בלי חזרות בין סעיפים. עברית עניינית.
   אל תמציא מידע שלא מופיע בכרטיס או במסמך.
"""


def card_user(card: str | None, doc: Document) -> str:
    current = card if card else "אין כרטיס עדיין."
    return (f"<current_card>\n{current}\n</current_card>\n\n"
            f"<new_document title=\"{doc.title}\" date=\"{doc.doc_date}\" type=\"{doc.doc_type}\">\n"
            f"{doc.text}\n</new_document>")


def update_request(card: str | None, doc: Document) -> llm.Req:
    return llm.Req(
        custom_id=f"card__{doc.id}",
        model=model_for("simple"),
        system=CARD_SYSTEM,
        cache_system=True,
        user=card_user(card, doc),
        max_tokens=10000,                  # a 1,500-word Hebrew card is ~6K tokens
        effort="medium",
        thinking_off=True,
        org_id=doc.org_id,
    )


COMPACT_SYSTEM = """אתה מקבל "כרטיס עמותה" שחרג מאורכו המותר. החזר את אותו כרטיס, באותו מבנה ובאותן
כותרות, בדיוק באורך שיתבקש. דחוס: אחד פריטים דומים, קצר ניסוחים, השמט אירועים תפעוליים קטנים וישנים,
ושמור שורת מגמה אחת לנתונים שחוזרים לפי שנה. לעולם אל תשמיט: החלטות ועד מהותיות, נתוני השפעה מרכזיים,
אנשי מפתח, ותגיות מקור. אל תשנה מספרים ואל תוסיף מידע. החזר רק את הכרטיס."""


def words(text: str) -> int:
    return len(text.split())


def update(card: str | None, doc: Document) -> list[llm.Result]:
    """Update the card with one new document; compact it in a second call if it ran over the limit.

    The limit is enforced in code because the model does not count words reliably.
    """
    results = [llm.call(update_request(card, doc), component=COMPONENT)]
    text = results[0].text.strip()
    if words(text) > config()["card"]["max_words"]:
        target = config()["card"]["compact_to_words"]
        results.append(llm.call(llm.Req(
            custom_id=f"card_compact__{doc.id}", model=model_for("simple"), system=COMPACT_SYSTEM, cache_system=True,
            user=f"אורך נוכחי: {words(text)} מילים. אורך יעד: {target} מילים לכל היותר.\n\n<card>\n{text}\n</card>",
            max_tokens=10000, effort="medium", thinking_off=True, org_id=doc.org_id), component=COMPONENT))
    return results


def naive_request(history: list[Document]) -> llm.Req:
    """Naive: no card — rebuild the summary from the full history with Sonnet every time."""
    docs = "\n\n".join(f"<document title=\"{d.title}\" date=\"{d.doc_date}\">\n{d.text}\n</document>" for d in history)
    return llm.Req(
        custom_id=f"naive_card__{history[-1].id}",
        model=model_for("naive"),
        system=CARD_SYSTEM,
        user=f"<current_card>\nאין כרטיס עדיין.\n</current_card>\n\n{docs}",
        max_tokens=10000,
        org_id=history[-1].org_id,
    )
