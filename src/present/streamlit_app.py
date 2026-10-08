"""Streamlit entrypoint. Run:

    streamlit run src/present/streamlit_app.py

Signed out, you get the landing and sign-in pages. Every app page stays registered either way,
because a URL Streamlit does not know raises its "page not found" dialog; signed out, an app page
forwards to sign-in and on to that page afterwards. Sign-in is a mock (present.auth).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from present import auth, header, routes, theme

HERE = Path(__file__).parent

st.set_page_config(
    page_title="Derivative-Implied Pricing", layout="wide", initial_sidebar_state="expanded"
)
theme.apply()

signed_in = auth.user() is not None

# Page scripts resolve relative to this file's directory. The overview owns "/" once signed in;
# before that the landing page does.
app = [
    st.Page(f"{stem}.py", title=title, default=signed_in and stem == routes.DEFAULT)
    for stem, title in routes.APP
]
landing = st.Page("landing.py", title="Derivative-Implied Pricing",
                  url_path="home" if signed_in else None, visibility="hidden", default=not signed_in)
login = st.Page("login.py", title="Sign in", url_path="login", visibility="hidden")
# Signed out, the landing page owns "/", so a stale /home link would hit "page not found".
home_alias = [] if signed_in else [
    st.Page(lambda: st.switch_page(landing), title="Home", url_path="home", visibility="hidden")
]

# position="top" puts the nav in the header as a top navbar; the sidebar is left for page
# controls. Signed out there is no app to navigate, so no nav at all.
current = st.navigation([*app, landing, login, *home_alias],
                        position="top" if signed_in else "hidden")
on_app_page = current.url_path in {p.url_path for p in app}

if on_app_page and not signed_in:
    if st.session_state.pop("signed_out", False):
        st.switch_page(landing)
    st.switch_page(login, query_params={"next": current.url_path})

if on_app_page:
    st.logo(str(HERE / "assets" / "wordmark.svg"), size="large")
    header.bar()

current.run()
