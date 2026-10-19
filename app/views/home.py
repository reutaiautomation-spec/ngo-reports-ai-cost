import pandas as pd
import streamlit as st

from src import costs
from src import db
from views.common import calls, html_table, orgs, pct, results_json, usd

st.title("כמה עולה AI לדוחות עמותות?")
st.caption("כל המספרים כאן נמדדו: עלות בפועל לפי שדה ה־usage שה־API מחזיר בכל קריאה; "
           "עלות נאיבית לפי ספירת טוקנים מדויקת (token counting API) של אותה בקשה בגרסה הנאיבית.")

df = calls()
if df.empty:
    st.info("עדיין אין קריאות רשומות. הרץ את הסקריפטים לפי הסדר (ראה README).")
    st.stop()

table = costs.component_table(df)
total = table.iloc[-1]
spent = costs.spent_summary(df)

c1, c2, c3, c4 = st.columns(4)
c1.metric("עלות נאיבית (כל ההדגמה)", usd(total["נאיבי"]))
c2.metric("עלות בפועל", usd(total["בפועל"]))
c3.metric("חיסכון", pct(total["חיסכון %"]), usd(total["חיסכון $"]) + " פחות", delta_color="off")
# "\$" — two bare dollar signs in one metric value are rendered as a LaTeX formula
c4.metric("הוצאה כוללת מתוך תקציב", f"{usd(spent['total_spent'])} / ${spent['budget']:.0f}".replace("$", "\\$"),
          help="כולל יצירת הנתונים הסינתטיים וריצות האימות הנאיביות")

st.subheader("השוואה לפי רכיב")
show = pd.DataFrame({
    "רכיב": table["רכיב"],
    "עלות נאיבית": table["נאיבי"].map(usd),
    "ביניים*": table["ביניים"].map(usd),
    "עלות בפועל": table["בפועל"].map(usd),
    "חיסכון $": table["חיסכון $"].map(usd),
    "חיסכון %": table["חיסכון %"].map(pct),
    "קריאות API": table["קריאות"],
})
st.markdown(html_table(show, {"עלות נאיבית", "ביניים*", "עלות בפועל", "חיסכון $", "חיסכון %", "קריאות API"},
                       total_last=True), unsafe_allow_html=True)
st.caption("""
\\* **ביניים** = אותו Sonnet עם כל המסמכים המלאים (בלי RAG ובלי כרטיס עמותה), אבל עם Batch API לעבודה שלא דחופה
ועם prompt caching לשאלות שנשאלות ברצף. העמודה מראה כמה מהחיסכון מגיע מ"טריקים" של תמחור, וכמה מהארכיטקטורה עצמה.

**קליטת מסמכים** היא השקעה חד־פעמית: בגרסה הנאיבית אין עיבוד מקדים ולכן עלותה 0$ — אבל המחיר משולם שוב ושוב
בכל דוח ובכל שאלה (שורות 3–5), כי המסמכים המלאים נשלחים מחדש בכל פעם.
""")

st.subheader("עלות ליחידה")
act, est = df[df["kind"] == "actual"], df[df["kind"] == "naive_estimate"]


def per_unit(component: str, by: str = "ref") -> tuple[float, float]:
    a = act[act["component"] == component].groupby(by)["cost_usd"].sum()
    n = est[est["component"] == component].groupby(by)["cost_usd"].sum()
    return (a.mean() if len(a) else None), (n.mean() if len(n) else None)


units = []
for label, comp, by in [("חישוב כספי לעמותה", "finance", "org_id"), ("עדכון כרטיס (למסמך חדש)", "card", "ref"),
                        ("דוח לעמותה", "report", "org_id"), ("שאלה בצ'אט", "chat", "ref")]:
    a, n = per_unit(comp, by)
    units.append({"פעולה": label, "נאיבי": usd(n), "בפועל": usd(a),
                  "פי כמה זול יותר": f"×{n / a:,.0f}" if a and n else ("∞ (0$)" if n and a == 0 else "—")})
ing = act[act["component"] == "ingest"]
n_docs = ing[ing["model"].str.startswith("voyage")]["ref"].nunique()
if n_docs:
    units.insert(1, {"פעולה": "קליטת מסמך (חילוץ + embeddings, חד־פעמי)", "נאיבי": usd(0),
                     "בפועל": usd(ing["cost_usd"].sum() / n_docs), "פי כמה זול יותר": "השקעה"})
