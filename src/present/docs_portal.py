"""Docs page: renders the repo's markdown docs, including the formula sheet.

Display-math blocks are rendered with st.latex because Streamlit's markdown parser
mishandles multi-line $$...$$ blocks (it mis-pairs the delimiters and turns the rest
of the doc into one KaTeX error). Prose and inline $...$ go through st.markdown.
"""

from __future__ import annotations

import re

import streamlit as st

from config import REPO_ROOT
from present import theme

# (label, path relative to repo root)
DOCS: list[tuple[str, str]] = [
    ("Formulas and metrics", "docs/formulas.md"),
    ("Dashboard", "docs/dashboard.md"),
    ("Scanner", "docs/scanner.md"),
    ("Requirements", "docs/requirements.md"),
    ("Data schema", "docs/schema.md"),
    ("Open decisions", "docs/open-decisions.md"),
    ("Project brief", "Project-Breif.md"),
    ("Architecture", "CLAUDE.md"),
    ("Development principles", ".claude/Development-Principles.md"),
    ("AI policy", "docs/ai-policy.md"),
    ("README", "README.md"),
    ("Context handoff", "docs/AI-CONTEXT.md"),
]

_DISPLAY_MATH = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)


def render_doc(text: str) -> None:
    """Render markdown, sending $$...$$ display blocks to st.latex and the rest to st.markdown."""
    pos = 0
    for m in _DISPLAY_MATH.finditer(text):
        prose = text[pos:m.start()]
        if prose.strip():
            st.markdown(prose)
        st.latex(m.group(1).strip())
        pos = m.end()
    tail = text[pos:]
    if tail.strip():
        st.markdown(tail)


theme.intro("Docs and formulas", eyebrow="Reference")

available = [(label, rel) for label, rel in DOCS if (REPO_ROOT / rel).exists()]

with st.sidebar:
    st.header("Documents")
    choice = st.radio("Open", [lbl for lbl, _ in available], label_visibility="collapsed")
    query = st.text_input("Find in page", placeholder="e.g. Sharpe")

rel = dict(available)[choice]
text = (REPO_ROOT / rel).read_text(encoding="utf-8")

matches = None
if query:
    blocks = [b for b in text.split("\n\n") if query.lower() in b.lower()]
    matches = f"{len(blocks)} matches for '{query}'"
    text = "\n\n".join(blocks) if blocks else "_No matches._"
with theme.card("doc"):
    theme.panel_head(choice, matches or rel)
    render_doc(text)
