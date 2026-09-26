"""
Decision outputs built on top of simulation results.

Every function answers one question a planner or delivery PM gets asked:
    milestone_summary   -> "How likely is the date?"
    criticality_table   -> "What actually drives it?"
    driver_chains       -> the same, with items that are always critical together merged
    latest_dates        -> "How late can this delivery / submission be?"
    recovery_options    -> "Which links can we break to win time, and at what cost?"
    seasonal_experiment -> "What does a late start really cost?"
    stoppage_sweep      -> "What if bad weather stops the site for a week?"
    weather_spells      -> "How often does the site lose a whole week to weather?"
    risk_contributions  -> "Which common risk costs the most, and what is removing it worth?"
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from . import labels as L
from .model import HARD_LINK_TYPES, Model
from .simulate import RandomBank, Scenario, SimResult, simulate
from .weather import day_to_date

# A proposal counts as having a measurable effect when it moves P50 by at least
# half a day or the chance of meeting the target by at least 0.1 percentage point.
MIN_GAIN_DAYS = 0.5
MIN_DELTA_P = 0.001


def _q(values: np.ndarray, q: float) -> float:
    finite = values[np.isfinite(values)]
    return float(np.quantile(finite, q)) if finite.size else float("nan")


# ------------------------------------------------------------------ milestone
def milestone_summary(res: SimResult, start: date, target_day: float, plan_day: float) -> dict:
    ms = res.milestone_finish()
    return {
        "plan_day": plan_day,
        "plan_date": day_to_date(start, plan_day),
        "target_day": target_day,
        "target_date": day_to_date(start, target_day),
        "p_on_target": float(np.mean(ms <= target_day)),
        "p_on_plan": float(np.mean(ms <= plan_day)),
        "p50_day": _q(ms, 0.5), "p80_day": _q(ms, 0.8), "p90_day": _q(ms, 0.9),
        "p50_date": day_to_date(start, _q(ms, 0.5)),
        "p80_date": day_to_date(start, _q(ms, 0.8)),
        "p90_date": day_to_date(start, _q(ms, 0.9)),
    }


# ---------------------------------------------------------------- criticality
def criticality_table(res: SimResult, start: date) -> pd.DataFrame:
    """Criticality Index = share of iterations in which the node is on the driving path."""
    m = res.model
    node_on, _ = res.driving_path()
    rows = []
    for nid in m.order:
        i = m.index[nid]
        node = m.nodes[nid]
        rows.append({
            "id": nid, "name": node.name, "short_name": node.short_name,
            "group": node.group, "condition": node.condition,
            "criticality": float(node_on[i].mean()),
            "p50_finish": day_to_date(start, _q(res.finish[i], 0.5)),
            "p80_finish": day_to_date(start, _q(res.finish[i], 0.8)),
            "source_grade": node.source_grade,
        })
    return pd.DataFrame(rows).sort_values("criticality", ascending=False, ignore_index=True)


def driver_chains(res: SimResult, top: int | None = 10) -> pd.DataFrame:
    """
    Criticality Index with series chains merged.

    Items in a pure series chain (piling -> foundations -> steel) are on the
    driving path in exactly the same iterations, so separate bars would repeat
    one number. Nodes whose driving-path rows node_on[i, :] are identical across
    all iterations are merged into one row, members in topological order.
    The milestone itself and items that never drive it are left out.

    Returns one row per chain: key (first member id), members (ids), label
    (chart label), criticality, condition ('mixed' if members differ), n_items.
    """
    m = res.model
    node_on, _ = res.driving_path()
    chains: dict[bytes, list[str]] = {}
    for nid in m.order:                       # topological order within each chain
        if nid == m.milestone:
            continue
        row = node_on[m.index[nid]]
        if not row.any():
            continue
        chains.setdefault(np.packbits(row).tobytes(), []).append(nid)

    rows = []
    for members in chains.values():
        nodes = [m.nodes[nid] for nid in members]
        conditions = {n.condition for n in nodes}
        rows.append({
            "key": members[0], "members": members, "n_items": len(members),
            "label": L.chain_label(nodes[0].short_name, nodes[-1].short_name, len(members)),
            "names": "; ".join(n.name for n in nodes),
            "group": nodes[0].group if len({n.group for n in nodes}) == 1 else "Several areas",
            "condition": conditions.pop() if len(conditions) == 1 else "mixed",
            "criticality": float(node_on[m.index[members[0]]].mean()),
            "order": m.index[members[0]],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["criticality", "order"], ascending=[False, True], ignore_index=True)
    return (df.head(top) if top else df).drop(columns="order")


def driving_link_mix(res: SimResult) -> pd.DataFrame:
    """Average share of driving-path links by type: how 'breakable' is the critical path?"""
    m = res.model
    _, link_on = res.driving_path()
    counts: dict[str, float] = {}
    per_iter_total = link_on.sum(axis=0).astype(float)
    per_iter_total[per_iter_total == 0] = np.nan
    for link in m.links:
        counts[link.type] = counts.get(link.type, 0.0) + link_on[link.idx].astype(float)
    rows = [{"link_type": t, "share": float(np.nanmean(c / per_iter_total)),
             "breakable": t not in HARD_LINK_TYPES} for t, c in counts.items()]
    return pd.DataFrame(rows).sort_values("share", ascending=False, ignore_index=True)


# ----------------------------------------------------------------- latest dates
def latest_dates(res: SimResult, start: date, target_day: float, confidence: float = 0.8) -> pd.DataFrame:
    """
    For external inputs and review nodes: the latest date that still protects the
    target in `confidence` of simulated futures (holding everything else as simulated).

    Latest acceptable finish  = (1 - confidence) quantile of LF.
    For reviews with a planned submission day:
        latest submission     = latest acceptable finish - P80 review duration
    Margin = latest - reference (planned date, or simulated P50 for completions);
    negative means the current plan or expectation is already too late for the target.
    """
    m = res.model
    LF = res.latest_finish(target_day)
    rows = []
    for nid in m.order:
        node = m.nodes[nid]
        if node.kind != "external" and node.condition != "regulatory":
            continue
        i = m.index[nid]
        lf = _q(LF[i], 1.0 - confidence)
        if not np.isfinite(lf):
            continue
        dur_p80 = _q(res.finish[i] - res.start[i], 0.8)
        if node.kind == "external":
            what, basis, planned, latest = "Arrival", "Planned arrival", node.planned_day, lf
        elif node.earliest_day > 0:
            what, basis, planned, latest = "Submission", "Planned submission", node.earliest_day, lf - dur_p80
        else:
            what, basis, planned, latest = "Completion", "Simulated P50", _q(res.finish[i], 0.5), lf
        rows.append({
            "id": nid, "name": node.name, "short_name": node.short_name,
            "kind": "External input" if node.kind == "external" else "Review",
            "rule": node.rule_id or "", "measure": what,
            "reference_basis": basis, "reference": day_to_date(start, planned),
            "latest_ok": day_to_date(start, latest),
            "margin_days": round(latest - planned),
            "p80_duration_days": round(dur_p80) if node.kind != "external" else None,
            "source_grade": node.source_grade,
        })
    return pd.DataFrame(rows).sort_values("margin_days", ignore_index=True)


# ------------------------------------------------------------ recovery options
def recovery_options(model: Model, bank: RandomBank, base: SimResult, target_day: float) -> pd.DataFrame:
    """
    Break one soft link at a time (same random numbers) and measure the gain.
    Also reports how often the link is on the driving path in the baseline:
    breaking a link that rarely drives the milestone buys little, however
    attractive it looks on site.

    Rows are ranked by P50 gain, then by change in chance of meeting the target.
    `measurable` flags proposals that move P50 by at least MIN_GAIN_DAYS or the
    chance by at least MIN_DELTA_P; the last row combines every proposal.
    """
    base_ms = base.milestone_finish()
    p_base, p50_base = float(np.mean(base_ms <= target_day)), _q(base_ms, 0.5)
    _, link_on = base.driving_path()

    rows = []
    soft = model.relaxable_links()
    for link in soft:
        res = simulate(model, bank, replace(base.scenario, relaxed=frozenset({link.idx}), label=link.label))
        ms = res.milestone_finish()
        rows.append({
            "proposal": link.relax.get("proposal", ""),
            "link": f"{model.nodes[link.src].name} -> {model.nodes[link.dst].name}",
            "link_id": link.idx, "type": link.type,
            "change": _describe_relax(model, link),
            "on_driving_path": float(link_on[link.idx].mean()),
            "gain_p50_days": round(p50_base - _q(ms, 0.5), 1),
            "delta_p_on_target": float(np.mean(ms <= target_day)) - p_base,
            "cost_or_risk": link.relax.get("cost", ""),
        })
    if soft:
        res = simulate(model, bank, replace(base.scenario, relaxed=frozenset(l.idx for l in soft),
                                            label="All soft links"))
        ms = res.milestone_finish()
        rows.append({
            "proposal": "All proposals together",
            "link": "All soft links together", "link_id": -1, "type": "combined",
            "change": "Every relaxation applied at once",
            "on_driving_path": float("nan"),
            "gain_p50_days": round(p50_base - _q(ms, 0.5), 1),
            "delta_p_on_target": float(np.mean(ms <= target_day)) - p_base,
            "cost_or_risk": "Sum of the individual costs and risks",
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["measurable"] = ((df["gain_p50_days"].abs() >= MIN_GAIN_DAYS)
                        | (df["delta_p_on_target"].abs() >= MIN_DELTA_P))
    df["combined"] = df["link_id"] < 0
    return df.sort_values(["combined", "gain_p50_days", "delta_p_on_target"],
                          ascending=[True, False, False], ignore_index=True)


def _describe_relax(model: Model, link) -> str:
    r = link.relax
    pred = r.get("pred", link.src)
    lag = r.get("lag", link.lag)
    lag_txt = f"{'+' if lag >= 0 else ''}{int(lag)}d"
    if pred != link.src:
        return f"Use another means: start after {model.nodes[pred].name} ({r.get('rel', 'FS')} {lag_txt})"
    return f"{link.rel} {int(link.lag)}d -> {r.get('rel', link.rel)} {lag_txt}"


# --------------------------------------------------------- seasonal experiment
def late_start_headline(both: dict, weeks: int = 4) -> tuple[int, float, float] | None:
    """
    The headline finding: (k, P50 shift without weather, P50 shift with weather)
    for a k-week late start, k = `weeks` if it was tested, else the first delay
    tested. `both` = {False: {"season": ...}, True: {"season": ...}}.
    """
    off, on = both[False]["season"], both[True]["season"]
    tested = off.loc[off["start_delay_weeks"] > 0, "start_delay_weeks"]
    if tested.empty:
        return None
    k = weeks if weeks in set(tested) else int(tested.iloc[0])
    pick = lambda df: float(df.loc[df["start_delay_weeks"] == k, "p50_shift_days"].iloc[0])
    return k, pick(off), pick(on)


def seasonal_experiment(model: Model, bank: RandomBank, shifts_weeks: list[int],
                        template: Scenario = Scenario()) -> pd.DataFrame:
    """
    Delay every site-start activity by k weeks while deliveries and the calendar
    stay put, and measure the milestone shift. If the shift is larger than k,
    the delay pushed weather-sensitive work into a worse season (amplification).
    `template` carries the other scenario settings, e.g. ignore_weather.
    """
    rows = []
    ref50 = ref80 = None
    for k in shifts_weeks:
        res = simulate(model, bank, replace(template, site_start_shift=7 * int(k), label=f"+{k}w"))
        ms = res.milestone_finish()
        p50, p80 = _q(ms, 0.5), _q(ms, 0.8)
        if ref50 is None:
            ref50, ref80 = p50, p80
        rows.append({"start_delay_weeks": int(k), "start_delay_days": 7 * int(k),
                     "p50_shift_days": p50 - ref50, "p80_shift_days": p80 - ref80})
    df = pd.DataFrame(rows)
    df["amplification_p50"] = np.where(df["start_delay_days"] > 0,
                                       df["p50_shift_days"] / df["start_delay_days"].replace(0, np.nan), np.nan)
    return df


# ------------------------------------------------------------ weather stress
def weather_work_span(res: SimResult, q: float = 0.9) -> tuple[float, float]:
    """(earliest P10 start, latest `q` finish) of weather-sensitive work: when the site is exposed."""
    m = res.model
    rows = [m.index[n] for n, node in m.nodes.items() if node.weather != "none"]
    if not rows:
        return 0.0, 0.0
    first = min(_q(res.start[i], 0.1) for i in rows)
    last = max(_q(res.finish[i], q) for i in rows)
    return first, last


def stoppage_sweep(model: Model, bank: RandomBank, base: SimResult, days: int = 7, step: int = 14,
                   target_day: float | None = None, start: date | None = None) -> pd.DataFrame:
    """
    Vulnerability curve: force `days` lost days on all weather-sensitive work,
    starting on each day 0, step, 2*step, ... up to the P90 finish of the last
    weather-sensitive activity, and measure how far first fire moves.
    Same random numbers as the baseline, so each shift is the stoppage alone.

    Per iteration the shift is >= 0 (losing days never helps). It is 0 when no
    weather-sensitive work was running or it had float. On the driving path it
    is about `days`, but not exactly: days of the window that the weather had
    already taken cost nothing extra, and the workable days lost are made up
    later, in whatever weather comes then. `share_more_than_window` is the share
    of futures in which the stoppage costs first fire more than its own length.
    """
    days, step = int(days), int(step)
    if days < 1 or step < 1:
        raise ValueError("days and step must be at least 1")
    base_ms = base.milestone_finish()
    _, last = weather_work_span(base)
    last_first_day = min(int(np.ceil(last)), bank.horizon - days)
    rows = []
    for a in range(0, max(last_first_day, 0) + 1, step):
        res = simulate(model, bank, replace(base.scenario, stoppage=(a, days), label=f"Stoppage day {a}"))
        ms = res.milestone_finish()
        shift = ms - base_ms
        row = {"first_day": a, "days": days,
               "p50_shift_days": _q(ms, 0.5) - _q(base_ms, 0.5),
               "p80_shift_days": _q(ms, 0.8) - _q(base_ms, 0.8),
               "mean_shift_days": float(shift.mean()),
               "share_delayed": float(np.mean(shift > 0)),
               "share_more_than_window": float(np.mean(shift > days))}
        if start is not None:
            row["first_date"] = pd.Timestamp(day_to_date(start, a))
        if target_day is not None:
            row["delta_p_on_target"] = float(np.mean(ms <= target_day) - np.mean(base_ms <= target_day))
        rows.append(row)
    return pd.DataFrame(rows)


def longest_runs(lost: np.ndarray) -> np.ndarray:
    """Longest run of consecutive True values in each row of a boolean (n_iter, days) matrix."""
    run = np.zeros(lost.shape[0], dtype=np.int64)
    best = np.zeros_like(run)
    for d in range(lost.shape[1]):
        run = np.where(lost[:, d], run + 1, 0)
        np.maximum(best, run, out=best)
    return best


def weather_spells(bank: RandomBank, first_day: float, last_day: float, run_days: int = 7) -> pd.DataFrame:
    """
    Per weather kind, over the days weather-sensitive work is exposed
    [first_day, last_day): the share of days lost, and the share of futures with
    at least one run of `run_days` or more consecutive lost days.
    """
    lo, hi = max(int(first_day), 0), max(int(np.ceil(last_day)), 1)
    rows = []
    for kind in ("rain", "wind"):
        lost = bank.lost_days(kind, hi)[:, lo:]
        runs = longest_runs(lost)
        rows.append({"kind": kind, "lost_share": float(lost.mean()),
                     "share_with_run": float(np.mean(runs >= run_days)),
                     "median_longest_run": float(np.median(runs))})
    return pd.DataFrame(rows)


# ------------------------------------------------------------- common risks
def risk_contributions(model: Model, bank: RandomBank, base: SimResult, target_day: float) -> pd.DataFrame:
    """
    What each common risk costs, on the same random numbers as the baseline.

    If removed : switch this risk off, keep the others. The gain is what
                 eliminating or insuring against it is worth with the rest
                 still in play (the decision view).
    Alone      : only this risk on, against no common risks at all.
    Risks interact (a delay only costs when its path drives first fire, and
    factors multiply), so neither column adds up to the total; the last row,
    every common risk removed, gives the total.
    """
    if not model.risks:
        return pd.DataFrame()
    all_ids = frozenset(r.id for r in model.risks)
    base_ms = base.milestone_finish()
    b50, b80 = _q(base_ms, 0.5), _q(base_ms, 0.8)
    p_base = float(np.mean(base_ms <= target_day))
    none_ms = simulate(model, bank, replace(base.scenario, disabled_risks=all_ids,
                                            label="No common risks")).milestone_finish()
    n80 = _q(none_ms, 0.8)

    rows = []
    for risk in model.risks:
        without = simulate(model, bank, replace(base.scenario, disabled_risks=frozenset({risk.id}),
                                                label=f"Without {risk.id}")).milestone_finish()
        alone = simulate(model, bank, replace(base.scenario, disabled_risks=all_ids - {risk.id},
                                              label=f"Only {risk.id}")).milestone_finish()
        u_occ, _ = bank.u_risk[risk.id]
        rows.append({
            "id": risk.id, "name": risk.name, "short_name": risk.short_name,
            "probability": risk.probability, "occurs_share": float(np.mean(u_occ < risk.probability)),
            "effect": risk.effect, "impact": risk.impact, "n_items": len(risk.targets),
            "targets": list(risk.targets),
            "p50_gain_if_removed": b50 - _q(without, 0.5),
            "p80_gain_if_removed": b80 - _q(without, 0.8),
            "delta_p_if_removed": float(np.mean(without <= target_day)) - p_base,
            "p80_added_alone": _q(alone, 0.8) - n80,
            "source_grade": risk.source_grade, "source_note": risk.source_note,
            "combined": False,
        })
    rows.append({
        "id": "", "name": "All common risks", "short_name": "All common risks",
        "probability": np.nan, "occurs_share": np.nan, "effect": "", "impact": None,
        "n_items": len({t for r in model.risks for t in r.targets}), "targets": [],
        "p50_gain_if_removed": b50 - _q(none_ms, 0.5),
        "p80_gain_if_removed": b80 - n80,
        "delta_p_if_removed": float(np.mean(none_ms <= target_day)) - p_base,
        "p80_added_alone": b80 - n80,
        "source_grade": "", "source_note": "", "combined": True,
    })
    df = pd.DataFrame(rows)
    return df.sort_values(["combined", "p80_gain_if_removed"], ascending=[True, False], ignore_index=True)


# -------------------------------------------------------------- wind warnings
MONSOON_MONTHS = (10, 11, 12, 1, 2, 3)     # north-east monsoon season on Taiwan's west coast


def weather_warnings(res: SimResult, start: date, exceed: dict[str, dict[str, np.ndarray]]) -> pd.DataFrame:
    """
    For every weather-sensitive activity: its P50 window (median start to median
    finish in this run) and the expected number of days in that window that
    reach each threshold:
        expected days = sum over window days d of P(day d reaches the threshold)
    with P from the station record by calendar month. These are warnings: they
    change the schedule only when weather is applied.

    exceed: {"rain": {"stop": daily p}, "wind": {"warning": daily p, "stop": daily p}},
    each array indexed from day 0 = start.
    """
    m = res.model
    rows = []
    for nid in m.order:
        node = m.nodes[nid]
        if node.weather not in exceed:
            continue
        i = m.index[nid]
        s50, f50 = int(round(_q(res.start[i], 0.5))), int(round(_q(res.finish[i], 0.5)))
        days = np.arange(max(s50, 0), max(f50, s50 + 1))
        dates = day_to_date(start, days)
        row = {"kind": node.weather, "id": nid, "name": node.name, "short_name": node.short_name,
               "source_note": node.source_note,
               "p50_start": day_to_date(start, s50), "p50_finish": day_to_date(start, f50),
               "window_days": len(days),
               "monsoon_days": int(np.isin(dates.month, MONSOON_MONTHS).sum())}
        for level in ("warning", "stop"):
            daily = exceed[node.weather].get(level)
            if daily is None:
                row[f"days_{level}"] = np.nan
                continue
            inside = days[days < len(daily)]
            row[f"days_{level}"] = float(daily[inside].sum())
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["_rank"] = df["days_warning"].fillna(df["days_stop"])
    df = df.sort_values(["kind", "_rank"], ascending=[False, False], ignore_index=True)
    return df.drop(columns="_rank")
