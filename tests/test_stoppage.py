"""
Forced stoppage (Scenario.stoppage): a window of days lost to all weather-sensitive
work on top of the simulated weather. Checked against a brute-force reference that
zeroes the window in the workable-day matrix, and against the invariants a
stoppage must satisfy in the full network.
"""

from __future__ import annotations

import numpy as np
import pytest
from conftest import START
from test_weather import _reference_finish

from locus import analysis as A
from locus import simulate as S
from locus.weather import daily_persistence, daily_probabilities


@pytest.mark.parametrize("window", [(0, 7), (50, 7), (120, 14), (390, 10), (200, 1)])
@pytest.mark.parametrize("spells", [False, True])
def test_stoppage_matches_brute_force(model, table, station, window, spells):
    H, N = 400, 200
    bank = S.RandomBank(model, N, 21, horizon=H)
    bank.prepare_weather(daily_probabilities(table, station, START, H),
                         daily_persistence(table, station, START, H) if spells else None)
    a, n = window
    for kind in ("rain", "wind"):
        ok = ~bank.lost_days(kind)
        ok[:, a:a + n] = False                                  # the forced stoppage
        rs = np.random.default_rng(a + n)
        start = rs.integers(-3, H + 3, N).astype(float)
        work = rs.integers(0, 150, N).astype(float)
        finish, overflow = S._weather_finish(start, work, bank.weather_arrays(kind), H, (a, n))
        expected = [_reference_finish(ok[r], int(start[r]), int(work[r]), H) for r in range(N)]
        np.testing.assert_array_equal(finish, [e[0] for e in expected])
        assert overflow == sum(e[1] for e in expected)


def test_stoppage_outside_horizon_is_rejected(make_bank):
    bank = make_bank(100, horizon=400)
    with pytest.raises(ValueError, match="inside the horizon"):
        S._weather_finish(np.zeros(100), np.ones(100), bank.weather_arrays("rain"), 400, (395, 7))


def test_stoppage_never_makes_anything_earlier(model, make_bank):
    """Losing days can only delay work, and the forward pass is monotone: no node finishes earlier."""
    bank = make_bank(300)
    base = S.simulate(model, bank)
    for a in (0, 60, 180, 300, 450):
        res = S.simulate(model, bank, S.Scenario(stoppage=(a, 7)))
        assert np.all(res.finish >= base.finish)
        assert np.all(res.start >= base.start)


def test_stoppage_after_all_weather_work_changes_nothing(model, make_bank):
    bank = make_bank(300)
    base = S.simulate(model, bank)
    wx = [model.index[n] for n, v in model.nodes.items() if v.weather != "none"]
    after = int(base.finish[wx].max()) + 1
    res = S.simulate(model, bank, S.Scenario(stoppage=(after, 7)))
    np.testing.assert_array_equal(res.finish, base.finish)


def test_stoppage_without_weather_loss_delays_by_the_window(model):
    """With no weather loss at all, work crossing a 7-day stoppage finishes exactly 7 days later."""
    H = 400
    bank = S.RandomBank(model, 60, 2, horizon=H)
    bank.prepare_weather({"rain": np.full(H, 0.0), "wind": np.full(H, 0.0), "none": np.zeros(H)})
    base = S.simulate(model, bank)
    res = S.simulate(model, bank, S.Scenario(stoppage=(10, 7)))
    pile = model.index["TH_PILE"]                              # starts day 0, weather work
    np.testing.assert_array_equal(res.finish[pile], base.finish[pile] + 7)


def test_vulnerability_curve_is_consistent(model, make_bank):
    bank = make_bank(300)
    base = S.simulate(model, bank)
    curve = A.stoppage_sweep(model, bank, base, days=7, step=28)
    assert (curve["p50_shift_days"] >= 0).all() and (curve["mean_shift_days"] >= 0).all()
    # Direct recomputation of one point.
    row = curve.iloc[3]
    res = S.simulate(model, bank, S.Scenario(stoppage=(int(row["first_day"]), 7)))
    shift = res.milestone_finish() - base.milestone_finish()
    assert row["mean_shift_days"] == pytest.approx(shift.mean())
