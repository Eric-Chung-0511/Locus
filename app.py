"""
Locus: interactive front end (entry point).

Run:
    streamlit run app.py

This script owns what every page shares:
    - the scenario settings in the sidebar, in the order a first-time reader
      needs them (the rest is collapsed): the weather switch (off = warnings
      only; on = applied under the collapsed "Weather parameters"), "Delays to
      test" (fixed delays for site handover, design and fabrication), dates,
      "Advanced", iterations and Run,
    - the explicit Run button: changing a setting never recalculates; results
      update only when Run is pressed (st.session_state["run_params"]),
    - the cached simulation results (st.session_state["results"]),
    - the guide language (st.session_state["lang"]), set on the Guide page.
Each page in views/ answers exactly one question:
    Start here                : the story: the scenario, the plan, the simulation, where
                                the delay comes from, what-ifs (landing page)
    Guide                     : bilingual guide with the English / 中文 switch
                                (every other page also has "How to read this page")
    Summary                   : the two-minute view, one finding per page
    Milestone confidence      : how likely is the plan date, and the target?
    What drives the date      : Criticality Index with series chains merged
    Common risks              : what each common risk costs, and removing it is worth
    Win time back             : which proposals win time, and at what cost
    Reviews and latest dates  : latest acceptable arrival / submission dates
    Late-start cost           : late start with and without weather (the headline finding)
    Weather risk              : weather warnings, forced-stoppage stress test, spells
    Assumptions and sources   : every input with its source grade

UI rule: never show internal ids, snake_case codes or raw dictionaries.
All display text goes through locus.labels.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import streamlit as st
import yaml

from locus import analysis as A
from locus import labels as L
from locus.model import ModelError, load_model
from locus.simulate import (DEFAULT_HORIZON, RandomBank, Scenario, delays, deterministic_plan,
                            required_horizon, simulate)
from locus.weather import (WeatherError, WeatherRule, daily_exceedance, daily_persistence,
                           daily_probabilities, date_to_day, day_to_date, has_spells,
                           has_thresholds, load_weather_table,
                           table_parameters, threshold_options)
from views.shared import PAGES, page_footer

logging.basicConfig(level=logging.INFO)
ROOT = Path(__file__).parent
CONFIG = ROOT / "config"
STOPPAGE_STEP = 14   # days between tested stoppage start dates


def weather_rule(rule: tuple) -> WeatherRule:
    """(rain mm, wind stop m/s, stop share, remobilisation days) -> WeatherRule; None = table default."""
    rain_mm, wind_stop, share, remob = rule
    return WeatherRule(rain_mm=rain_mm, wind_stop_ms=wind_stop, stop_share=share, remobilisation_days=remob)


DEFAULT_RULE = (None, None, 1.0, None)


# ----------------------------------------------------------------- file names
def yaml_display_name(path: Path, *keys: str) -> str | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    for key in keys:
        data = data.get(key, {}) if isinstance(data, dict) else {}
    return data if isinstance(data, str) else None


def config_choices(pattern: str, *keys: str) -> dict[str, str]:
    """Map descriptive name -> file name for every config file matching the pattern."""
    choices = {}
    for p in sorted(CONFIG.glob(pattern)):
        choices[L.file_label(p.name, yaml_display_name(p, *keys))] = p.name
    return choices


# ----------------------------------------------------------------- cached work
@st.cache_resource(show_spinner=False)
def get_model(plant_file: str, rules_file: str, with_risks: bool = True):
    return load_model(CONFIG / plant_file, CONFIG / rules_file, with_risks=with_risks)


@st.cache_resource(show_spinner=False)
def long_daily(weather_file: str, station: str, start: date, rule: tuple = DEFAULT_RULE):
    """Ten years of daily weather probabilities: cheap 1-D arrays for point passes."""
    table = load_weather_table(CONFIG / weather_file)
    return daily_probabilities(table, station, start, DEFAULT_HORIZON, weather_rule(rule))


@st.cache_resource(show_spinner=False, max_entries=2)
def get_bank(plant_file: str, rules_file: str, n_iter: int, seed: int,
             weather_file: str, station: str, start: date, horizon: int, spells: bool,
             rule: tuple = DEFAULT_RULE):
    """
    Random numbers and prepared weather for one run. The horizon is sized from the
    model (required_horizon); weather draws are fixed per day, so the horizon only
    changes memory, never results. spells=True uses the station's mean spell
    lengths (Markov chain); otherwise days are independent. The weather is
    prepared under `rule` even when weather is switched off: the switch is a
    scenario flag, so both modes share the same random numbers.
    The bank always holds draws for every common risk, so runs with and
    without them share their random numbers.
    """
    model = get_model(plant_file, rules_file)
    table = load_weather_table(CONFIG / weather_file)
    bank = RandomBank(model, n_iter, seed, horizon=horizon)
    wr = weather_rule(rule)
    daily = daily_probabilities(table, station, start, bank.horizon, wr)
    persistence = daily_persistence(table, station, start, bank.horizon, wr) if spells else None
    bank.prepare_weather(daily, persistence)
    return bank, daily, bool(table.get("is_illustrative", False))


@st.cache_resource(show_spinner=False, max_entries=4)
def run_all(plant_file: str, rules_file: str, weather_file: str, station: str,
            start: date, target: date, n_iter: int, seed: int,
            confidence: float, max_shift_weeks: int, spells: bool, stoppage_days: int,
            risks: bool, weather_on: bool, rain_mm: float, wind_warning_ms: int, wind_stop_ms: int,
            stop_share: float, remobilisation_days: int, gust_factor: float,
            extra_days: tuple = ()) -> dict:
    """Every result the pages show, for one set of run parameters."""
    full = get_model(plant_file, rules_file)                   # with the plant's common risks
    risks = risks and bool(full.risks)
    model = full if risks else get_model(plant_file, rules_file, with_risks=False)
    table = load_weather_table(CONFIG / weather_file)
    thresholds = has_thresholds(table, station)
    rule = (rain_mm, wind_stop_ms, stop_share, remobilisation_days) if thresholds else DEFAULT_RULE
    table_spells = has_spells(table, station)
    spells = spells and table_spells
    # The late-start experiment and the stoppage test both push work later.
    horizon = required_horizon(full, long_daily(weather_file, station, start, rule),
                               extra_days=7 * max_shift_weeks + stoppage_days, tested=extra_days)
    bank, daily, illustrative = get_bank(plant_file, rules_file, n_iter, seed,
                                         weather_file, station, start, horizon, spells, rule)

    # The weather switch is a scenario flag: same random numbers in both modes.
    # The tested delays (Delays to test) apply to every scenario; the plan never carries them.
    mode = Scenario(ignore_weather=not weather_on, extra_days=extra_days)
    mode_off = Scenario(ignore_weather=True, extra_days=extra_days)
    mode_on = Scenario(ignore_weather=False, extra_days=extra_days)
    base = simulate(model, bank, mode)
    plan = deterministic_plan(model, daily, mode)
    plan_day = plan[model.milestone][1]
    target_day = date_to_day(start, target)
    shifts = list(range(0, max_shift_weeks + 1, 2))

    # Headline finding: the same experiments with and without weather.
    both = {}
    for on, scen in ((False, mode_off), (True, mode_on)):
        res = base if scen == mode else simulate(model, bank, scen)
        mode_plan = deterministic_plan(model, daily, scen)[model.milestone][1]
        both[on] = {"summary": A.milestone_summary(res, start, target_day, mode_plan),
                    "season": A.seasonal_experiment(model, bank, shifts, scen)}

    # Weather stress: when is the site exposed, what does a forced stoppage cost,
    # and (weather applied, same random numbers) what changes with and without spells.
    base_on = base if weather_on else simulate(model, bank, mode_on)
    exposed = A.weather_work_span(base_on)
    weather = {
        "station": table["stations"][station], "station_name": station,
        "table_has_spells": table_spells, "spells": spells,
        "on": bool(weather_on), "exposed": exposed, "stoppage_days": stoppage_days,
        "sweep": A.stoppage_sweep(model, bank, base, stoppage_days, STOPPAGE_STEP, target_day, start),
        "compare": None, "warnings": None,
        "table": {k: table.get(k) for k in ("display_name", "citation", "disclaimer", "provenance")},
        "parameters": table_parameters(table),
        "settings": {"rain_mm": rain_mm, "wind_warning_ms": wind_warning_ms, "wind_stop_ms": wind_stop_ms,
                     "stop_share": stop_share, "remobilisation_days": remobilisation_days,
                     "gust_factor": gust_factor} if thresholds else None,
    }
    if table_spells:
        other, _, _ = get_bank(plant_file, rules_file, n_iter, seed, weather_file, station,
                               start, horizon, not spells, rule)
        banks = {spells: (bank, base_on), not spells: (other, simulate(model, other, mode_on))}
        weather["compare"] = {
            key: {"summary": A.milestone_summary(res, start, target_day, plan_day),
                  "spells": A.weather_spells(b, *exposed)}
            for key, (b, res) in banks.items()
        }
    if thresholds:
        exceed = {"rain": {"stop": daily_exceedance(table, station, start, horizon, "rain", rain_mm)},
                  "wind": {"warning": daily_exceedance(table, station, start, horizon, "wind", wind_warning_ms),
                           "stop": daily_exceedance(table, station, start, horizon, "wind", wind_stop_ms)}}
        weather["warnings"] = A.weather_warnings(base, start, exceed)
    out = {
        "model": model, "base": base, "plan_day": plan_day, "start": start,
        "target_day": target_day, "illustrative": illustrative, "confidence": confidence,
        "summary": A.milestone_summary(base, start, target_day, plan_day),
        "gap": A.plan_gap(model, bank, daily, base),
        "sources": A.source_gap(model, bank, daily, base),
        "plan_times": plan,
        "extra_days": dict(extra_days),
        "crit": A.criticality_table(base, start),
        "chains": A.driver_chains(base),
        "mix": A.driving_link_mix(base),
        "latest": A.latest_dates(base, start, target_day, confidence),
        "recovery": A.recovery_options(model, bank, base, target_day),
        "season": both[bool(weather_on)]["season"],
        "both_modes": both,
        "weather": weather,
        # Common risks are always measured on the full model, so the page can
        # say what they cost even when they are switched off for the other pages.
        "risks": {"enabled": risks, "model": full,
                  "table": A.risk_contributions(full, bank, base if risks else simulate(full, bank, mode),
                                                target_day)},
    }
    # "What the analysis supports": latest dates against the P80 date (the date worth
    # committing to), not against the target, which defaults to the unreachable plan date.
    summary = out["summary"]
    out["latest_p80"] = A.latest_dates(base, start, summary["p80_day"], confidence)
    out["actions"] = A.supported_actions(model, summary, base.milestone_finish().size, out["sources"],
                                         out["risks"]["table"], risks, out["latest_p80"], out["recovery"],
                                         both)
    return out


@st.cache_resource(show_spinner=False)
def plan_date_only(plant_file: str, rules_file: str, weather_file: str, station: str, start: date,
                   weather_on: bool = False, rule: tuple = DEFAULT_RULE) -> date:
    """Deterministic plan date in the chosen weather mode, used as the default target."""
    model = get_model(plant_file, rules_file)
    daily = long_daily(weather_file, station, start, rule)
    plan = deterministic_plan(model, daily, Scenario(ignore_weather=not weather_on))
    return day_to_date(start, plan[model.milestone][1])


# ----------------------------------------------------------------------- page
st.set_page_config(page_title="Locus", layout="wide")

page = st.navigation([
    st.Page(PAGES["start"], title="Start here", default=True),
    st.Page(PAGES["guide"], title="Guide"),
    st.Page(PAGES["summary"], title="Summary"),
    st.Page(PAGES["confidence"], title="Milestone confidence"),
    st.Page(PAGES["drivers"], title="What drives the date"),
    st.Page(PAGES["risks"], title="Common risks"),
    st.Page(PAGES["recovery"], title="Win time back"),
    st.Page(PAGES["reviews"], title="Reviews and latest dates"),
    st.Page(PAGES["late_start"], title="Late-start cost"),
    st.Page(PAGES["weather"], title="Weather risk"),
    st.Page(PAGES["assumptions"], title="Assumptions and sources"),
])


def _option_index(options: list, value) -> int:
    for i, o in enumerate(options):
        if float(o) == float(value):
            return i
    return 0


with st.sidebar:
    st.header("Scenario")
    # Containers keep the reading order (weather, delays, dates, Advanced) while the
    # plant and rule pack, chosen under Advanced, are read first.
    weather_box = st.container()
    delays_box = st.expander("Delays to test")
    dates_box = st.container()
    advanced = st.expander("Advanced")

    plants = config_choices("*plant*.yaml", "meta", "name")
    rule_packs = config_choices("rules_*.yaml", "display_name")
    weathers = config_choices("weather_*.yaml", "display_name")
    if not plants or not rule_packs or not weathers:
        st.error("The config folder needs a plant file, a rule pack (rules_*.yaml) "
                 "and a weather table (weather_*.yaml).")
        st.stop()
    with advanced:
        plant_file = plants[st.selectbox("Plant", list(plants))]
        rules_file = rule_packs[st.selectbox("Rule pack", list(rule_packs))]
    try:
        model_preview = get_model(plant_file, rules_file)
    except (ModelError, ValueError) as exc:
        st.error(f"The plant or rule file has a problem: {exc}")
        st.stop()

    with weather_box:
        weather_on = st.toggle(
            "Apply weather to the schedule", value=False,
            help="Off (default): weather is shown as warnings only and does not change any date. "
                 "On: rain and wind stop weather-sensitive work under the rule in Weather parameters.")

        with st.expander("Weather parameters"):
            weather_file = weathers[st.selectbox("Weather table", list(weathers))]
            try:
                weather_table = load_weather_table(CONFIG / weather_file)
            except WeatherError as exc:
                st.error(str(exc))
                st.stop()
            station = st.selectbox("Station", list(weather_table["stations"]))
            pars = table_parameters(weather_table)
            rain_mm, wind_warning_ms, wind_stop_ms, stop_share, remobilisation_days, gust_factor = \
                None, None, None, 1.0, None, 1.0
            if has_thresholds(weather_table, station):
                opts = threshold_options(weather_table, station)

                def pick(key: str, label: str, options: list, unit: str):
                    spec = pars.get(key, {})
                    return st.selectbox(f"{label} ({unit})", options,
                                        index=_option_index(options, spec.get("default", options[0])),
                                        help=f"Source: {spec.get('source', '-')}. Status: {spec.get('status', '-')}.")

                rain_mm = pick("rain_mm", "Rain stoppage threshold", opts["rain_mm"], "mm/day")
                wind_warning_ms = pick("wind_warning_ms", "Wind warning threshold", opts["wind_ms"], "m/s, 10-min mean")
                wind_stop_ms = pick("wind_stop_ms", "Wind stoppage threshold", opts["wind_ms"], "m/s, 10-min mean")
                spec = pars.get("stop_share", {})
                stop_share = st.slider("Share of windy spells that stop work", 0, 100,
                                       int(round(100 * float(spec.get("default", 1.0)))), 10, format="%d%%",
                                       help=f"Source: {spec.get('source', '-')}. Status: {spec.get('status', '-')}.") / 100
                spec = pars.get("remobilisation_days", {})
                remobilisation_days = st.select_slider(
                    "Remobilisation days after each wind stop", options=opts["remobilisation_days"],
                    value=spec.get("default", opts["remobilisation_days"][0]),
                    help=f"Source: {spec.get('source', '-')}. Status: {spec.get('status', '-')}.")
                spec = pars.get("gust_factor", {})
                gust_factor = st.number_input(
                    "Gust factor (display only)", min_value=1.0, max_value=3.0, step=0.01,
                    value=float(spec.get("default", 1.5)),
                    help=f"Converts the wind thresholds to gust values for comparison with crane manuals; "
                         f"it does not change results. Source: {spec.get('source', '-')}. "
                         f"Status: {spec.get('status', '-')}.")
            station_spells = has_spells(weather_table, station)
            spells = st.checkbox("Bad weather comes in spells", value=station_spells, disabled=not station_spells,
                                 help="Use the mean spell lengths in the weather table: a lost day makes the "
                                      "next day more likely to be lost. Off: every day is drawn independently."
                                      if station_spells else "This weather table has no spell lengths.")
    rule = (rain_mm, wind_stop_ms, float(stop_share), remobilisation_days)

    with delays_box:
        adjustable = [n for n in model_preview.nodes.values() if n.adjustable]
        st.caption("Days late for each item, alone or together. All are on time by default. "
                   "The plan keeps its dates; the simulation carries the delays.")
        tested = {n.id: st.number_input(f"{n.short_name} (days late)", min_value=0, max_value=365,
                                        value=0, step=7, help=n.name)
                  for n in adjustable}
        if not adjustable:
            st.caption("This plant file offers no items to delay.")
    extra_days = delays(tested)

    with dates_box:
        default_start = date.fromisoformat(str(model_preview.meta.get("default_start_date", "2027-01-04")))
        start = st.date_input("Site start (first piling)", value=default_start)
        plan_default = plan_date_only(plant_file, rules_file, weather_file, station, start, weather_on, rule)
        target = st.date_input("Target first-fire date", value=plan_default,
                               help="Defaults to the single-number plan date. Move it to test a committed date.")

    with advanced:
        seed = st.number_input("Random seed", value=42, step=1)
        confidence = st.slider("Confidence for latest dates", 0.5, 0.95, 0.8, 0.05)
        max_shift = st.slider("Late-start experiment: up to (weeks)", 4, 20, 12, 2)
        stoppage_days = st.slider("Weather stress test: stoppage length (days)", 3, 21, 7, 1)
        plant_risks = bool(model_preview.risks)
        risks = st.checkbox("Common risks move many items together", value=plant_risks,
                            disabled=not plant_risks,
                            help="Apply the plant file's common risks (for example site productivity or "
                                 "a supply-chain disruption): one event that slows many items at once. "
                                 "Off: every duration varies independently."
                                 if plant_risks else "This plant file defines no common risks.")
    n_iter = st.select_slider("Iterations", options=[500, 1000, 2000, 5000], value=5000,
                              help="Number of simulated futures. 5,000 (default) gives the published figures; "
                                   "fewer runs faster.")
    run_pressed = st.button("Run", type="primary", width="stretch")
    notice = st.empty()

# Explicit run: pages always show the results for run_params, which change only
# when Run is pressed (or on the very first load, so the app is never empty).
current = {
    "plant_file": plant_file, "rules_file": rules_file, "weather_file": weather_file,
    "station": station, "start": start, "target": target, "n_iter": int(n_iter),
    "seed": int(seed), "confidence": float(confidence), "max_shift_weeks": int(max_shift),
    "spells": bool(spells), "stoppage_days": int(stoppage_days), "risks": bool(risks),
    "weather_on": bool(weather_on), "rain_mm": rain_mm, "wind_warning_ms": wind_warning_ms,
    "wind_stop_ms": wind_stop_ms, "stop_share": float(stop_share), "remobilisation_days": remobilisation_days,
    "gust_factor": float(gust_factor), "extra_days": extra_days,
}
if run_pressed or "run_params" not in st.session_state:
    st.session_state["run_params"] = dict(current)
params = st.session_state["run_params"]
if current != params:
    notice.caption("Settings changed. Press Run to update.")

try:
    with st.spinner("Running simulations"):
        st.session_state["results"] = run_all(**params)
except (ModelError, WeatherError, ValueError) as exc:
    st.error(f"The model could not run: {exc}")
    st.stop()

page.run()
# Disclaimer and data citation on every page, at the bottom (the licence asks for the citation).
page_footer()
