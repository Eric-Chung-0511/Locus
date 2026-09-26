"""
Weather layer: the independent model, the Markov-chain spells, and the lookup
that turns workable days into finish days. Each piece is checked against a
brute-force reference or against the statistics it is meant to reproduce.
"""

from __future__ import annotations

import numpy as np
import pytest
from conftest import START, row_cum

from locus import analysis as A
from locus import simulate as S
from locus.weather import (WeatherError, daily_persistence, daily_probabilities,
                           independent_spell_days, load_weather_table,
                           transition_probabilities)


def _uniforms(bank, kind):
    """Redraw the bank's weather uniforms exactly as prepare_weather does (day-major)."""
    rng = np.random.default_rng(bank._weather_seq[kind])
    return rng.random((bank.horizon, bank.n_iter), dtype=np.float32).T


def _share_with_run(lost, k):
    """Share of iterations with at least one run of k or more consecutive lost days."""
    return float(np.mean(A.longest_runs(lost) >= k))


def test_longest_runs_matches_python_reference():
    rs = np.random.default_rng(4)
    lost = rs.random((50, 120)) < 0.4
    expected = []
    for row in lost:
        best = cur = 0
        for x in row:
            cur = cur + 1 if x else 0
            best = max(best, cur)
        expected.append(best)
    np.testing.assert_array_equal(A.longest_runs(lost), expected)


def _bank(model, n, H, p, p11=None, seed=1):
    """Bank with constant, hand-set daily probabilities (rain and wind the same)."""
    bank = S.RandomBank(model, n, seed, horizon=H)
    daily = {"rain": np.full(H, p), "wind": np.full(H, p), "none": np.zeros(H)}
    persist = None if p11 is None else {"rain": np.full(H, p11), "wind": np.full(H, p11)}
    bank.prepare_weather(daily, persist)
    return bank


# ------------------------------------------------------------- the transitions
def test_transition_probabilities_keep_the_long_run_share():
    p = np.array([0.05, 0.25, 0.4, 0.6])
    L = np.array([1.2, 3.0, 2.0, 5.0])
    p11, p01 = transition_probabilities(p, L)
    stationary = p01 / (p01 + 1 - p11)
    np.testing.assert_allclose(stationary, p)
    np.testing.assert_allclose(1 / (1 - p11), L)           # mean spell length


def test_independent_spell_length_gives_independent_days():
    p = np.array([0.1, 0.3, 0.5])
    p11, p01 = transition_probabilities(p, [independent_spell_days(x) for x in p])
    np.testing.assert_allclose(p11, p)
    np.testing.assert_allclose(p01, p)


def test_table_rejects_spells_shorter_than_independent(tmp_path):
    bad = tmp_path / "weather_bad.yaml"
    bad.write_text(
        "stations:\n  S:\n"
        "    rain: [0.5,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1]\n"
        "    wind: [0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1]\n"
        "    mean_spell_days:\n"
        "      rain: [1.5,2,2,2,2,2,2,2,2,2,2,2]\n"       # 1.5 < 1/(1-0.5) = 2
        "      wind: [2,2,2,2,2,2,2,2,2,2,2,2]\n", encoding="utf-8")
    with pytest.raises(WeatherError, match="shorter than 2.00"):
        load_weather_table(bad)


# ------------------------------------------------------------- the bank itself
def test_independent_bank_is_exactly_bernoulli(model, table, station):
    H = 400
    bank = S.RandomBank(model, 80, 9, horizon=H)
    daily = daily_probabilities(table, station, START, H)
    bank.prepare_weather(daily)
    for kind in ("rain", "wind"):
        lost = _uniforms(bank, kind) < daily[kind].astype(np.float32)[None, :]
        np.testing.assert_array_equal(row_cum(bank, kind), np.cumsum(~lost, axis=1))


def test_chain_bank_matches_day_by_day_reference(model, table, station):
    """Brute force: walk every iteration day by day with the same uniforms and thresholds."""
    H, N = 400, 50
    bank = S.RandomBank(model, N, 9, horizon=H)
    daily = daily_probabilities(table, station, START, H)
    persist = daily_persistence(table, station, START, H)
    bank.prepare_weather(daily, persist)
    for kind in ("rain", "wind"):
        u = _uniforms(bank, kind)
        p = daily[kind].astype(np.float32)
        p11 = persist[kind].astype(np.float32)
        p01 = (daily[kind] * (1 - persist[kind]) / (1 - daily[kind])).astype(np.float32)
        expected = np.zeros((N, H), dtype=np.int64)
        for r in range(N):
            count, prev = 0, None
            for d in range(H):
                thr = p[0] if prev is None else (p11[d] if prev else p01[d])
                prev = bool(u[r, d] < thr)
                count += not prev
                expected[r, d] = count
        np.testing.assert_array_equal(row_cum(bank, kind), expected)


