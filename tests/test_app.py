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
def test_every_page_renders_with_the_citation_at_the_bottom(app, key):
    app.switch_page(PAGES[key]).run()
    assert not app.exception, f"{key}: {app.exception}"
    assert app.title, f"{key}: no page title"
    # The data licence asks for the citation wherever CWA-derived numbers can appear.
    captions = [c.value for c in app.caption]
    assert any("經作者加工計算" in c and "not a forecast" in c for c in captions), key


def test_supported_actions_are_complete_and_well_worded(app):
    from locus import labels as L
    R = app.session_state["results"]
    keys = [a["key"] for a in R["actions"]]
    assert keys == ["commit", "focus", "watch", "proposals", "start"]
    commit = R["actions"][0]
    assert commit["p80_date"] == R["summary"]["p80_date"]
    for fact in R["actions"]:
        title, evidence, trade_off = L.supported_action_text(fact)
        text = " ".join((title, evidence, trade_off))
        assert title and evidence and trade_off
        assert " 1 days" not in text and "the 1 proposals" not in text
        assert "e&i" not in text                      # acronyms keep their case


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
