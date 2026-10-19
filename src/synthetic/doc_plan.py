"""Which documents each org gets, what goes in them, the 5 known facts and the sample questions."""
from __future__ import annotations

from ..finance import summary_text

# slot, doc type, date, pages, finance years shown to the writer
SLOTS = [
    ("bp2024a", "board_protocol", "2024-02-18", 3, ["2023"]),
    ("ga2024", "grant_application", "2024-04-10", 6, ["2023"]),
    ("ar2023", "annual_report", "2024-04-28", 7, ["2022", "2023"]),
    ("iu2024a", "impact_update", "2024-07-15", 2, []),
    ("bp2024b", "board_protocol", "2024-11-12", 4, ["2023"]),
    ("iu2024b", "impact_update", "2025-01-20", 3, []),
    ("ar2024", "annual_report", "2025-04-27", 8, ["2023", "2024"]),
    ("bp2025a", "board_protocol", "2025-06-09", 3, ["2024"]),
    ("ga2025", "grant_application", "2025-09-02", 7, ["2024"]),
    ("iu2025", "impact_update", "2025-12-22", 3, []),
    ("bp2026a", "board_protocol", "2026-02-16", 4, ["2025"]),
    ("ar2025", "annual_report", "2026-04-26", 10, ["2024", "2025"]),
]

# slots each org does NOT get -> 12/10/9/11/8 documents (50 total)
DROPPED = {
    "youth": set(),
    "elderly": {"ga2024", "iu2024a"},
    "education": {"bp2024a", "iu2024a", "bp2026a"},
    "health": {"iu2024a"},
    "environment": {"bp2024a", "ga2024", "iu2024a", "bp2024b"},
}

TYPE_HE = {
    "annual_report": "דוח מילולי שנתי",
    "board_protocol": "פרוטוקול ישיבת ועד מנהל",
    "grant_application": "בקשת מענק",
    "impact_update": "עדכון השפעה",
}

TYPE_GUIDE = {
    "annual_report": "מבנה: דבר יו\"ר הוועד; דבר המנכ\"ל/ית; סקירת פעילות מפורטת לכל תוכנית; נתוני השפעה ומוטבים; "
                     "סקירה כספית (רק המספרים שניתנו); צוות, מתנדבים ושותפים; אתגרים ולקחים; יעדים לשנה הבאה.",
    "board_protocol": "מבנה: מספר ישיבה, תאריך, נוכחים ונעדרים (בשמות), סדר יום ממוספר, דיון בכל סעיף עם ציטוטים "
                      "קצרים של משתתפים, והחלטות ממוספרות בסוף כל סעיף. סגנון יבש ופורמלי של פרוטוקול.",
    "grant_application": "מבנה: פרטי הארגון; רקע וצורך (עם נתונים על האוכלוסייה); תיאור התוכנית המוצעת; יעדים ומדדי "
                         "הצלחה; לוח זמנים; תקציב מבוקש בחלוקה לסעיפים; קיימות והמשכיות; צוות מוביל.",
    "impact_update": "מבנה: תקציר; נתונים מרכזיים מול יעדים; סיפור אישי של משתתף/ת (שם בדוי); ציטוטים; "
                     "מה למדנו; מה הלאה. סגנון חם, מיועד לתורמים.",
}


def org_slots(org_id: str) -> list[tuple]:
    return [s for s in SLOTS if s[0] not in DROPPED[org_id]]


def grantor_for(org: dict, slot: str) -> str:
    text = " ".join(org["details"].get(slot, []))
    for name, _ in org["finance"]["grantors"]:
        # Hebrew prefixes swallow the definite article: "המשרד" appears as "למשרד" after ל
        core = name[1:] if name.startswith("ה") else name
        if core in text:
            return name
    return next(n for n, k in org["finance"]["grantors"] if k == "foundation")


def doc_title(org: dict, slot: str, dtype: str, date: str) -> str:
    year = date[:4]
    if dtype == "annual_report":
        return f"{TYPE_HE[dtype]} לשנת {slot[2:]} — {org['name']}"
    if dtype == "grant_application":
        return f"{TYPE_HE[dtype]} ל{grantor_for(org, slot)} — {org['name']} ({year})"
    if dtype == "board_protocol":
        return f"{TYPE_HE[dtype]} — {org['name']}, {date}"
    return f"{TYPE_HE[dtype]} — {org['name']}, {date[:7]}"


def facts(org: dict, m: dict) -> list[dict]:
    """5 known facts per org, checked automatically in every generated report."""
    y, py = "2025", "2024"
    d = m["by_year"][y]
    lg = d["largest_grant"]
    return [
        {"id": "income_2025", "label": "סך ההכנסות ב־2025", "type": "ils", "value": d["income_total"]},
        {"id": "income_growth_2025", "label": f"שינוי בהכנסות {py}→{y} (%)", "type": "pct",
         "value": d["growth_pct"]["income_total"]},
        {"id": "donors_2025", "label": "מספר התורמים ב־2025", "type": "int", "value": d["donors"]},
        {"id": "largest_grant_2025", "label": "המענק הגדול ביותר ב־2025", "type": "grant",
         "value": lg["amount"], "grantor": lg["grantor"]},
        {"id": "beneficiaries_2025", "label": "מספר המוטבים ב־2025", "type": "int", "value": d["beneficiaries"]},
    ]


