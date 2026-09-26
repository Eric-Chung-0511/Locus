"""
Monthly weather statistics from daily station records (used to build config/weather_*.yaml).

A day is "lost" (1), "workable" (0) or unknown (NaN, missing data). For each
calendar month the model needs two numbers (see locus/weather.py):

    p  share of lost days
         p = lost days / days with data

    L  mean spell length: average run of consecutive lost days
         L = lost days whose previous day is known / runs that start that month
       A run starts on a lost day whose previous day was workable. Under the
       two-state Markov chain the model uses, P(previous day workable | lost
       today) = 1 - p11 = 1 / L, so this ratio estimates exactly the parameter
       the chain needs. It is a count over pairs of consecutive days
       (yesterday, today) with both known; pairs that involve a missing day are
       skipped, so a gap can neither start a run nor join two runs.

Remobilisation: after work stops for wind, restarting (re-rigging, checks) takes
r more days. `extend_stoppage` marks those r days as lost too, on the daily
record, so overlapping spells merge the way they would on site, and p and L
are then measured on the extended record.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def monthly_spell_stats(lost: pd.Series) -> pd.DataFrame:
    """
    lost: daily series (DatetimeIndex, one row per calendar day) of 1 / 0 / NaN.
    Returns one row per calendar month (1..12): p, mean_spell_days, n_days,
    lost_days, runs, and L_independent = 1 / (1 - p).

    Months with no runs get L = 1 / (1 - p) (the independent-days value, 1 when
    p = 0). L below that value is raised to it and flagged in `raised`,
    because the model rejects spells shorter than independence.
    """
    if not isinstance(lost.index, pd.DatetimeIndex):
        raise TypeError("lost must have a DatetimeIndex")
    x = lost.astype(float).asfreq("D")                 # expose missing dates as NaN
    prev = x.shift(1)
    known_pair = x.notna() & prev.notna()
    month = x.index.month

    n_days = x.notna().groupby(month).sum()
    lost_days = (x == 1).groupby(month).sum()
    p = lost_days / n_days
    lost_known_prev = ((x == 1) & known_pair).groupby(month).sum()
    runs = ((x == 1) & (prev == 0)).groupby(month).sum()
    L_ind = 1.0 / (1.0 - p)
    L = (lost_known_prev / runs.replace(0, np.nan)).fillna(L_ind)
    raised = L < L_ind - 1e-12
    L = L.where(~raised, L_ind)
    out = pd.DataFrame({"p": p, "mean_spell_days": L, "L_independent": L_ind, "n_days": n_days,
                        "lost_days": lost_days, "runs": runs, "raised": raised})
    return out.reindex(range(1, 13))


def extend_stoppage(lost: pd.Series, days_after: int) -> pd.Series:
    """
    Add `days_after` lost days after every lost day (remobilisation), on the daily record.
        extended(d) = 1   if any of lost(d - k), k = 0..days_after, is 1
                    = 0   if all of them are known and 0
                    = NaN otherwise (a missing day could have been a stop)
    """
    if days_after < 0:
        raise ValueError("days_after must be >= 0")
    x = lost.astype(float).asfreq("D")
    if days_after == 0:
        return x
    window = days_after + 1
    any_lost = (x == 1).astype(float).rolling(window, min_periods=1).max() == 1
    any_missing = x.isna().astype(float).rolling(window, min_periods=1).max() == 1
    out = pd.Series(0.0, index=x.index)
    out[any_missing] = np.nan
    out[any_lost] = 1.0
    return out


def gust_factor(ws: pd.Series, gust: pd.Series, min_ws: float = 3.0) -> tuple[float, float, float, int]:
    """
    Median ratio gust / mean wind over hours with mean wind >= min_ws, with its
    interquartile range and sample size. Light-wind hours are left out: a small
    denominator inflates the ratio, and they are far from any work threshold.
    """
    ok = ws.notna() & gust.notna() & (ws >= min_ws) & (gust > 0)
    r = gust[ok] / ws[ok]
    if r.empty:
        raise ValueError("No hours with mean wind at or above the minimum")
    return float(r.median()), float(r.quantile(0.25)), float(r.quantile(0.75)), int(ok.sum())
