"""Streamlit entry point:  .venv\\Scripts\\streamlit run app\\streamlit_app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

from views.common import inject_rtl  # noqa: E402

st.set_page_config(page_title="עלויות AI לדוחות עמותות", page_icon="📊", layout="wide")
inject_rtl()

pages = [
    st.Page("views/home.py", title="סיכום עלויות", icon="💰", default=True),
    st.Page("views/forecast.py", title="תחזית ל־1,000 עמותות", icon="📈"),
    st.Page("views/org.py", title="עמותה ודוח", icon="🏢"),
    st.Page("views/chat.py", title="שאלות על עמותה", icon="💬"),
    st.Page("views/how.py", title="איך זה עובד", icon="🧭"),
    st.Page("views/verify.py", title="אימות המספרים", icon="🔍"),
]
st.navigation(pages).run()
