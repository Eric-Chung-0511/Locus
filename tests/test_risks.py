"""
Common risks (risk drivers): exact effect on durations and arrivals, shared
draws across the items a risk applies to, validation, monotonicity, and the
attribution table.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest
from conftest import CONFIG, START

from locus import analysis as A
from locus import distributions as dist
from locus import simulate as S
from locus.model import ModelError, Risk, load_model
from locus.weather import daily_probabilities


def _with_risks(model, *risks):
    m = copy.deepcopy(model)
    m.risks = list(risks)
    m._resolve_risks()
    return m


def _risk(rid="R", probability=1.0, effect="factor", impact=None, **applies_to):
    return Risk(id=rid, name=rid, short_name=rid, probability=probability, effect=effect,
                impact=impact or {"dist": "fixed", "value": 1.5}, applies_to=applies_to)


def _no_weather_bank(model, n=200, seed=3):
    """No weather loss at all, so durations can be read straight from finish - start."""
    H = 1500
    bank = S.RandomBank(model, n, seed, horizon=H)
    bank.prepare_weather({"rain": np.zeros(H), "wind": np.zeros(H), "none": np.zeros(H)})
    return bank


# ---------------------------------------------------------------- the effect
def test_factor_multiplies_the_sampled_duration_exactly(model):
    m = _with_risks(model, _risk(impact={"dist": "fixed", "value": 1.5}, ids=["TH_MECH", "TH_PILE"]))
    bank = _no_weather_bank(m)
    res = S.simulate(m, bank)
    for nid in ("TH_MECH", "TH_PILE"):
        i = m.index[nid]
        expected = np.maximum(np.rint(dist.sample(m.nodes[nid].duration, bank.u_node[nid]) * 1.5), 0)
        np.testing.assert_array_equal(res.finish[i] - res.start[i], expected)


def test_days_add_to_external_arrivals_exactly(model):
    m = _with_risks(model, _risk(effect="days", impact={"dist": "fixed", "value": 20}, ids=["GT_DELIV"]))
    bank = _no_weather_bank(m)
    res = S.simulate(m, bank)
    node = m.nodes["GT_DELIV"]
    expected = node.planned_day + np.rint(dist.sample(node.delay, bank.u_node["GT_DELIV"]) + 20)
    np.testing.assert_array_equal(res.node_finish("GT_DELIV"), expected)


def test_two_risks_on_one_item_multiply_and_add(model):
    m = _with_risks(model,
                    _risk("F1", impact={"dist": "fixed", "value": 1.2}, ids=["TH_MECH"]),
                    _risk("F2", impact={"dist": "fixed", "value": 1.5}, ids=["TH_MECH"]),
                    _risk("D1", effect="days", impact={"dist": "fixed", "value": 7}, ids=["TH_MECH"]))
    bank = _no_weather_bank(m)
    res = S.simulate(m, bank)
    i = m.index["TH_MECH"]
    base = dist.sample(m.nodes["TH_MECH"].duration, bank.u_node["TH_MECH"])
    np.testing.assert_array_equal(res.finish[i] - res.start[i], np.rint(base * 1.2 * 1.5 + 7))


def test_one_draw_per_iteration_is_shared_by_every_target(model):
    """The point of a common risk: in one future, all its items get the same factor."""
    m = _with_risks(model, _risk(probability=0.4, impact={"dist": "triangular", "min": 1.0, "mode": 1.1, "max": 1.4},
                                 groups=["Construction: Turbine Hall"], conditions=["productivity"]))
    bank = S.RandomBank(m, 20000, 8, horizon=400)
    factor, extra = S.risk_effects(m, bank)
    assert not extra
    arrays = [factor[t] for t in m.risks[0].targets]
    for a in arrays[1:]:
        np.testing.assert_array_equal(a, arrays[0])
    occurs = arrays[0] > 1
    assert occurs.mean() == pytest.approx(0.4, abs=0.01)
    assert np.all(arrays[0][~occurs] == 1)


def test_risk_correlates_durations_that_were_independent(model):
    m = _with_risks(model, _risk(probability=0.5, impact={"dist": "triangular", "min": 1.0, "mode": 1.1, "max": 1.3},
                                 ids=["TH_MECH", "HRSG_PP"]))
    bank = _no_weather_bank(m, n=20000)
    dur = lambda res, nid: res.finish[m.index[nid]] - res.start[m.index[nid]]
    on = S.simulate(m, bank)
    off = S.simulate(m, bank, S.Scenario(disabled_risks=frozenset({"R"})))
    assert abs(np.corrcoef(dur(off, "TH_MECH"), dur(off, "HRSG_PP"))[0, 1]) < 0.03
    assert np.corrcoef(dur(on, "TH_MECH"), dur(on, "HRSG_PP"))[0, 1] > 0.3


# ------------------------------------------------------- switching risks off
def test_disabling_every_risk_equals_a_model_without_risks(model, make_bank):
    """Same bank, risks off by scenario or never loaded: identical results."""
    assert model.risks, "the reference plant should define common risks"
    plain = load_model(CONFIG / "reference_plant.yaml", CONFIG / "rules_taiwan.yaml", with_risks=False)
    bank = make_bank(300)
    all_off = S.Scenario(disabled_risks=frozenset(r.id for r in model.risks))
    a = S.simulate(model, bank, all_off)
    b = S.simulate(plain, bank)
    np.testing.assert_array_equal(a.finish, b.finish)
    np.testing.assert_array_equal(a.driver, b.driver)


def test_risk_stream_leaves_node_and_weather_draws_unchanged():
    """SeedSequence children are keyed by position: adding a last stream changes none before it."""
    three = np.random.SeedSequence(42).spawn(3)
    four = np.random.SeedSequence(42).spawn(4)
    for a, b in zip(three, four):
        np.testing.assert_array_equal(np.random.default_rng(a).random(10), np.random.default_rng(b).random(10))


def test_delay_only_risks_never_make_anything_earlier(model, make_bank):
    assert all(dist.sample(r.impact, np.array([0.0]))[0] >= (1 if r.effect == "factor" else 0)
               for r in model.risks)
    bank = make_bank(300)
    on = S.simulate(model, bank)
    off = S.simulate(model, bank, S.Scenario(disabled_risks=frozenset(r.id for r in model.risks)))
    assert np.all(on.finish >= off.finish)


def test_horizon_covers_risks_spells_and_experiments(model, table, station, make_bank):
    extra = 20 * 7 + 21
    H = S.required_horizon(model, daily_probabilities(table, station, START, 3650), extra_days=extra)
    bank = make_bank(2000, horizon=H)
    relax_all = frozenset(l.idx for l in model.relaxable_links())
    for sc in (S.Scenario(site_start_shift=140), S.Scenario(relaxed=relax_all, site_start_shift=140),
               S.Scenario(site_start_shift=140, stoppage=(300, 21))):
        assert S.simulate(model, bank, sc).overflow_count == 0


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize("risk, message", [
    (_risk(effect="factor", ids=["GT_DELIV"]), "cannot apply to external inputs"),
    (_risk(colour=["red"]), "unknown selector"),
    (_risk(groups=["No such group"]), "matches no item"),
    (_risk(ids=["NOPE"]), "unknown item id"),
    (_risk(probability=0.0, ids=["TH_MECH"]), "probability"),
    (_risk(impact={"dist": "triangular", "min": 0, "mode": 1, "max": 2}, ids=["TH_MECH"]), "greater than 0"),
    (_risk(effect="percent", ids=["TH_MECH"]), "effect must be one of"),
])
def test_invalid_risks_are_rejected(model, risk, message):
    with pytest.raises(ModelError, match=message):
        _with_risks(model, risk)


def test_milestone_is_never_a_target(model):
    m = _with_risks(model, _risk(groups=["Gate C: first-fire items"]))
    assert m.milestone not in m.risks[0].targets


# --------------------------------------------------------------- attribution
def test_risk_contributions_are_consistent(model, make_bank):
    bank = make_bank(500)
    base = S.simulate(model, bank)
    target = float(np.quantile(base.milestone_finish(), 0.5))
    table = A.risk_contributions(model, bank, base, target)
    assert len(table) == len(model.risks) + 1 and table["combined"].iloc[-1]

    all_ids = frozenset(r.id for r in model.risks)
    none = S.simulate(model, bank, S.Scenario(disabled_risks=all_ids)).milestone_finish()
    q80 = lambda x: float(np.quantile(x, 0.8))
    total = table.iloc[-1]
    assert total["p80_gain_if_removed"] == pytest.approx(q80(base.milestone_finish()) - q80(none))

    row = table[table["id"] == "SUPPLY_CHAIN"].iloc[0]
    without = S.simulate(model, bank, S.Scenario(disabled_risks=frozenset({"SUPPLY_CHAIN"}))).milestone_finish()
    alone = S.simulate(model, bank, S.Scenario(disabled_risks=all_ids - {"SUPPLY_CHAIN"})).milestone_finish()
    assert row["p80_gain_if_removed"] == pytest.approx(q80(base.milestone_finish()) - q80(without))
    assert row["p80_added_alone"] == pytest.approx(q80(alone) - q80(none))
    # Delay-only risks: removing one never makes P80 later.
    assert (table["p80_gain_if_removed"] >= 0).all()
