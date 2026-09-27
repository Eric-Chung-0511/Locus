"""Why the single-number plan misses: expected values, the point plans and the exact split of the gap."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from locus import analysis as A
from locus import distributions as dist
from locus import labels as L
from locus.simulate import RandomBank, Scenario, deterministic_plan, point_plan, simulate
from locus.weather import daily_probabilities

from conftest import START

OFF = Scenario(ignore_weather=True)
U = (np.arange(400_000) + 0.5) / 400_000


@pytest.fixture(scope="module")
def daily(table, station):
    return daily_probabilities(table, station, START, 1410)


@pytest.mark.parametrize("spec", [
    {"dist": "triangular", "min": 60, "mode": 75, "max": 100},
    {"dist": "triangular", "min": 0, "mode": 0, "max": 30},
    {"dist": "lognormal", "median": 30, "p90": 60},
    {"dist": "fixed", "value": 12},
])
def test_mean_value_matches_the_sampled_mean(spec):
    assert dist.mean_value(spec) == pytest.approx(dist.sample(spec, U).mean(), rel=1e-4)


def test_point_plan_with_typical_values_is_the_deterministic_plan(model, daily):
    for scen in (OFF, Scenario()):
        assert point_plan(model, daily, scen) == deterministic_plan(model, daily, scen)[model.milestone][1]


def test_point_plan_rejects_unknown_choices(model, daily):
    with pytest.raises(ValueError, match="durations"):
        point_plan(model, daily, OFF, durations="p80")
    with pytest.raises(ValueError, match="deliveries"):
        point_plan(model, daily, OFF, deliveries="early")


@pytest.mark.parametrize("scen", [OFF, Scenario()])
def test_steps_add_up_to_the_simulated_mean(model, make_bank, daily, scen):
    base = simulate(model, make_bank(), scen)
    gap = A.plan_gap(model, make_bank(), daily, base)
    finish = base.milestone_finish()
    assert gap["plan_day"] == point_plan(model, daily, scen)
    assert gap["mean_day"] == pytest.approx(finish.mean())
    assert gap["plan_day"] + gap["steps"]["days"].sum() == pytest.approx(gap["mean_day"])
    assert list(gap["steps"]["step"]) == list(A.GAP_STEPS)
    # Delays start at zero and every range skews late in the reference plant.
    steps = gap["steps"].set_index("step")["days"]
    assert steps["deliveries"] > 0 and steps["durations"] > 0 and steps["risks"] > 0
    assert gap["weather_applied"] == (not scen.ignore_weather)


def test_all_steps_vanish_when_nothing_is_uncertain(model, table, station, daily):
    """
    Degenerate case: fixed durations and delays, no common risks, no weather.
    Every future is the plan, so every step of the gap is exactly zero.
    """
    fixed = copy.deepcopy(model)
    fixed.risks = []
    for node in fixed.nodes.values():
        if node.duration is not None:
            node.duration = {"dist": "fixed", "value": dist.typical_value(node.duration)}
        if node.delay is not None:
            node.delay = {"dist": "fixed", "value": 0}
    bank = RandomBank(fixed, 100, 3, horizon=1410)
    bank.prepare_weather(daily, None)
    gap = A.plan_gap(fixed, bank, daily, simulate(fixed, bank, OFF))
    assert gap["steps"]["days"].abs().max() == pytest.approx(0.0, abs=1e-9)
    assert gap["mean_day"] == gap["plan_day"] == gap["p80_day"]
    assert not gap["has_risks"]


def test_risk_step_is_zero_when_the_risks_are_switched_off(model, make_bank, daily):
    scen = Scenario(ignore_weather=True, disabled_risks=frozenset(r.id for r in model.risks))
    gap = A.plan_gap(model, make_bank(), daily, simulate(model, make_bank(), scen))
    assert not gap["has_risks"]
    assert gap["steps"].set_index("step").loc["risks", "days"] == 0
    assert "risks" not in set(A.plan_gap_days(gap)["step"])


@pytest.mark.parametrize("scen", [OFF, Scenario()])
def test_whole_days_shown_add_up_to_the_totals_shown(model, make_bank, daily, scen):
    base = simulate(model, make_bank(), scen)
    gap = A.plan_gap(model, make_bank(), daily, base)
    shown = A.plan_gap_days(gap).set_index("step")["days"]
    assert all(isinstance(v, (int, np.integer)) for v in shown)
    assert shown[list(A.GAP_STEPS)].sum() == shown["mean"]
    assert shown["mean"] + shown["spread"] == shown["p80"]
    assert shown["p80"] == round(gap["p80_day"] - gap["plan_day"])


def test_plan_gap_wording_is_complete_and_short():
    for key in (*A.GAP_STEPS, "mean", "spread", "p80"):
        for weather in (False, True):
            assert 0 < len(L.plan_gap_label(key, weather)) <= L.CHART_LABEL_MAX
            assert L.plan_gap_text(key, weather)
    for key in A.GAP_STEPS:
        assert L.PLAN_GAP_STEPS[key]["action"] and L.plan_gap_phrase(key)
