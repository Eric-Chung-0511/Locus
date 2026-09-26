"""
Weather statistics from daily records, the wind policy, and the shipped CWA table.
Statistics are checked against day-by-day references; the policy against its
algebra and against the engine; the table against the licence wording rules.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest
from conftest import ROOT, START

from locus import simulate as S
from locus import analysis as A
from locus.weather import (WeatherError, WeatherRule, daily_exceedance, daily_persistence,
                           daily_probabilities, has_spells, monthly_loss, threshold_options,
                           transition_probabilities)
from locus.weather_stats import extend_stoppage, gust_factor, monthly_spell_stats

sys.path.insert(0, str(ROOT / "scripts"))
import build_weather_table as B  # noqa: E402


def _series(seed=0, years=3, p=0.3, missing=0.03):
    rs = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=365 * years, freq="D")
    x = (rs.random(len(idx)) < p).astype(float)
    x[rs.random(len(idx)) < missing] = np.nan
    return pd.Series(x, index=idx)


# ---------------------------------------------------------- daily statistics
def test_monthly_spell_stats_matches_a_day_by_day_count():
    x = _series()
    got = monthly_spell_stats(x)
    for m in range(1, 13):
        lost = known = lost_prev_known = runs = 0
        for i, (d, v) in enumerate(x.items()):
            if d.month != m or np.isnan(v):
                continue
            known += 1
            lost += v == 1
            prev = x.iloc[i - 1] if i > 0 else np.nan
            if v == 1 and not np.isnan(prev):
                lost_prev_known += 1
                runs += prev == 0
        p = lost / known
        L = max(lost_prev_known / runs, 1 / (1 - p))
        assert got.loc[m, "p"] == pytest.approx(p)
        assert got.loc[m, "mean_spell_days"] == pytest.approx(L)


def test_spell_length_of_known_runs():
    idx = pd.date_range("2021-03-01", periods=31, freq="D")
    x = pd.Series(0.0, index=idx)
    x.iloc[[2, 3, 4, 10, 11, 20]] = 1.0                    # runs of 3, 2 and 1 day
    st = monthly_spell_stats(x).loc[3]
    assert st["runs"] == 3 and st["lost_days"] == 6 and st["mean_spell_days"] == pytest.approx(2.0)


def test_a_missing_day_breaks_a_run():
    idx = pd.date_range("2021-03-01", periods=31, freq="D")
    x = pd.Series(0.0, index=idx)
    x.iloc[[5, 6, 8, 9]] = 1.0
    x.iloc[7] = np.nan                                      # 0 1 1 ? 1 1
    st = monthly_spell_stats(x).loc[3]
    # Known (yesterday, today) pairs with today lost: (0,1) (1,1) (1,1); day 8 is skipped
    # because its yesterday is missing. P(yesterday workable | lost) = 1/3, so L = 3.
    assert st["runs"] == 1                                  # the gap does not create a run start
    assert st["mean_spell_days"] == pytest.approx(3.0)


@pytest.mark.parametrize("r", [0, 1, 2])
def test_extend_stoppage_matches_brute_force(r):
    x = _series(seed=3, p=0.2, missing=0.05)
    got = extend_stoppage(x, r)
    v = x.to_numpy()
    for i in range(len(v)):
        window = v[max(0, i - r):i + 1]
        want = 1.0 if np.any(window == 1) else (np.nan if np.any(np.isnan(window)) else 0.0)
        assert (np.isnan(want) and np.isnan(got.iloc[i])) or got.iloc[i] == want


def test_remobilisation_extends_each_run_and_merges_close_ones():
    idx = pd.date_range("2021-05-01", periods=31, freq="D")
    x = pd.Series(0.0, index=idx)
    x.iloc[[2, 3]] = 1.0                                    # run of 2
    x.iloc[[10, 13]] = 1.0                                  # two single days, 2 apart
    ext = extend_stoppage(x, 2)
    assert list(np.flatnonzero(ext.to_numpy() == 1)) == [2, 3, 4, 5, 10, 11, 12, 13, 14, 15]


def test_gust_factor_ignores_light_wind():
    ws = pd.Series([1.0, 2.0, 4.0, 5.0, 6.0])
    gust = pd.Series([5.0, 8.0, 6.0, 8.0, 12.0])            # ratios 5, 4, 1.5, 1.6, 2.0
    med, lo, hi, n = gust_factor(ws, gust)
    assert n == 3 and med == pytest.approx(1.6)


def test_rounded_table_values_always_pass_the_model_check():
    stats = pd.DataFrame({"p": [0.003257, 0.4868, 0.0], "mean_spell_days": [1.003267, 2.6249, 1.0]})
    p_txt, L_txt = B._p_and_spells(stats)
    p = np.array(eval(p_txt))
    L = np.array(eval(L_txt))
    assert np.all(L >= 1 / (1 - p) - 1e-12)
    assert L[1] == pytest.approx(2.625)                      # rounded up, never down


# ------------------------------------------------------------- weather rule
def _st(table):
    return next(iter(table["stations"]))


def test_table_defaults_come_from_the_parameter_block(cwa_table):
    st = _st(cwa_table)
    pars = cwa_table["parameters"]
    rain_p, _ = monthly_loss(cwa_table, st, "rain")
    np.testing.assert_allclose(rain_p, cwa_table["stations"][st]["rain_by_threshold"][pars["rain_mm"]["default"]]["p"])
    wind_p, _ = monthly_loss(cwa_table, st, "wind")
    v = cwa_table["stations"][st]["wind_exceedance"][pars["wind_stop_ms"]["default"]][pars["remobilisation_days"]["default"]]
    np.testing.assert_allclose(wind_p, v["p"])


@pytest.mark.parametrize("threshold, r, share", [(10, 0, 1.0), (10, 7, 0.4), (16, 1, 0.7), (8, 10, 1.0)])
def test_rule_is_share_times_the_measured_variant(cwa_table, threshold, r, share):
    st = _st(cwa_table)
    v = cwa_table["stations"][st]["wind_exceedance"][threshold][r]
    p, L = monthly_loss(cwa_table, st, "wind", WeatherRule(wind_stop_ms=threshold, stop_share=share,
                                                             remobilisation_days=r))
    np.testing.assert_allclose(p, share * np.asarray(v["p"]))
    np.testing.assert_allclose(L, v["mean_spell_days"])
    assert np.all(p < 1) and np.all(L >= 1 / (1 - p) - 1e-12)   # thinning spells keeps the chain valid


def test_rule_errors(cwa_table):
    st = _st(cwa_table)
    with pytest.raises(WeatherError, match="Stop share"):
        WeatherRule(stop_share=1.5)
    with pytest.raises(WeatherError, match="wind threshold"):
        monthly_loss(cwa_table, st, "wind", WeatherRule(wind_stop_ms=13))
    with pytest.raises(WeatherError, match="remobilisation"):
        monthly_loss(cwa_table, st, "wind", WeatherRule(remobilisation_days=11))
    with pytest.raises(WeatherError, match="rain threshold"):
        monthly_loss(cwa_table, st, "rain", WeatherRule(rain_mm=12))


def test_zero_share_means_no_wind_loss_and_rain_ignores_wind_settings(cwa_table):
    st = _st(cwa_table)
    p, L = monthly_loss(cwa_table, st, "wind", WeatherRule(stop_share=0.0))
    assert np.all(p == 0) and np.all(L == 1)
    a = monthly_loss(cwa_table, st, "rain")[0]
    b = monthly_loss(cwa_table, st, "rain", WeatherRule(wind_stop_ms=8, remobilisation_days=10))[0]
    np.testing.assert_array_equal(a, b)


def test_higher_thresholds_lose_fewer_days(cwa_table):
    st = _st(cwa_table)
    opts = threshold_options(cwa_table, st)
    rain = [monthly_loss(cwa_table, st, "rain", WeatherRule(rain_mm=t))[0].sum() for t in opts["rain_mm"]]
    wind = [monthly_loss(cwa_table, st, "wind", WeatherRule(wind_stop_ms=t, remobilisation_days=0))[0].sum()
            for t in opts["wind_ms"]]
    remob = [monthly_loss(cwa_table, st, "wind", WeatherRule(wind_stop_ms=10, remobilisation_days=r))[0].sum()
             for r in opts["remobilisation_days"]]
    assert rain == sorted(rain, reverse=True) and wind == sorted(wind, reverse=True)
    assert remob == sorted(remob)                                  # more remobilisation, more lost days


def _cwa_bank(model, table, rule=WeatherRule(), n=300, H=1800):
    st = _st(table)
    bank = S.RandomBank(model, n, 9, horizon=H)
    bank.prepare_weather(daily_probabilities(table, st, START, H, rule),
                         daily_persistence(table, st, START, H, rule))
    return bank


def _zero_bank(model, n=300, H=1800):
    bank = S.RandomBank(model, n, 9, horizon=H)
    bank.prepare_weather({"rain": np.zeros(H), "wind": np.zeros(H), "none": np.zeros(H)})
    return bank


# ----------------------------------------------------- weather on / off
@pytest.mark.parametrize("stoppage", [None, (0, 7), (150, 14), (400, 3)])
def test_weather_off_equals_a_run_without_weather_loss(model, cwa_table, stoppage):
    """Off = every day workable: identical to a bank whose weather never loses a day, stoppage included."""
    off = S.simulate(model, _cwa_bank(model, cwa_table), S.Scenario(ignore_weather=True, stoppage=stoppage))
    zero = S.simulate(model, _zero_bank(model), S.Scenario(stoppage=stoppage))
    np.testing.assert_array_equal(off.finish, zero.finish)
    np.testing.assert_array_equal(off.driver, zero.driver)


def test_calendar_finish_matches_the_weather_lookup_with_no_loss(model):
    bank, H = _zero_bank(model, n=100, H=400), 400
    rs = np.random.default_rng(1)
    start = rs.integers(0, 300, 100).astype(float)
    work = rs.integers(0, 90, 100).astype(float)
    for stop in (None, (50, 7), (0, 1), (200, 30)):
        a, _ = S._weather_finish(start, work, bank.weather_arrays("rain"), H, stop)
        np.testing.assert_array_equal(S._calendar_finish(start, work, stop), a)


def test_plan_without_weather_ignores_the_weather_table(model, cwa_table):
    st = _st(cwa_table)
    daily = daily_probabilities(cwa_table, st, START, 3650)
    zero = {k: np.zeros(3650) for k in daily}
    off = S.deterministic_plan(model, daily, S.Scenario(ignore_weather=True))
    assert off == S.deterministic_plan(model, zero)
    assert off[model.milestone][1] <= S.deterministic_plan(model, daily)[model.milestone][1]


def test_without_weather_a_late_start_never_costs_more_than_the_delay(model, cwa_table):
    """
    With fixed durations the forward pass is max-plus: delaying some inputs by k
    delays every output by at most k. So without weather, first fire moves by
    0..k days in every future; only weather can amplify a late start.
    """
    bank = _cwa_bank(model, cwa_table)
    base = S.simulate(model, bank, S.Scenario(ignore_weather=True)).milestone_finish()
    for k in (14, 28, 84):
        late = S.simulate(model, bank, S.Scenario(ignore_weather=True, site_start_shift=k)).milestone_finish()
        shift = late - base
        assert shift.min() >= 0 and shift.max() <= k


def test_a_larger_stopping_share_never_finishes_anything_earlier(model, cwa_table):
    """Same uniforms, p11 fixed, p01 rising with the share: the lost days are nested, the pass is monotone."""
    finishes = [S.simulate(model, _cwa_bank(model, cwa_table, WeatherRule(wind_stop_ms=10, stop_share=s,
                                                                          remobilisation_days=1))).finish
                for s in (0.0, 0.3, 0.7, 1.0)]
    for a, b in zip(finishes, finishes[1:]):
        assert np.all(b >= a)


def test_horizon_covers_the_strictest_rule(model, cwa_table):
    st = _st(cwa_table)
    strict = WeatherRule(rain_mm=5, wind_stop_ms=10, remobilisation_days=3)
    H = S.required_horizon(model, daily_probabilities(cwa_table, st, START, 3650, strict), extra_days=161)
    bank = _cwa_bank(model, cwa_table, strict, n=1000, H=H)
    assert S.simulate(model, bank, S.Scenario(site_start_shift=140)).overflow_count == 0


def test_weather_warnings_add_up_the_daily_chances(model, cwa_table):
    st = _st(cwa_table)
    bank = _cwa_bank(model, cwa_table)
    res = S.simulate(model, bank, S.Scenario(ignore_weather=True))
    H = 1800
    exceed = {"rain": {"stop": daily_exceedance(cwa_table, st, START, H, "rain", 10)},
              "wind": {"warning": daily_exceedance(cwa_table, st, START, H, "wind", 10),
                       "stop": daily_exceedance(cwa_table, st, START, H, "wind", 16)}}
    w = A.weather_warnings(res, START, exceed)
    assert set(w["kind"]) == {"rain", "wind"}
    assert w.loc[w["kind"] == "rain", "days_warning"].isna().all()
    row = w[w["id"] == "HRSG_ERECT"].iloc[0]
    i = model.index["HRSG_ERECT"]
    s50, f50 = int(round(np.quantile(res.start[i], 0.5))), int(round(np.quantile(res.finish[i], 0.5)))
    assert row["days_warning"] == pytest.approx(exceed["wind"]["warning"][s50:f50].sum())
    assert row["days_stop"] <= row["days_warning"]


# ------------------------------------------------------------ shipped table
def test_shipped_table_is_real_data_with_citation_and_disclaimer(cwa_table):
    assert cwa_table["is_illustrative"] is False
    cite = cwa_table["citation"]
    for phrase in ("交通部中央氣象署 CODiS", "467050", "政府資料開放授權條款第 1 版", "經作者加工計算"):
        assert phrase in cite
    assert "not a forecast" in cwa_table["disclaimer"]
    text = " ".join(f"{r['item']} {r['value']}" for r in cwa_table["provenance"]).lower()
    assert "verified by cwa" not in text and "endorse" not in text
    st = _st(cwa_table)
    assert has_spells(cwa_table, st)
    opts = threshold_options(cwa_table, st)
    assert opts["remobilisation_days"] == list(range(11))
    assert 10 in opts["rain_mm"] and {10, 16} <= set(opts["wind_ms"])


def test_every_parameter_states_source_and_verification_status(cwa_table):
    pars = cwa_table["parameters"]
    assert {"rain_mm", "wind_warning_ms", "wind_stop_ms", "stop_share", "remobilisation_days", "gust_factor"} <= set(pars)
    for key, spec in pars.items():
        assert spec["source"].strip() and spec["status"].strip(), key
    assert "pending" in pars["wind_warning_ms"]["status"].lower()
    assert "pending" in pars["wind_stop_ms"]["status"].lower()
    assert (pars["wind_warning_ms"]["default"], pars["wind_stop_ms"]["default"]) == (10, 16)
    assert "149 hours" in pars["gust_factor"]["source"]


def test_chain_reproduces_the_measured_january_wind(model, cwa_table):
    """Bank built from the table: simulated share of windy January days matches the record."""
    st = _st(cwa_table)
    rule = WeatherRule(wind_stop_ms=10, remobilisation_days=0)
    bank = _cwa_bank(model, cwa_table, rule, n=3000, H=400)
    lost = bank.lost_days("wind", 365)
    jan = pd.date_range(START, periods=365, freq="D").month == 1
    v = cwa_table["stations"][st]["wind_exceedance"][10][0]
    assert lost[:, jan].mean() == pytest.approx(v["p"][0], abs=0.02)
    p11, _ = transition_probabilities(np.array(v["p"][:1]), np.array(v["mean_spell_days"][:1]))
    x = lost[:, jan].astype(float)
    cond = (x[:, 1:] * x[:, :-1]).sum() / x[:, :-1].sum()
    assert cond == pytest.approx(float(p11[0]), abs=0.03)