def test_chain_reproduces_share_spell_length_and_autocorrelation(model):
    p, L = 0.25, 3.0
    p11, p01 = transition_probabilities(np.array([p]), np.array([L]))
    bank = _bank(model, 2000, 2000, p, float(p11[0]))
    lost = bank.lost_days("rain")
    assert lost.mean() == pytest.approx(p, abs=0.005)
    # Mean spell length: lost days / number of runs that start inside the window.
    starts = lost[:, 1:] & ~lost[:, :-1]
    assert lost[:, 1:].sum() / starts.sum() == pytest.approx(L, rel=0.02)
    # Lag-1 autocorrelation of the lost indicator equals p11 - p01.
    x = lost.astype(float)
    rho = np.corrcoef(x[:, 1:].ravel(), x[:, :-1].ravel())[0, 1]
    assert rho == pytest.approx(float(p11[0] - p01[0]), abs=0.01)


def test_spells_keep_the_mean_but_widen_the_spread(make_bank):
    """Same monthly table: expected lost days unchanged, spread wider, lost weeks far more common."""
    ind, chain = make_bank(2000, spells=False), make_bank(2000, spells=True)
    days = 730
    for kind in ("rain", "wind"):
        a, b = ind.lost_days(kind, days), chain.lost_days(kind, days)
        assert b.mean() == pytest.approx(a.mean(), rel=0.03)
        # Lost days per 30-day window: spread across iterations, window by window
        # (pooling windows would mix in the seasonal differences between months).
        wa = a[:, :720].reshape(a.shape[0], 24, 30).sum(axis=2)
        wb = b[:, :720].reshape(b.shape[0], 24, 30).sum(axis=2)
        np.testing.assert_allclose(wb.mean(axis=0), wa.mean(axis=0), atol=0.6)
        ratio = wb.std(axis=0) / wa.std(axis=0)
        assert ratio.min() > 1.1 and ratio.mean() > 1.3
        # A fully lost week: almost never with independent days, common with spells.
        share_a, share_b = _share_with_run(a, 7), _share_with_run(b, 7)
        assert share_b > max(5 * share_a, share_a + 0.5)


def test_chain_with_independent_spells_matches_independent_statistics(model):
    p = 0.3
    bank = _bank(model, 2000, 1500, p, p11=p)            # p11 = p  ->  p01 = p
    x = bank.lost_days("wind").astype(float)
    assert x.mean() == pytest.approx(p, abs=0.005)
    rho = np.corrcoef(x[:, 1:].ravel(), x[:, :-1].ravel())[0, 1]
    assert abs(rho) < 0.005


# ------------------------------------------------------- horizon and draw order
@pytest.mark.parametrize("spells", [False, True])
def test_horizon_changes_memory_not_results(model, make_bank, spells):
    short, long_ = make_bank(300, horizon=1230, spells=spells), make_bank(300, horizon=3650, spells=spells)
    relax_all = frozenset(l.idx for l in model.relaxable_links())
    for sc in (S.Scenario(), S.Scenario(site_start_shift=140), S.Scenario(relaxed=relax_all)):
        a, b = S.simulate(model, short, sc), S.simulate(model, long_, sc)
        np.testing.assert_array_equal(a.finish, b.finish)
        np.testing.assert_array_equal(a.driver, b.driver)
        assert a.overflow_count == 0


def test_block_size_does_not_change_draws(model, table, station, monkeypatch):
    H = 400
    daily = daily_probabilities(table, station, START, H)
    persist = daily_persistence(table, station, START, H)
    arrays = []
    for block in (64, 7):
        monkeypatch.setattr(S.RandomBank, "_DAY_BLOCK", block)
        bank = S.RandomBank(model, 100, 3, horizon=H)
        bank.prepare_weather(daily, persist)
        arrays.append([bank.weather_arrays(k).copy() for k in ("rain", "wind")])
    for x, y in zip(*arrays):
        np.testing.assert_array_equal(x, y)


# ----------------------------------------------------------- finish-day lookup
def _reference_finish(ok_row, s, w, H):
    """1 + first day t >= s at which w workable days have accumulated, or the fallback."""
    if w == 0:
        return s, False
    if not 0 <= s < H:
        return s + np.ceil(w / 0.75), True
    count = 0
    for d in range(s, H):
        count += ok_row[d]
        if count >= w:
            return d + 1, False
    return s + np.ceil(w / 0.75), True


@pytest.mark.parametrize("spells", [False, True])
def test_weather_finish_matches_brute_force(model, table, station, spells):
    H, N = 400, 80
    bank = S.RandomBank(model, N, 11, horizon=H)
    bank.prepare_weather(daily_probabilities(table, station, START, H),
                         daily_persistence(table, station, START, H) if spells else None)
    ok = ~bank.lost_days("rain")
    rs = np.random.default_rng(0)
    start = rs.integers(-5, H + 5, N).astype(float)
    work = rs.integers(0, 200, N).astype(float)
    finish, overflow = S._weather_finish(start, work, bank.weather_arrays("rain"), H)
    expected = [_reference_finish(ok[r], int(start[r]), int(work[r]), H) for r in range(N)]
    np.testing.assert_array_equal(finish, [e[0] for e in expected])
    assert overflow == sum(e[1] for e in expected)
