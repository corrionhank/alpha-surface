"""The navigation is built from present.routes; a stem without a page file would vanish from the
nav, and a bad default would leave "/" pointing nowhere once signed in."""

from __future__ import annotations

from alphasurface.config import REPO_ROOT
from alphasurface.present import routes

PAGES = REPO_ROOT / "src" / "alphasurface" / "present"


def test_every_route_has_a_page_file():
    missing = [stem for stem, _ in routes.APP if not (PAGES / f"{stem}.py").exists()]
    assert not missing


def test_default_is_a_route():
    assert routes.DEFAULT in routes.STEMS


def test_landing_and_login_exist():
    assert (PAGES / "landing.py").exists() and (PAGES / "login.py").exists()


def test_entry_resolves_every_page():
    entry = REPO_ROOT / "src" / "alphasurface" / "app.py"
    assert entry.exists()
    for stem in [*routes.STEMS, "landing", "login"]:
        assert (entry.parent / routes.page(stem)).exists(), stem
