"""Mock sign-in. Session only: nothing is verified, sent or stored, and a browser refresh signs
you out. Real authentication would replace these three functions and nothing else."""

from __future__ import annotations

import streamlit as st


def user() -> str | None:
    return st.session_state.get("user")


def sign_in(email: str) -> None:
    st.session_state["user"] = email.strip()


def sign_out() -> None:
    st.session_state.pop("user", None)
    st.session_state["signed_out"] = True  # the entrypoint sends you home, not back to sign-in
