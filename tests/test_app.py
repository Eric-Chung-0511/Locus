"""The app under Streamlit's AppTest: every page renders, and results change only when Run is pressed."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from views.shared import PAGES

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(scope="module")
def app():
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception
    return at


@pytest.mark.parametrize("key", list(PAGES))
def test_every_page_renders(app, key):
    app.switch_page(PAGES[key]).run()
    assert not app.exception, f"{key}: {app.exception}"
    assert app.title, f"{key}: no page title"


def test_start_here_is_the_landing_page():
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert at.title[0].value == "Start here"


def _run_button(at):
    return next(b for b in at.button if b.label == "Run")


def test_changing_a_setting_without_run_keeps_the_results():
    at = AppTest.from_file(APP, default_timeout=300).run()
    before = at.session_state["results"]["summary"]["p80_day"]
    next(n for n in at.number_input if n.label == "Random seed").set_value(7)
    at.run()
    assert at.session_state["results"]["summary"]["p80_day"] == before
    assert any("Press Run" in c.value for c in at.caption)
    _run_button(at).click()
    at.run()
    assert at.session_state["run_params"]["seed"] == 7


def test_delays_to_test_reach_the_results_after_run():
    at = AppTest.from_file(APP, default_timeout=300).run()
    base = at.session_state["results"]["summary"]
    next(n for n in at.number_input if n.label.startswith("Site handover")).set_value(120)
    _run_button(at).click()
    at.run()
    R = at.session_state["results"]
    assert R["extra_days"] == {"SITE_HANDOVER": 120.0}
    assert R["summary"]["plan_day"] == base["plan_day"]           # the plan keeps its dates
    assert R["summary"]["p50_day"] > base["p50_day"] + 30         # the simulation carries the delay
