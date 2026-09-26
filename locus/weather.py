"""
Weather layer (L3): turns a monthly stoppage table into day-by-day probabilities
on the project calendar.

Model
    Each calendar day d has a probability p(d) that weather-sensitive work is lost,
    taken from the month that day d falls in.

    Expected calendar days to finish W working days inside one month:
        E[calendar days] = W / (1 - p)
    so a month with p = 0.35 stretches work by about 54%, while p = 0.10
    stretches it by about 11%. Delaying work into a worse season therefore
    costs more than the delay itself. This is the non-linear effect the
    "start piling later" experiment measures.

Spells (two-state Markov chain)
    Real bad weather comes in spells: a plum-rain front or a monsoon surge lasts
    several days. With independent days a lost week is almost impossible
    (p^7 = 0.00006 for p = 0.25), so the spread of lost days, and with it P80,
    is understated. A station may therefore give, per month and weather kind,
    the MEAN SPELL LENGTH L: the average number of consecutive lost days.
    Each day's state then depends on yesterday's:

        p11 = P(lost today | lost yesterday)     = 1 - 1 / L
        p01 = P(lost today | workable yesterday) = p (1 - p11) / (1 - p)

    p01 is chosen so that the long-run share of lost days stays exactly p:
    the stationary probability p01 / (p01 + 1 - p11) simplifies to p. The
    monthly table keeps its meaning; spells only regroup the same lost days
    into runs. A run of lost days ends with probability 1 - p11 each day, so
    its length is geometric with mean 1 / (1 - p11) = L.

    Independence is the special case p11 = p, i.e. L = 1 / (1 - p).
    L below that would make lost days repel each other, so it is rejected.
    The lag-1 autocorrelation of the lost-day indicator is p11 - p01, and the
    variance of the lost days in a long window grows by about
    (1 + rho) / (1 - rho): same mean, wider spread.

Known limitation
    Rain and wind are still drawn independently of each other (a typhoon stops
    both). The planned upgrade is to resample whole historical years of daily
    records (block bootstrap) once CWA data is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


WEATHER_KINDS = ("rain", "wind")


class WeatherError(ValueError):
    """Raised when a weather table is missing or malformed."""


@dataclass(frozen=True)
class WeatherRule:
    """
    How weather turns into lost days WHEN weather is applied to the schedule
    (whether it is applied at all is Scenario.ignore_weather). Used with tables
    that store statistics per threshold (rain_by_threshold, wind_exceedance);
    tables with fixed stoppage shares ('rain', 'wind') ignore it.

    rain_mm             daily precipitation that stops rain-sensitive work
    wind_stop_ms        maximum 10-minute mean wind that stops wind-limited lifts
    stop_share          share of windy spells that actually stop work, 0..1.
                        Whole spells are kept or dropped, so their length is unchanged:
                            p = share * p',  L = L'
                        (p', L' measured on the station record). Because p <= p',
                        L' >= 1/(1 - p') >= 1/(1 - p), so the chain stays valid.
    remobilisation_days days lost after each wind stop; p' and L' are measured on
                        the record with those days added
    None takes the table's default for that setting.
    """
    rain_mm: float | None = None
    wind_stop_ms: int | None = None
    stop_share: float = 1.0
    remobilisation_days: int | None = None

    def __post_init__(self):
        if not 0.0 <= float(self.stop_share) <= 1.0:
            raise WeatherError("Stop share must be between 0 and 1")
        if self.remobilisation_days is not None and int(self.remobilisation_days) < 0:
            raise WeatherError("Remobilisation days must be >= 0")


TABLE_DEFAULTS = WeatherRule()


def _check_months(values, where: str, lo: float = 0.0, hi: float = 1.0, closed_hi: bool = False) -> list[float]:
    if values is None or len(values) != 12:
        raise WeatherError(f"{where}: needs 12 monthly values")
    vals = [float(v) for v in values]
    if any(not (lo <= v < hi or (closed_hi and v == hi)) for v in vals):
        raise WeatherError(f"{where}: values must be in [{lo:g}, {hi:g}{']' if closed_hi else ')'}")
    return vals


def _check_spells(spells, p: list[float], where: str) -> None:
    L = _check_months(spells, where, 1.0, float("inf"))
    for month, (l, q) in enumerate(zip(L, p), start=1):
        if l < independent_spell_days(q) - 1e-9:
            raise WeatherError(
                f"{where} month {month}: mean spell {l:g} days is shorter than "
                f"{independent_spell_days(q):.2f}, the value for independent days at p = {q:g}; "
                "spells cannot be shorter than that")


def _check_variant(v, where: str) -> None:
    q = _check_months((v or {}).get("p"), f"{where} 'p'")
    _check_spells((v or {}).get("mean_spell_days"), q, f"{where} 'mean_spell_days'")


def load_weather_table(path: str | Path) -> dict:
    """
    Read a weather YAML and check it. Per station, either fixed stoppage shares
        rain, wind              12 monthly shares of lost days, each in [0, 1)
        mean_spell_days         optional {rain, wind}, each >= 1/(1-p)
    or statistics per threshold (a WeatherRule picks among them)
        rain_by_threshold       {mm: {p: [12], mean_spell_days: [12]}}
        wind_exceedance         {m/s: {remobilisation_days: {p: [12], mean_spell_days: [12]}}}
    A table-level 'parameters' block gives each setting's default, options,
    source and verification status; defaults must be among the options.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise WeatherError(f"Weather table not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise WeatherError(f"Could not parse weather table {path}: {exc}") from exc

    stations = (data or {}).get("stations")
    if not stations:
        raise WeatherError(f"{path}: no 'stations' defined")
    for name, table in stations.items():
        where = f"{path}: station '{name}'"
        table = table or {}
        fixed = table.get("rain") is not None
        if fixed == (table.get("rain_by_threshold") is not None):
            raise WeatherError(f"{where}: give either 'rain' (fixed) or 'rain_by_threshold', not both or neither")
        if fixed:
            rain = _check_months(table.get("rain"), f"{where} 'rain'")
            wind = _check_months(table.get("wind"), f"{where} 'wind'")
            spells = table.get("mean_spell_days")
            if spells is not None:
                _check_spells((spells or {}).get("rain"), rain, f"{where} mean_spell_days 'rain'")
                _check_spells((spells or {}).get("wind"), wind, f"{where} mean_spell_days 'wind'")
            continue
        for mm, v in (table.get("rain_by_threshold") or {}).items():
            _check_variant(v, f"{where} rain_by_threshold {mm} mm")
        exceed = table.get("wind_exceedance")
        if not isinstance(exceed, dict) or not exceed:
            raise WeatherError(f"{where}: 'rain_by_threshold' needs 'wind_exceedance'")
        for thr, variants in exceed.items():
            if not isinstance(variants, dict) or 0 not in variants:
                raise WeatherError(f"{where}: wind_exceedance {thr} needs a variant for 0 remobilisation days")
            for r, v in variants.items():
                _check_variant(v, f"{where} wind_exceedance {thr} m/s, {r} remobilisation days")

    for key, spec in ((data or {}).get("parameters") or {}).items():
        opts = spec.get("options")
        if opts is not None and spec.get("default") not in opts:
            raise WeatherError(f"{path}: parameter '{key}' default {spec.get('default')} is not among {opts}")
        for field_ in ("label", "source", "status"):
            if not str(spec.get(field_, "")).strip():
                raise WeatherError(f"{path}: parameter '{key}' needs a '{field_}'")
    return data


def table_parameters(table: dict) -> dict:
    """The table's parameter block: {key: {label, default, options, unit, source, status}}."""
    return dict(table.get("parameters") or {})


def parameter_default(table: dict, key: str, fallback=None):
    return table_parameters(table).get(key, {}).get("default", fallback)


def independent_spell_days(p: float) -> float:
    """Mean run of lost days when days are independent: 1 / (1 - p)."""
    return 1.0 / (1.0 - float(p))


def has_spells(table: dict, station: str) -> bool:
    """Spell lengths are available: always for threshold tables, optional for fixed ones."""
    st = _station(table, station)
    return st.get("rain_by_threshold") is not None or st.get("mean_spell_days") is not None


def has_thresholds(table: dict, station: str) -> bool:
    """True when the station stores statistics per threshold (a WeatherRule applies)."""
    return _station(table, station).get("rain_by_threshold") is not None


def threshold_options(table: dict, station: str) -> dict[str, list]:
    """Thresholds and remobilisation days available at this station, ascending."""
    st = _station(table, station)
    exceed = st.get("wind_exceedance") or {}
    return {"rain_mm": sorted(float(t) if float(t) % 1 else int(t) for t in (st.get("rain_by_threshold") or {})),
            "wind_ms": sorted(int(t) for t in exceed),
            "remobilisation_days": sorted({int(r) for v in exceed.values() for r in v})}


def transition_probabilities(p: np.ndarray, spell_days: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    (p11, p01) of the two-state chain with long-run lost share p and mean spell
    length spell_days (see the module docstring).
    """
    p = np.asarray(p, dtype=float)
    p11 = 1.0 - 1.0 / np.asarray(spell_days, dtype=float)
    p01 = p * (1.0 - p11) / (1.0 - p)
    return p11, p01


def _month_index(start: date, horizon: int) -> np.ndarray:
    return pd.date_range(start=start, periods=horizon, freq="D").month.to_numpy() - 1


def _station(table: dict, station: str) -> dict:
    stations = table["stations"]
    if station not in stations:
        raise WeatherError(f"Station '{station}' not in table; available: {list(stations)}")
    return stations[station]


def _resolve(table: dict, rule: WeatherRule) -> tuple[float, int, float, int]:
    rain_mm = rule.rain_mm if rule.rain_mm is not None else parameter_default(table, "rain_mm", 10)
    wind = rule.wind_stop_ms if rule.wind_stop_ms is not None else parameter_default(table, "wind_stop_ms", 16)
    remob = (rule.remobilisation_days if rule.remobilisation_days is not None
             else parameter_default(table, "remobilisation_days", 0))
    return rain_mm, int(wind), float(rule.stop_share), int(remob)


def _pick(mapping: dict, key, what: str, station: str):
    for k, v in mapping.items():
        if float(k) == float(key):
            return v
    raise WeatherError(f"Station '{station}' has no {what} {key:g}; available: {sorted(mapping)}")


def monthly_loss(table: dict, station: str, kind: str,
                 rule: WeatherRule = TABLE_DEFAULTS) -> tuple[np.ndarray, np.ndarray | None]:
    """
    (p, mean spell length or None) per calendar month for one weather kind, when
    weather is applied. Fixed tables return their values; threshold tables follow
    the rule (None settings take the table defaults).
    """
    st = _station(table, station)
    if kind not in WEATHER_KINDS:
        raise WeatherError(f"Unknown weather kind '{kind}'")
    if st.get("rain") is not None:                                   # fixed stoppage table
        L = (st.get("mean_spell_days") or {}).get(kind)
        return np.asarray(st[kind], dtype=float), (np.asarray(L, dtype=float) if L is not None else None)
    rain_mm, wind_ms, share, remob = _resolve(table, rule)
    if kind == "rain":
        v = _pick(st["rain_by_threshold"], rain_mm, "rain threshold (mm)", station)
        return np.asarray(v["p"], dtype=float), np.asarray(v["mean_spell_days"], dtype=float)
    if share == 0:
        return np.zeros(12), np.ones(12)
    variants = _pick(st["wind_exceedance"], wind_ms, "wind threshold (m/s)", station)
    v = _pick(variants, remob, "remobilisation variant (days)", station)
    return share * np.asarray(v["p"], dtype=float), np.asarray(v["mean_spell_days"], dtype=float)


def daily_probabilities(table: dict, station: str, start: date, horizon: int,
                        rule: WeatherRule = TABLE_DEFAULTS) -> dict[str, np.ndarray]:
    """
    Build arrays p_rain[d] and p_wind[d] for d = 0 .. horizon-1, where day 0 = start.
    A 'none' entry of zeros is included so every activity can use the same code path.
    """
    months = _month_index(start, horizon)
    out = {kind: monthly_loss(table, station, kind, rule)[0][months] for kind in WEATHER_KINDS}
    out["none"] = np.zeros(horizon)
    return out


def daily_persistence(table: dict, station: str, start: date, horizon: int,
                      rule: WeatherRule = TABLE_DEFAULTS) -> dict[str, np.ndarray] | None:
    """
    Per weather kind, p11[d] = P(day d lost | day d-1 lost) from the mean spell
    lengths, or None when the station has none (independent days).
    """
    if not has_spells(table, station):
        return None
    months = _month_index(start, horizon)
    out = {}
    for kind in WEATHER_KINDS:
        p, L = monthly_loss(table, station, kind, rule)
        if L is None:
            raise WeatherError(f"Station '{station}' has no mean spell lengths for '{kind}'")
        p11, _ = transition_probabilities(p, L)
        out[kind] = p11[months]
    return out


def daily_exceedance(table: dict, station: str, start: date, days: int, kind: str,
                     threshold: float) -> np.ndarray | None:
    """
    Chance, per day, that the day reaches `threshold` (rain: mm; wind: 10-min
    maximum m/s), from the station record, for warnings; None if unknown.
    """
    st = _station(table, station)
    try:
        if kind == "rain" and st.get("rain_by_threshold"):
            v = _pick(st["rain_by_threshold"], threshold, "rain threshold (mm)", station)
        elif kind == "wind" and st.get("wind_exceedance"):
            v = _pick(st["wind_exceedance"], threshold, "wind threshold (m/s)", station)[0]
        else:
            return None
    except WeatherError:
        return None
    return np.asarray(v["p"], dtype=float)[_month_index(start, days)]


def day_to_date(start: date, day: float | np.ndarray):
    """Convert a day offset (or array of offsets) into calendar dates."""
    if np.isscalar(day):
        return start + timedelta(days=int(round(float(day))))
    return pd.to_datetime(start) + pd.to_timedelta(np.rint(day).astype(int), unit="D")


def date_to_day(start: date, when: date) -> int:
    return (when - start).days
