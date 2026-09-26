"""Display wording for shares of simulated futures, and the confidence page's headline metrics."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from streamlit.testing.v1 import AppTest

from views.shared import futures_count, pct, share_of_futures

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_pct_does_not_round_small_shares_to_zero_or_one():
    assert pct(0.0) == "0%"
    assert pct(0.003) == "<1%"
    assert pct(0.12) == "12%"
    assert pct(0.997) == ">99%"
    assert pct(1.0) == "100%"
    assert pct(None) == ""


def test_share_of_futures_spells_out_the_extremes():
    assert share_of_futures(0.0, 1000) == "none of the 1,000 simulated futures"
    assert share_of_futures(1.0, 1000) == "all 1,000 simulated futures"
    assert share_of_futures(0.12, 1000) == "12% of simulated futures (120 of 1,000)"
    assert futures_count(0.0, 1000) == "0 of 1,000 futures"


def _confidence_page(target_shift_days: int = 0) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=180).run()
    if target_shift_days:
        box = next(d for d in at.date_input if d.label == "Target first-fire date")
        box.set_value(box.value + timedelta(days=target_shift_days))
        next(b for b in at.button if b.label == "Run").click()
        at.run()
    at.switch_page("views/confidence.py").run()
    assert not at.exception
    return at


def test_target_equal_to_plan_is_not_shown_twice():
    labels = [m.label for m in _confidence_page().metric]
    assert "Chance of meeting plan" in labels
    assert not any(label.startswith("Chance of meeting target") for label in labels)


def test_a_different_target_gets_its_own_chance():
    labels = [m.label for m in _confidence_page(target_shift_days=120).metric]
    assert any(label.startswith("Chance of meeting target") for label in labels)
