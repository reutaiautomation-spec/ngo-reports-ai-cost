import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import costs
from src.settings import config
from views.common import COLORS, LABELS, calls, docs_table, html_table, usd

st.title("תחזית: 1,000 עמותות, 12 חודשים")
st.caption("התחזית מבוססת על העלויות שנמדדו בהדגמה (עלות ליחידה, טוקנים למסמך), ומכפילה אותן לפי הפרמטרים.")

df, docs = calls(), docs_table()
if df.empty or docs.empty:
    st.info("צריך קודם להריץ את שלבי הקליטה, הכרטיס, הדוח והצ'אט.")
    st.stop()

f = config()["forecast"]
c1, c2, c3, c4 = st.columns(4)
orgs = c1.number_input("מספר עמותות", 1, 100_000, f["orgs"], step=100)
docs_pm = c2.number_input("מסמכים חדשים לעמותה בחודש", 1, 200, f["docs_per_month"])
reports_pm = c3.number_input("דוחות לעמותה בחודש", 0, 30, f["reports_per_month"])
q_pm = c4.number_input("שאלות לעמותה בחודש", 0, 1000, f["questions_per_month"])
months = f["months"]

u = costs.measure_units(df, docs)
fc = costs.forecast(u, orgs, months, docs_pm, reports_pm, q_pm)

tot = {k: fc[c].sum() for k, c in [("naive", "נאיבי"), ("middle", "ביניים"), ("correct", "נכון")]}
k1, k2, k3, k4 = st.columns(4)
k1.metric("נאיבי — 12 חודשים", usd(tot["naive"], big=True))
k2.metric("ביניים — 12 חודשים", usd(tot["middle"], big=True))
k3.metric("ארכיטקטורה נכונה — 12 חודשים", usd(tot["correct"], big=True))
k4.metric("חיסכון שנתי מול נאיבי", usd(tot["naive"] - tot["correct"], big=True),
          f"{100 * (1 - tot['correct'] / tot['naive']):.1f}%" if tot["naive"] else None, delta_color="off")

fig = go.Figure()
for key, col, dash in [("naive", "נאיבי", "solid"), ("middle", "ביניים", "dash"), ("correct", "נכון", "solid")]:
    fig.add_trace(go.Scatter(
        x=fc["חודש"], y=fc[col], name=LABELS[key], mode="lines+markers",
        line=dict(color=COLORS[key], width=2, dash=dash), marker=dict(size=8),
        hovertemplate="%{y:$,.0f}<extra>" + LABELS[key] + "</extra>"))
    last = fc.iloc[-1]
    fig.add_annotation(x=last["חודש"], y=last[col], text=f"  {usd(last[col], big=True)}", showarrow=False,
                       xanchor="left", font=dict(size=13))
fig.update_layout(
    title="עלות חודשית כוללת (דולר)", hovermode="x unified", height=460,
    margin=dict(l=80, r=90, t=50, b=10), legend=dict(orientation="h", y=-0.15),
    xaxis=dict(title="חודש", dtick=1, showgrid=False),
    yaxis=dict(title=None, tickprefix="$", tickformat=",.0f", gridcolor="rgba(128,128,128,.18)", rangemode="tozero",
               automargin=True),
)
st.plotly_chart(fig, width="stretch", theme="streamlit")

first, last = fc.iloc[0], fc.iloc[-1]
st.markdown(f"""
**מה רואים בגרף:** בגרסה הנאיבית כל דוח וכל שאלה שולחים את **כל ההיסטוריה** של העמותה. בחודש 1 יש
{int(first['מסמכים בהיסטוריה'])} מסמכים לעמותה, ובחודש {months} כבר {int(last['מסמכים בהיסטוריה'])} — ולכן העלות החודשית
עולה מ־{usd(first['נאיבי'], big=True)} ל־{usd(last['נאיבי'], big=True)}.
בארכיטקטורה הנכונה הדוח מקבל כרטיס בגודל קבוע ו־{config()['rag']['report_k']} קטעים רלוונטיים, ולכן העלות נשארת
**יציבה**: {usd(first['נכון'], big=True)} בחודש.
""")
if fc["חורג מחלון ההקשר"].any():
    m = int(fc[fc["חורג מחלון ההקשר"]]["חודש"].min())
    st.warning(f"מחודש {m} ההיסטוריה של עמותה כבר לא נכנסת לחלון ההקשר של המודל (מיליון טוקנים) — "
               "הגרסה הנאיבית פשוט מפסיקה לעבוד, לא רק מתייקרת.")

with st.expander("פירוט לפי חודש"):
    show = fc[["חודש", "מסמכים בהיסטוריה", "טוקנים בהיסטוריה", "נאיבי", "ביניים", "נכון",
               "נאיבי — דוח", "נאיבי — צ'אט", "נאיבי — כרטיס", "נכון — דוח", "נכון — צ'אט", "נכון — קליטה וכרטיס"]].copy()
    money = [c for c in show.columns if c not in ("חודש", "מסמכים בהיסטוריה", "טוקנים בהיסטוריה")]
    for c in money:
        show[c] = show[c].map(lambda x: usd(x, big=True))
    show["טוקנים בהיסטוריה"] = show["טוקנים בהיסטוריה"].map("{:,}".format)
    st.markdown(html_table(show, set(show.columns) - {"חודש"}), unsafe_allow_html=True)

with st.expander("הנחות המודל (נמדדו בהדגמה)"):
    st.markdown(html_table(pd.DataFrame([
        {"פרמטר": "עלות קליטת מסמך (חילוץ + embeddings)", "ערך": usd(u.ingest_per_doc)},
        {"פרמטר": "עלות עדכון כרטיס עמותה", "ערך": usd(u.card_per_doc)},
        {"פרמטר": "עלות דוח (נכון)", "ערך": usd(u.report)},
        {"פרמטר": "עלות שאלה (נכון)", "ערך": usd(u.chat_per_q)},
        {"פרמטר": "טוקנים ממוצעים למסמך (עברית)", "ערך": f"{u.doc_tokens:,.0f}"},
        {"פרמטר": "אורך פלט דוח / תשובה / כרטיס (טוקנים)", "ערך": f"{u.report_output:,.0f} / {u.chat_output:,.0f} / {u.card_output:,.0f}"},
        {"פרמטר": "חישוב כספי נאיבי לכל דוח", "ערך": usd(u.naive_finance)},
        {"פרמטר": "שאלות ברצף שנהנות ממטמון (ביניים)", "ערך": str(config()["middle"]["chat_questions_per_session"])},
    ]), {"ערך"}), unsafe_allow_html=True)
    st.caption("ההיסטוריה מתחילה מ־0 מסמכים בחודש הראשון. מחירים מ־pricing.yaml.")
