import streamlit as st

from src import chat, llm, naive
from src.ledger import BudgetExceeded, ensure_budget
from src.loaders import load_json, load_org_documents
from src.settings import path
from views.common import org_picker, usd

st.title("שאלות חופשיות על עמותה")
st.caption("החיפוש מסונן תמיד לפי העמותה שנבחרה — עמותה לעולם לא רואה מידע של עמותה אחרת.")
org = org_picker("chat_org")
data_dir = path("synthetic_dir")

samples = load_json(data_dir, org["id"], "questions.json") or []
if samples:
    st.write("שאלות לדוגמה:")
    cols = st.columns(len(samples))
    for i, (c, q) in enumerate(zip(cols, samples)):
        if c.button(q["question"], key=f"s{i}", width="stretch"):
            st.session_state["question"] = q["question"]

question = st.text_input("השאלה שלך", key="question")
if st.button("שאל", type="primary") and question.strip():
    try:
        ensure_budget(0.01, "chat question")
    except BudgetExceeded as e:
        st.error(str(e))
        st.stop()
    with st.spinner("מחפש במסמכים ועונה..."):
        ans = chat.ask(org["id"], question, ref=f"chat_ui__{org['id']}", component="chat_ui")
        docs = load_org_documents(data_dir, org["id"])
        nreq = chat.naive_request(org["id"], question, docs, f"chat_ui__{org['id']}")
        est = naive.estimate(nreq, ans.usage["output_tokens"], "chat_ui", ref=nreq.custom_id)
    st.session_state["last"] = (question, ans, est)

if "last" in st.session_state:
    q, ans, est = st.session_state["last"]
    st.markdown(f"#### {q}")
    st.markdown(ans.text)
    if ans.cited:
        st.markdown("**מקורות:** " + " · ".join(sorted({f"{h.title} ({h.doc_date})" for h in ans.cited})))
    with st.expander(f"הקטעים שנשלפו ({len(ans.sources)})"):
        for i, h in enumerate(ans.sources, 1):
            st.markdown(f"**[{i}] {h.title}** — {h.doc_date} · דמיון {h.similarity:.2f}")
            st.text(h.content[:1200])
    c1, c2, c3 = st.columns(3)
    c1.metric("עלות השאלה בפועל", usd(ans.cost), help="Haiku + embedding של השאלה")
    c2.metric("עלות נאיבית", usd(est["naive_cost"]), help=f"Sonnet עם כל {est['input_tokens']:,} הטוקנים של מסמכי העמותה")
    c3.metric("פי כמה זול יותר", f"×{est['naive_cost'] / ans.cost:,.0f}" if ans.cost else "—")
    st.caption(f"טוקני קלט: {ans.usage['input_tokens'] + ans.usage['cache_read_tokens'] + ans.usage['cache_write_tokens']:,} "
               f"מול {est['input_tokens']:,} בגרסה הנאיבית.")