def fact_text(f: dict) -> str:
    if f["type"] == "grant":
        return f"{f['grantor']} — {f['value']:,} ש\"ח"
    if f["type"] == "ils":
        return f"{f['value']:,} ש\"ח"
    if f["type"] == "pct":
        return f"{f['value']:+.1f}%"
    return f"{f['value']:,}"


def finance_context(m: dict, years: list[str]) -> str:
    years = [y for y in years if y in m["by_year"]]
    return summary_text(m, years) if years else ""


SYSTEM = """אתה כותב מסמכים פנימיים ריאליסטיים של עמותות ישראליות, לצורך הדגמה של מערכת ניתוח מסמכים.
המסמכים צריכים להיראות ולהישמע כמו מסמכים אמיתיים שעמותה בישראל כותבת: עברית תקנית ועניינית, מינוח
מקובל במגזר השלישי (מוטבים, ועד מנהל, ועדת ביקורת, רשם העמותות, סעיף 46, מתנדבים, תורמים, קרנות),
ופרטים קונקרטיים: שמות של אנשי צוות ומשתתפים (בדויים), שכונות, תאריכים, אירועים, קשיים ופתרונות.

כללים מחייבים:
1. מספרים כספיים: השתמש אך ורק בסכומים, באחוזים ובנתונים הכספיים שמופיעים בבלוק "נתונים כספיים",
   בדיוק כפי שהם כתובים (אותו סכום, אותו עיגול). אל תחשב בעצמך סכומים, הפרשים, אחוזים או ממוצעים חדשים,
   ואל תמציא סכומים כספיים שאינם מופיעים שם. מותר לכתוב סכומים של תקציב מבוקש בבקשת מענק רק אם הם
   מופיעים בפרטים שחובה לשלב.
2. "פרטים שחובה לשלב" — שלב כל אחד מהם באופן טבעי במקום המתאים במסמך, עם אותם מספרים ושמות בדיוק.
   אל תסתור אותם ואל תשנה אותם בשום מקום אחר במסמך.
3. מספרים לא־כספיים אחרים (מספר משתתפים בפעילות מסוימת, מספר מפגשים וכד') — מותר, בהיקף סביר
   ועקבי עם מספר המוטבים השנתי שניתן.
4. אורך: כתוב מסמך מלא באורך היעד שצוין (במילים). אל תקצר, אל תסכם במקום לפרט, ואל תכתוב
   "וכו'" או "[השלם כאן]". מסמך ארוך נבנה מתוכן ממשי: פירוט פעילויות, דוגמאות, ציטוטים ודיונים.
5. פורמט: Markdown. כותרת ראשית אחת (#) עם שם המסמך, ואחריה כותרות משנה (##, ###), פסקאות,
   ורשימות היכן שמתאים. בלי טבלאות HTML. בלי הקדמה או הערות מחוץ למסמך עצמו — רק המסמך.
6. אל תזכיר שהמסמך סינתטי, בדוי או נכתב לצורך הדגמה.
"""


def user_prompt(org: dict, fin_raw: dict, m: dict, slot: str, dtype: str, date: str, pages: int,
                years: list[str], words_per_page: int) -> str:
    programs = "\n".join(f"- {name}: {desc}" for name, desc in org["programs"])
    details = org["details"].get(slot, [])
    is_final_report = slot == "ar2025"
    if is_final_report:
        details = details + [f"{f['label']}: {fact_text(f)}" for f in facts(org, m)]
    fin = finance_context(m, years)
    parts = [
        f"## העמותה\nשם: {org['name']}\nתחום: {org['field']}\nשנת הקמה: {org['founded']}\nמיקום: {org['city']}, {org['region']}",
        f'מנכ"ל/ית: {org["ceo"]}; יו"ר הוועד: {org["chair"]}; גזבר/ית: {org["treasurer"]}',
        f"ייעוד: {org['mission']}",
        f"תוכניות:\n{programs}",
        f"מספר מוטבים שנתי: " + ", ".join(f"{y}: {n:,}" for y, n in org["beneficiaries"].items()),
        f"\n## המסמך לכתיבה\nסוג: {TYPE_HE[dtype]}\nכותרת: {doc_title(org, slot, dtype, date)}\nתאריך: {date}",
        f"אורך יעד: כ־{pages * words_per_page:,} מילים (כ־{pages} עמודים).",
        f"הנחיות מבנה: {TYPE_GUIDE[dtype]}",
    ]
    if dtype == "grant_application":
        grantor = grantor_for(org, slot)
        year = str(min(int(date[:4]), 2025))
        amount = next((g["amount"] for g in fin_raw["years"][year]["grants"] if g["grantor"] == grantor), None)
        parts.append(f"הגוף שאליו מוגשת הבקשה: {grantor}")
        if amount:
            parts.append(f"סכום המענק המבוקש: {amount:,} ש\"ח. בסעיף התקציב מותר לפרק אותו לסעיפים, "
                         f"בתנאי שסכום הסעיפים שווה בדיוק לסכום המבוקש.")
    if fin:
        parts.append(f"\n## נתונים כספיים (להשתמש רק בהם, כפי שהם)\n{fin}")
    if details:
        parts.append("\n## פרטים שחובה לשלב\n" + "\n".join(f"- {d}" for d in details))
    return "\n".join(parts)


def questions(org: dict) -> list[dict]:
    return [{"question": q, "source_slot": slot, "expected": " ".join(org["details"][slot])}
            for q, slot in org["questions"]]
