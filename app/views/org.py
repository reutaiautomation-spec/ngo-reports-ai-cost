import pandas as pd
import streamlit as st

from src import db
from views.common import html_table, org_picker, usd

st.title("עמותה: הדוח שהופק")
org = org_picker()

rep = db.latest_report(org["id"])
if not rep:
    st.info("עדיין לא הופק דוח לעמותה הזו (scripts/04_reports.py).")
    st.stop()
ev = db.latest_eval(org["id"], rep["id"])
meta = rep["meta"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("ציון איכות", f"{ev['score']:.0f}/100" if ev else "—",
          help="עובדות ידועות שנמצאו × שיעור המספרים בדוח שמגובים בנתונים")
c2.metric("עלות הדוח בפועל", usd(rep["cost_usd"]), help="Sonnet ב־Batch + embeddings לשאילתות החיפוש")
c3.metric("עלות נאיבית לאותו דוח", usd(meta.get("naive_cost")))
if meta.get("naive_cost"):
    c4.metric("פי כמה זול יותר", f"×{meta['naive_cost'] / rep['cost_usd']:,.0f}")

u = meta.get("usage", {})
st.caption(f"טוקני קלט: {u.get('input_tokens', 0) + u.get('cache_read_tokens', 0) + u.get('cache_write_tokens', 0):,} "
           f"(מתוכם מהמטמון: {u.get('cache_read_tokens', 0):,}) · פלט: {u.get('output_tokens', 0):,} · "
           f"בגרסה הנאיבית הקלט היה {meta.get('naive_input_tokens', 0):,} טוקנים")

tab_r, tab_q, tab_c, tab_n = st.tabs(["הדוח", "בדיקת איכות", "כרטיס העמותה", "השוואה לדוח נאיבי"])
with tab_r:
    st.markdown(f'<div class="report-box">\n\n{rep["content"]}\n\n</div>', unsafe_allow_html=True)
    if meta.get("sources"):
        with st.expander(f"הקטעים שנשלפו מ־RAG ({len(meta['sources'])})"):
            for s in meta["sources"]:
                st.write(f"- {s['title']} ({s['date']}) — דמיון {s['similarity']}")

with tab_q:
    if ev:
        d = ev["details"]
        st.markdown(f"**עובדות ידועות:** {d['facts_found']}/5 נמצאו בדוח עם הערך הנכון")
        st.markdown(html_table(pd.DataFrame([
            {"עובדה": f["label"], "ערך נכון": (f"{f.get('grantor', '')} " if f.get("grantor") else "") + f"{f['value']:,}",
             "בדוח": "✅ נמצא" if f["found"] else "❌ חסר / שגוי"} for f in d["facts"]]), {"ערך נכון"}),
            unsafe_allow_html=True)
        st.markdown(f"**מספרים לא מגובים:** נבדקו {d['numbers_checked']} מספרים בדוח; "
                    f"{len(d['unsupported_numbers'])} לא נמצאו בנתונים או במסמכים.")
        if d["unsupported_numbers"]:
            st.write("מספרים לבדיקה: " + ", ".join(f"`{x}`" for x in d["unsupported_numbers"]))
        st.caption("מספרים קטנים מ־10 ושנים לא נבדקים. מספר 'לא מגובה' יכול להיות גם חישוב תקין שה־AI עשה בעצמו — "
                   "ולכן הוא מסומן לבדיקה, לא בהכרח שגיאה.")

with tab_c:
    card = db.latest_card(org["id"])
    if card:
        st.caption(f"גרסה {card['version']} · {card['n_words']} מילים · עודכן אחרי המסמך {card['after_doc']}")
        st.markdown(card["content"])

with tab_n:
    nrep = db.latest_report(org["id"], variant="naive_validation")
    if not nrep:
        st.info("הדוח הנאיבי הורץ באמת רק על עמותה אחת (לאימות). בחר אותה כדי לראות את ההשוואה.")
    else:
        nev = db.latest_eval(org["id"], nrep["id"])
        a, b = st.columns(2)
        a.metric("ציון — גרסה נכונה", f"{ev['score']:.0f}" if ev else "—", help=usd(rep["cost_usd"]))
        b.metric("ציון — גרסה נאיבית", f"{nev['score']:.0f}" if nev else "—", help=usd(nrep["cost_usd"]))
        st.caption(f"עלות: {usd(rep['cost_usd'])} (נכון) מול {usd(nrep['cost_usd'])} (נאיבי, הרצה אמיתית)")
        st.markdown(f'<div class="report-box">\n\n{nrep["content"]}\n\n</div>', unsafe_allow_html=True)
