import pandas as pd
import streamlit as st

from src import ledger
from src.settings import pricing
from views.common import calls, html_table, results_json, usd

st.title("איך לבדוק שהמספרים אמיתיים")
st.markdown("""
אין צורך לסמוך עלינו. כל מספר "בפועל" באתר מגיע מיומן שבו כל קריאה ל־Claude רשומה עם מספר הטוקנים
**ש־Anthropic עצמה החזירה** בתשובה, ואת היומן הזה אפשר להשוות לרשומות של Anthropic בשתי דרכים בלתי תלויות.
""")

rec = results_json("reconciliation.json")
df = calls()
spent = df[df["kind"].isin(ledger.SPENT_KINDS) & df["model"].str.startswith("claude")] if not df.empty else df

if rec:
    s = rec["summary"]
    c1, c2, c3 = st.columns(3)
    c1.metric("הוצאה על Claude לפי היומן", usd(s["claude_spend_usd"]))
    c2.metric(f"אומת שורה־שורה מול Anthropic ({100 * s['verified_by_batch_usd'] / s['claude_spend_usd']:.0f}%)",
              usd(s["verified_by_batch_usd"]))
    c3.metric("השאר — לבדיקה מול ה־Console", usd(s["claude_spend_usd"] - s["verified_by_batch_usd"]))

# ─────────── 1. batches ───────────
st.subheader("בדיקה 1: עבודות Batch — הורדה מחדש מ־Anthropic")
st.markdown("""
עבודות שנשלחו ב־Batch API נשמרות אצל Anthropic 29 יום. הסקריפט `scripts/08_reconcile.py` מוריד מחדש את
התוצאות של כל Batch ישירות מהשרת של Anthropic, ומשווה את מספר הטוקנים של כל בקשה לשורה המתאימה ביומן.
""")
if rec:
    rows = []
    for b in rec["batches"]:
        ta, tl = b["tokens_at_anthropic"], b["tokens_in_ledger"]
        rows.append({
            "עבודה": b["label"],
            "מזהה Batch": f'<code>{b["batch_id"]}</code>',
            "בקשות": f'{b["ledger_rows_matched"]}/{b["requests_at_anthropic"]}',
            "טוקנים אצל Anthropic": f'{sum(ta.values()):,}',
            "טוקנים ביומן": f'{sum(tl.values()):,}',
            "עלות לפי Anthropic": usd(b["cost_from_anthropic_usage"]),
            "עלות ביומן": usd(b["cost_in_ledger"]),
            "תוצאה": "✅ זהה" if b["match"] else "❌ פער",
        })
    st.markdown(html_table(pd.DataFrame(rows), {"בקשות", "טוקנים אצל Anthropic", "טוקנים ביומן",
                                                "עלות לפי Anthropic", "עלות ביומן"}), unsafe_allow_html=True)
    st.caption(f"נבדק לאחרונה: {rec['checked_at']} (UTC). עם מפתח API של החשבון אפשר לשלוף כל Batch בעצמכם: "
               "`client.messages.batches.results(\"msgbatch_...\")`.")
else:
    st.info("עדיין לא הורצה בדיקה. הרץ `scripts/08_reconcile.py`.")