st.markdown(html_table(pd.DataFrame(units), {"נאיבי", "בפועל", "פי כמה זול יותר"}), unsafe_allow_html=True)

chat_rs = results_json("chat_samples.json")
if chat_rs:
    st.subheader("האם החיסכון פגע באיכות?")
    n = len(chat_rs)
    ok = sum(r.get("verdict") == "correct" for r in chat_rs)
    refusals = [r for r in chat_rs if r.get("verdict") == "correct_refusal"]
    st.markdown(f"**צ'אט:** {ok}/{n} תשובות נכונות עם הפניה למסמך המקור"
                + (f", ועוד {len(refusals)} סירוב נכון (המידע באמת לא היה במסמכים — המערכת לא המציאה תשובה)."
                   if refusals else "."))
    for r in refusals:
        st.caption(f"• {r['question']} — {r.get('review_note', '')}")

scores = []
for o in orgs():
    rep = db.latest_report(o["id"])
    ev = db.latest_eval(o["id"], rep["id"]) if rep else None
    if ev:
        scores.append((o["name"], ev["score"], ev["details"]["facts_found"]))
if scores:
    st.markdown("**דוחות:** " + " · ".join(f"{n} — ציון {s:.0f}, עובדות {f}/5" for n, s, f in scores))
    st.caption("ציון = עובדות ידועות שנמצאו × שיעור המספרים המגובים בנתונים. מספרים 'לא מגובים' בדוחות נבדקו ידנית: "
               "כולם יחסים שהמודל חישב נכון (למשל 'כ־75% מההכנסות תלויים בקרנות ובממשלה' — בפועל 74.7%).")

val = results_json("validation.json")
st.subheader("אימות: האם ההערכה הנאיבית מדויקת?")
if not val:
    st.info("ריצות האימות עוד לא בוצעו (scripts/06_validate_naive.py).")
else:
    st.write(f"הרצנו כל גרסה נאיבית **באמת** פעם אחת, על עמותה אחת (`{val['org_id']}`), והשווינו להערכה:")
    rows = [{"רכיב": r["component"], "קלט מוערך": f"{r['est_input']:,}", "קלט שחויב": f"{r['real_input']:,}",
             "סטייה בקלט": f"{r['input_diff_pct']:+.1f}%", "פלט מוערך": f"{r['assumed_output']:,}",
             "פלט אמיתי": f"{r['real_output']:,}", "עלות מוערכת": usd(r["est_cost"]), "עלות אמיתית": usd(r["real_cost"]),
             "סטייה בעלות": f"{r['cost_diff_pct']:+.0f}%"} for r in val["rows"]]
    st.markdown(html_table(pd.DataFrame(rows), {"קלט מוערך", "קלט שחויב", "סטייה בקלט", "פלט מוערך", "פלט אמיתי",
                                                 "עלות מוערכת", "עלות אמיתית", "סטייה בעלות"}), unsafe_allow_html=True)
    max_in = max(abs(r["input_diff_pct"]) for r in val["rows"])
    st.caption(f"הסטייה המקסימלית בספירת הקלט: {max_in:.1f}%. הסטייה בעלות נובעת בעיקר מאורך הפלט — ההערכה מניחה "
               "פלט באורך הפלט של הגרסה הנכונה, וטוקני חשיבה של Sonnet נספרים כפלט.")
    fa = val["finance_accuracy"]
    wrong = fa["wrong"]
    st.markdown(f"**סיכון דיוק בחישובים כספיים:** מתוך {fa['checked']} מספרים ש־Sonnet חישב מהנתונים הגולמיים, "
                f"**{len(wrong)} שגויים** (בקוד: 0 שגיאות, 0$).")
    if wrong:
        st.markdown(html_table(pd.DataFrame([{"שנה": w["year"], "מדד": w["field"], "בקוד": f"{w['code']:,}",
                                              "ה־AI חישב": f"{w['ai']:,}"} for w in wrong]),
                               {"בקוד", "ה־AI חישב"}), unsafe_allow_html=True)
    q = val.get("report_quality", {})
    if q:
        st.markdown(f"**איכות הדוח:** ציון הדוח הנאיבי {q['naive_score']} מול {q['correct_score']} בגרסה הנכונה.")
