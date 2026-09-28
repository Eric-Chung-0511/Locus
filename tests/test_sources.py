"""Site handover, design and tested delays; keyed random streams; the split of the gap by source."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import numpy as np
import pytest

from locus import analysis as A
from locus.model import ModelError, Node, load_model
from locus.simulate import (RandomBank, Scenario, delays, deterministic_plan, point_plan, required_horizon,
                            simulate)
from locus.weather import daily_probabilities

from conftest import CONFIG, START

OFF = Scenario(ignore_weather=True)


@pytest.fixture(scope="module")
def daily(table, station):
    return daily_probabilities(table, station, START, 1410)


def finish_of(res, nid):
    return res.finish[res.model.index[nid]]


def start_of(res, nid):
    return res.start[res.model.index[nid]]


# ----------------------------------------------------------- random streams
def test_adding_a_node_leaves_every_other_draw_unchanged(model):
    bigger = copy.deepcopy(model)
    bigger.nodes["EXTRA_ITEM"] = Node(id="EXTRA_ITEM", name="Extra", group="Design", kind="external",
                                      condition="design", short_name="Extra", planned_day=0,
                                      delay={"dist": "fixed", "value": 0})
    a, b = RandomBank(model, 200, 11, horizon=400), RandomBank(bigger, 200, 11, horizon=400)
    assert set(b.u_node) - set(a.u_node) == {"EXTRA_ITEM"}
    for nid, u in a.u_node.items():
        np.testing.assert_array_equal(u, b.u_node[nid])


def test_node_streams_differ_between_nodes_and_seeds(model):
    a, b = RandomBank(model, 200, 11, horizon=400), RandomBank(model, 200, 12, horizon=400)
    assert not np.array_equal(a.u_node["TH_PILE"], a.u_node["TH_FDN"])
    assert not np.array_equal(a.u_node["TH_PILE"], b.u_node["TH_PILE"])


def test_ids_sharing_a_stream_are_rejected():
    # "plumless" and "buckeroo" have the same CRC-32, so they would share a stream.
    fake = SimpleNamespace(nodes={"plumless": None, "buckeroo": None}, risks=[])
    with pytest.raises(ValueError, match="share a random stream"):
        RandomBank(fake, 100, 1, horizon=400)


# ----------------------------------------------------------- tested delays
def test_tested_delays_move_arrivals_and_durations_but_not_the_plan(model, make_bank, daily):
    bank = make_bank()
    base = simulate(model, bank, OFF)
    late = simulate(model, bank, Scenario(ignore_weather=True,
                                          extra_days=delays({"FDN_IFC": 45, "STEEL_SHOP_DWG": 10})))
    np.testing.assert_array_equal(finish_of(late, "FDN_IFC"), finish_of(base, "FDN_IFC") + 45)
    shop = lambda r: finish_of(r, "STEEL_SHOP_DWG") - start_of(r, "STEEL_SHOP_DWG")
    np.testing.assert_array_equal(shop(late), shop(base) + 10)
    plan = deterministic_plan(model, daily, OFF)
    assert deterministic_plan(model, daily, late.scenario) == plan


def test_design_delay_within_float_is_absorbed_and_beyond_it_passes_through(model, make_bank):
    """Piling design IFC is planned 30 days before piling: up to 30 days late costs nothing."""
    bank = make_bank()
    base = simulate(model, bank, OFF)
    within = simulate(model, bank, Scenario(ignore_weather=True, extra_days=delays({"PILE_IFC": 25})))
    beyond = simulate(model, bank, Scenario(ignore_weather=True, extra_days=delays({"PILE_IFC": 50})))
    np.testing.assert_array_equal(start_of(within, "TH_PILE"), start_of(base, "TH_PILE"))
    np.testing.assert_array_equal(within.milestone_finish(), base.milestone_finish())
    assert np.all(start_of(beyond, "TH_PILE") == 20)


def test_late_start_moves_the_site_handover_too(model, make_bank):
    """The late-start experiment shifts the handover events, so it stacks on a tested handover delay."""
    bank = make_bank()
    held = Scenario(ignore_weather=True, extra_days=delays({"SITE_HANDOVER": 28}))
    res = simulate(model, bank, Scenario(ignore_weather=True, site_start_shift=28,
                                         extra_days=held.extra_days))
    assert np.all(finish_of(res, "SITE_HANDOVER") == 56)
    assert np.all(start_of(res, "TH_PILE") >= 56)


def test_defaults_add_nothing(model, make_bank):
    """Handover and design are on time by default: they never set a start later than the plan does."""
    res = simulate(model, make_bank(), OFF)
    for nid in ("SITE_HANDOVER", "START_APPROVAL", "PILE_IFC", "FDN_IFC", "OEM_FDN_DWG", "STEEL_IFC"):
        assert np.all(finish_of(res, nid) == model.nodes[nid].planned_day)


def test_horizon_grows_with_tested_delays(model, daily):
    base = required_horizon(model, daily)
    longer = required_horizon(model, daily, tested=delays({"SITE_HANDOVER": 300}))
    assert longer > base


# ----------------------------------------------------------- delay sources
def test_every_item_belongs_to_exactly_one_source(model):
    members = [nid for s in model.delay_sources for nid in s.members]
    assert sorted(members) == sorted(model.nodes)
    assert model.source_of("SITE_HANDOVER") == "handover"
    assert model.source_of("PILE_IFC") == "design"
    assert model.source_of("STEEL_FAB") == "supply"
    assert model.source_of("GSU_ENERGISATION") == "permits"      # regulatory wins over its Gate 0 group
    assert model.source_of("GATE_A") == "commissioning"
    assert model.source_of("TH_PILE") == "site"


def test_an_item_without_a_source_is_rejected(tmp_path):
    text = (CONFIG / "reference_plant.yaml").read_text(encoding="utf-8")
    cut = text.index("  - key: site")
    broken = text[:cut] + text[text.index("risks:", cut):]
    path = tmp_path / "plant.yaml"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(ModelError, match="belongs to no delay source"):
        load_model(path, CONFIG / "rules_taiwan.yaml")


@pytest.mark.parametrize("scen", [OFF, Scenario()])
def test_source_split_adds_up_and_matches_the_mechanism_split(model, make_bank, daily, scen):
    bank = make_bank()
    base = simulate(model, bank, scen)
    by_source = A.source_gap(model, bank, daily, base)
    by_mechanism = A.plan_gap(model, bank, daily, base)
    assert by_source["plan_day"] + by_source["steps"]["days"].sum() == pytest.approx(by_source["mean_day"])
    assert by_source["mean_day"] == pytest.approx(by_mechanism["mean_day"])
    assert by_source["p80_day"] == by_mechanism["p80_day"]
    shown_s = A.plan_gap_days(by_source).set_index("step")["days"]
    shown_m = A.plan_gap_days(by_mechanism).set_index("step")["days"]
    assert shown_s["mean"] == shown_m["mean"] and shown_s["p80"] == shown_m["p80"]
    assert shown_s["risks"] == shown_m["risks"]                     # same raw value, same number
    steps = by_source["steps"].set_index("step")["days"]
    assert steps["handover"] == 0 and steps["design"] == 0          # on time by default
    assert ("weather" in steps.index) == (not scen.ignore_weather)
    assert list(steps.index[:6]) == [s.key for s in model.delay_sources]


def test_a_tested_handover_delay_shows_in_its_own_bar(model, make_bank, daily):
    bank = make_bank()
    base = simulate(model, bank, Scenario(ignore_weather=True, extra_days=delays({"SITE_HANDOVER": 60})))
    steps = A.source_gap(model, bank, daily, base)["steps"].set_index("step")["days"]
    assert steps["handover"] > 10


def test_tightest_item_skips_the_project_starters(model, make_bank):
    base = simulate(model, make_bank(), OFF)
    latest = A.latest_dates(base, START, base.milestone_finish().min(), 0.8)
    worst = A.tightest_item(latest, model)
    assert model.nodes[worst["id"]].condition != "handover"


# ----------------------------------------------------------- commissioning order
COMMISSIONING = ("Gate A: condenser vacuum", "Gate B: GT spin", "Gate C: first-fire items")


@pytest.mark.parametrize("scen", [OFF, Scenario()])
def test_commissioning_gates_follow_power_feeding(model, make_bank, scen):
    """Every Gate A, B and C item starts after power feeding, in every simulated future."""
    res = simulate(model, make_bank(), scen)
    fed = finish_of(res, "GSU_POWER_FEED")
    for nid, node in model.nodes.items():
        if node.group in COMMISSIONING:
            assert np.all(start_of(res, nid) >= fed), f"{nid} can start before power feeding"


def test_every_group_is_listed_in_display_order(model):
    assert {n.group for n in model.nodes.values()} <= set(model.groups)
    order = [model.groups.index(g) for g in ("Gate 0: power receipt", *COMMISSIONING)]
    assert order == sorted(order)


@pytest.mark.parametrize("scen", [OFF, Scenario()])
def test_commissioning_follows_mechanical_completion(model, make_bank, scen):
    """Turbine hall, HRSG and stack work (with their E&I) finish before any commissioning starts."""
    res = simulate(model, make_bank(), scen)
    done = finish_of(res, "MECH_COMPLETE")
    for nid in ("TH_EI", "TH_MECH", "HRSG_EI", "STACK_MECH"):
        assert np.all(finish_of(res, nid) <= done), nid
    for nid, node in model.nodes.items():
        if node.group in COMMISSIONING:
            assert np.all(start_of(res, nid) >= done), f"{nid} can start before mechanical completion"


def test_construction_phases_end_before_commissioning_in_the_plan(model, daily):
    plan = deterministic_plan(model, daily, OFF)
    spans = {}
    for nid, (s, f) in plan.items():
        g = model.nodes[nid].group
        lo, hi = spans.get(g, (s, f))
        spans[g] = (min(lo, s), max(hi, f))
    commissioning_start = min(spans[g][0] for g in COMMISSIONING)
    for g in ("Construction: Turbine Hall", "Construction: HRSG", "Construction: stack"):
        assert spans[g][1] <= commissioning_start, g