# ─────────── 2. console ───────────
st.subheader("בדיקה 2: השוואה לחשבון החיוב ב־Anthropic Console")
st.markdown("""
קריאות רגילות (לא Batch) אי אפשר להוריד מחדש, ולכן בודקים אותן מול חשבון החיוב עצמו:

1. נכנסים ל־[platform.claude.com](https://platform.claude.com) ← **Usage** (טוקנים) ו־**Cost** (דולרים).
2. בוחרים את התאריכים שבטבלה למטה ומקבצים לפי מודל. התאריכים כאן לפי UTC.
3. משווים. אם אותו מפתח API שימש גם לדברים אחרים באותם ימים, החשבון יראה יותר — לכן לפרויקט אמיתי
   מומלץ מפתח או Workspace נפרד, ואז הסכומים צריכים להיות זהים.
""")
if rec:
    days = pd.DataFrame(rec["daily"])
    show = pd.DataFrame({
        "תאריך (UTC)": days["date"], "מודל": days["model"],
        "בקשות": days["requests"].map("{:,}".format),
        "מתוכן Batch": days["batch_requests"].map("{:,}".format),
        "טוקני קלט": (days["input_tokens"] + days["cache_write_tokens"] + days["cache_read_tokens"]).map("{:,}".format),
        "מתוכם מהמטמון": days["cache_read_tokens"].map("{:,}".format),
        "טוקני פלט": days["output_tokens"].map("{:,}".format),
        "עלות": days["cost_usd"].map(usd),
    })
    st.markdown(html_table(show, set(show.columns) - {"תאריך (UTC)", "מודל"}), unsafe_allow_html=True)
st.caption("מעכשיו כל קריאה רגילה נרשמת גם עם ה־request-id ש־Anthropic מחזירה, כך שאפשר לאתר כל קריאה גם מול התמיכה של Anthropic.")

# ─────────── 3. prices ───────────
st.subheader("המחירים שבהם השתמשנו")
p = pricing()
price_rows = [{"מודל": m, "קלט ($ למיליון)": v["input"], "פלט ($ למיליון)": v.get("output", "—")}
              for m, v in p["models"].items()]
st.markdown(html_table(pd.DataFrame(price_rows), {"קלט ($ למיליון)", "פלט ($ למיליון)"}), unsafe_allow_html=True)
mod = p["modifiers"]
st.caption(f"Batch: {100 * (1 - mod['batch_discount']):.0f}% הנחה · קריאה מהמטמון: {mod['cache_read']}× ממחיר הקלט · "
           f"כתיבה למטמון: {mod['cache_write_5m']}×. נבדק מול המחירון הרשמי ב־{p['checked_at']}: "
           "[Claude](https://platform.claude.com/docs/en/about-claude/pricing) · "
           "[Voyage](https://docs.voyageai.com/docs/pricing). Voyage רץ במכסה החינמית, ולכן החשבון שם יראה 0$.")

# ─────────── 4. what is not a measurement ───────────
st.subheader("מה כאן הוא הערכה ולא מדידה")
st.markdown("""
- **העלות הנאיבית ועלות הביניים לא חויבו.** הקלט נספר במדויק ב־token counting API של Anthropic; אורך הפלט הוא הנחה
  (אותו אורך כמו בגרסה הנכונה). כדי לבדוק את ההנחה, כל גרסה נאיבית הורצה באמת פעם אחת — התוצאות בטבלת האימות
  בעמוד "סיכום עלויות": הקלט יצא זהה, והעלות בטווח של כמה אחוזים.
- **חמש העמותות סינתטיות.** המסמכים שלהן נכתבו על ידי מודל כדי לדמות עמותות אמיתיות. העלויות של עיבודם אמיתיות;
  העמותות עצמן לא. הנתונים האמיתיים היחידים הם שלושה דוחות פעילות ציבוריים של החברה להגנת הטבע.
""")

# ─────────── 5. download ───────────
st.subheader("היומן המלא")
if not df.empty:
    cols = [c for c in ("ts", "component", "org_id", "model", "kind", "batch", "input_tokens", "output_tokens",
                        "cache_write_tokens", "cache_read_tokens", "cost_usd", "batch_id", "message_id",
                        "request_id", "ref", "note") if c in df.columns]
    st.download_button("הורדת כל הקריאות (CSV)", df[cols].to_csv(index=False).encode("utf-8-sig"),
                       file_name="api_calls.csv", mime="text/csv")
    st.caption(f"{len(df):,} שורות, כולל הערכות (שאינן חיוב). שורות של הוצאה בפועל: {len(spent):,}.")
