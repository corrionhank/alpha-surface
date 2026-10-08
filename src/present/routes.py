"""App pages as (file stem, nav title). The entrypoint builds the navigation from this list and
the sign-in page uses it to send you on to the page a link asked for."""

from __future__ import annotations

APP = [
    ("overview", "Overview"),
    ("option_chain", "Chain"),
    ("scanner", "Scanner"),
    ("scenarios", "Scenarios"),
    ("chart", "Charts"),
    ("vol_surface", "Vol Surface"),
    ("pricing", "Black-Scholes"),
    ("pot_odds", "Pot Odds"),
    ("docs_portal", "Docs"),
]
DEFAULT = "overview"
STEMS = {stem for stem, _ in APP}
