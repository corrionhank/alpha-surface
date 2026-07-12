"""Streamlit entrypoint. Two pages: Dashboard and Docs. Run:

    streamlit run src/present/streamlit_app.py
"""

from __future__ import annotations

import streamlit as st

from present import theme

st.set_page_config(page_title="derivative-implied-pricing", layout="wide")
theme.apply()

# Page scripts resolve relative to this file's directory. position="top" puts the nav in
# the header as a top navbar; the sidebar is left for page-specific controls.
pages = [
    st.Page("dashboard.py", title="Dashboard", default=True),
    st.Page("docs_portal.py", title="Docs and Formulas"),
]
st.navigation(pages, position="top").run()
