"""
Display helpers.

Rule: the UI never shows internal identifiers (TX_DELIV), snake_case codes
(regulatory, site_start) or raw dictionaries. Everything shown to a reader goes
through these functions, so wording stays consistent across every view.
"""

from __future__ import annotations

import textwrap
from datetime import date
from typing import Any, Mapping

from .weather import day_to_date

CONDITION_LABELS = {
    "weather": "Weather",
    "productivity": "Productivity",
    "supply": "Supply",
    "regulatory": "Review or permit",
    "milestone": "Milestone",
    "design": "Design",
    "handover": "Site handover",
    "mixed": "Mixed",
}

WEATHER_LABELS = {"none": "", "rain": "Rain", "wind": "Wind"}

LINK_TYPE_LABELS = {
    "physical": "Physical",
    "regulatory": "Regulatory",
    "means": "Means can change",
    "contractual": "Contractual",
    "resource": "Resource or sequence",
    "logistics": "Logistics or access",
    "combined": "Combined",
}

STATUS_LABELS = {"verified": "Verified", "pending": "Pending verification"}

CHART_LABEL_MAX = 40   # longer category labels squeeze the bars

LANGUAGES = {"en": "English", "zh": "中文"}

# Tooltips for the headline metrics, in the guide language chosen on the Guide page.
METRIC_HELP = {
    "plan": {
        "en": "Most-likely durations, deliveries on their planned day and average weather: "
              "the way a typical P6 schedule produces one date.",
        "zh": "用最可能工期、設備依計畫日到貨、平均天候算出的單一日期，也就是一般 P6 排程的做法。",
    },
    "p_plan": {
        "en": "Share of simulated futures in which first fire happens on or before the plan date. "
              "0% is a real result, not an error: the plan assumes every item takes its most-likely time "
              "at once, which almost never happens.",
        "zh": "模擬結果中，在計畫日當天或之前首次點火的比例。0% 是真實結果而非錯誤："
              "計畫假設每一項同時都以最可能工期完成，這幾乎不會發生。",
    },
    "p_target": {
        "en": "Share of simulated futures in which first fire happens on or before the target date.",
        "zh": "模擬結果中，在目標日當天或之前首次點火的比例。",
    },
    "p50": {
        "en": "Date by which half of the simulated futures have reached first fire.",
        "zh": "一半的模擬結果會在這天之前首次點火。",
    },
    "p80": {
        "en": "Date by which 80% of simulated futures have reached first fire. "
              "P80 minus the plan date is the contingency the plan needs.",
        "zh": "八成的模擬結果會在這天之前首次點火。P80 減去計畫日，就是這份計畫需要的緩衝天數。",
    },
}


# Why the single-number plan misses: one entry per step of analysis.plan_gap, in
# chart order, plus the two reference bars. "label" is the chart row (at most 40
# characters); "phrase" names a step inside a sentence; "what" explains the step; "action" is what a planner can do about it.
PLAN_GAP_STEPS = {
    "deliveries": {
        "label": "Deliveries arrive late",
        "phrase": "late deliveries",
        "what": "The plan puts every delivery on its planned day. Delay ranges start at zero, so a delivery "
                "can be late but never early, and on average it arrives after the planned day. Any delay set "
                "under Delays to test (site handover, design) also lands here.",
        "action": "Order long-lead items earlier, or hold float in front of the work that needs them.",
    },
    "durations": {
        "label": "Durations skew late",
        "phrase": "durations that skew late",
        "what": "The plan uses the most-likely duration. A job can overrun by more than it can underrun "
                "(for example 60 / 75 / 100 days: most likely 75, average 78), so the average is later.",
        "action": "Challenge most-likely durations that sit close to the best case; plan with averages.",
    },
    "merge": {
        "label": "Merge bias",
        "phrase": "merge bias",
        "label_weather": "Merge bias and weather spread",
        "what": "First fire waits for the last of several converging paths. Even when each path is on time "
                "on average, the latest of them usually is not.",
        "what_weather": " With weather applied, this step also holds the day-to-day spread of the weather, "
                        "which the plan replaces by an average loss.",
        "action": "Cut converging paths, or finish paths that are not critical early so they cannot become "
                  "the latest.",
    },
    "risks": {
        "label": "Common risks",
        "phrase": "common risks",
        "what": "Events that slow many items at once (see Common risks). The single-number plan does not "
                "carry them.",
        "action": "Mitigate the costliest risk first; the Common risks page ranks them.",
    },
    # Used by the split by source (Start here page).
    "weather": {
        "label": "Weather",
        "phrase": "weather",
        "what": "The plan takes off an average weather loss per day. In the simulation bad weather lands on "
                "particular days, often in spells, and costs more when it hits work that drives first fire.",
        "action": "Move weather-sensitive work to a better season, or protect it (covers, extra crews).",
    },
    "combined": {
        "label": "Combined effect (merge bias)",
        "phrase": "the combined effect",
        "what": "Each bar above is measured alone: that source kept to plan, everything else as simulated. "
                "Together they cost more, because first fire waits for the latest of several converging "
                "paths; fix one and another path takes over.",
        "action": "Work on several sources at once; fixing one alone gains less than its own bar suggests.",
    },
    "mean": {
        "label": "Simulated average",
        "what": "Where first fire lands on average: the plan plus the steps above.",
    },
    "spread": {
        "label": "Spread up to P80",
        "what": "Half of the futures finish after the average. Covering 80% of them needs this much more.",
        "action": "Only narrower ranges shrink it: firmer quotes, earlier reviews, proven crews.",
    },
    "p80": {
        "label": "P80: contingency needed",
        "what": "The plan plus every step: the contingency the plan needs to be met in 80% of futures.",
    },
}


def plan_gap_label(key: str, weather_applied: bool = False) -> str:
    entry = PLAN_GAP_STEPS[key]
    return entry.get("label_weather", entry["label"]) if weather_applied else entry["label"]


def plan_gap_phrase(key: str) -> str:
    """A step's name inside a sentence, e.g. "late deliveries"."""
    return PLAN_GAP_STEPS[key].get("phrase", PLAN_GAP_STEPS[key]["label"].lower())


def plan_gap_text(key: str, weather_applied: bool = False) -> str:
    entry = PLAN_GAP_STEPS[key]
    return entry["what"] + (entry.get("what_weather", "") if weather_applied else "")


def condition_label(code: str) -> str:
    return CONDITION_LABELS.get(code, code.replace("_", " ").capitalize())


def weather_label(code: str) -> str:
    return WEATHER_LABELS.get(code, code.replace("_", " ").capitalize())


def link_type_label(code: str) -> str:
    return LINK_TYPE_LABELS.get(code, code.replace("_", " ").capitalize())


def status_label(code: str) -> str:
    return STATUS_LABELS.get(code, code.replace("_", " ").capitalize())


def metric_help(key: str, lang: str = "en") -> str:
    """Tooltip for a headline metric in the chosen guide language (falls back to English)."""
    texts = METRIC_HELP[key]
    return texts.get(lang, texts["en"])


def cap(text: str, limit: int = CHART_LABEL_MAX) -> str:
    """Shorten a chart category label to at most `limit` characters."""
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,;:") + "…"


HOVER_WRAP_WIDTH = 60   # Plotly hover boxes do not wrap on their own; long single


def wrap_hover(text: str, width: int = HOVER_WRAP_WIDTH) -> str:
    """
    Break a long hover-text line into several lines (Plotly '<br>') at word
    boundaries, each at most `width` characters. Plotly draws a hover box as
    wide as its longest unbroken line, so an un-wrapped sentence can overflow
    past the edge of the chart's container and get clipped; wrapping keeps the
    box narrow enough to stay inside it.
    """
    return "<br>".join(textwrap.wrap(str(text), width=width)) or str(text)


def chain_label(first: str, last: str, n: int, limit: int = CHART_LABEL_MAX) -> str:
    """
    Chart label for items that are always critical together:
        'Gate A: vacuum … First fire (2 items)'                  (fits on one line)
        'Turbine hall piling …<br>Turbine hall steel, main bays (3 items)'
    When one line would exceed `limit`, the label wraps onto two lines (Plotly
    '<br>'), each at most `limit` characters, so the item count stays visible.
    """
    if n == 1:
        return cap(first, limit)
    tail = f" ({n} items)"
    one_line = f"{first} … {last}{tail}"
    if len(one_line) <= limit:
        return one_line
    return f"{cap(first, limit - 2)} …<br>{cap(last, limit - len(tail))}{tail}"


def plain_label(label: str) -> str:
    """Chart label as one line of plain text (for tables and hover text)."""
    return label.replace(" …<br>", " … ").replace("<br>", " ")


def origin_label(origin: str) -> str:
    """'plant' -> 'Plant file', 'rule:R01' -> 'Rule R01'."""
    if origin.startswith("rule:"):
        return f"Rule {origin.split(':', 1)[1]}"
    return "Plant file"


def relation_label(rel: str, lag: float) -> str:
    """'FS', 20 -> 'Finish to start, +20 d'."""
    names = {"FS": "Finish to start", "SS": "Start to start"}
    lag = int(round(lag))
    lag_txt = "" if lag == 0 else f", {'+' if lag > 0 else ''}{lag} d"
    return f"{names.get(rel, rel)}{lag_txt}"


def distribution_text(spec: Mapping[str, Any] | None, unit: str = "days") -> str:
    """
    Human-readable distribution:
        triangular -> '90 / 110 / 140 days (min / most likely / max)'
        lognormal  -> 'median 28 days, P90 45 days'
        fixed      -> '14 days'
    """
    if not spec:
        return ""
    kind = spec.get("dist")
    if kind == "triangular":
        return (f"{spec['min']:g} / {spec['mode']:g} / {spec['max']:g} {unit} "
                f"(min / most likely / max)")
    if kind == "lognormal":
        return f"median {spec['median']:g} {unit}, P90 {spec['p90']:g} {unit}"
    if kind == "fixed":
        return f"{spec['value']:g} {unit}"
    return str(kind)


def risk_impact_text(effect: str, spec: Mapping[str, Any] | None) -> str:
    """
    Size of a common risk when it occurs:
        factor -> 'durations x 1 / 1.08 / 1.25 (min / most likely / max)'
        days   -> '+10 / 30 / 90 days (min / most likely / max)'
    """
    if not spec:
        return ""
    if effect == "days":
        return "+" + distribution_text(spec)
    kind = spec.get("dist")
    if kind == "triangular":
        return f"durations × {spec['min']:g} / {spec['mode']:g} / {spec['max']:g} (min / most likely / max)"
    if kind == "lognormal":
        return f"durations × median {spec['median']:g}, P90 {spec['p90']:g}"
    if kind == "fixed":
        return f"durations × {spec['value']:g}"
    return str(kind)


def weather_status(on: bool) -> str:
    """A few words for the top of every page: is weather applied to the dates?"""
    return ("Weather: applied to the schedule" if on
            else "Weather: shown as warnings only, not applied to the dates")


def weather_mode_text(on: bool, settings: Mapping[str, Any] | None) -> str:
    """One sentence: is weather applied to the schedule, and under which rule."""
    if settings is None:
        return ("Weather is applied to the schedule." if on else
                "Weather is shown as warnings only; it is not applied to the schedule.")
    if not on:
        return ("Weather is shown as possible impacts (warnings) only; it is not applied to the schedule. "
                "Switch on \"Apply weather to the schedule\" to include it.")
    share, remob = float(settings["stop_share"]), int(settings["remobilisation_days"])
    wind = ("wind never stops work (share of windy spells set to 0%)" if share == 0 else
            f"10-min mean wind ≥ {settings['wind_stop_ms']:g} m/s stops wind-limited lifts in {share:.0%} of "
            f"windy spells, plus {remob} remobilisation day{'' if remob == 1 else 's'} after each stop")
    return (f"Weather is applied to the schedule: rain ≥ {settings['rain_mm']:g} mm/day stops civil and outdoor "
            f"work; {wind}.")


def node_duration_text(node, start: date) -> str:
    """Duration text for activities, planned arrival plus delay for external inputs."""
    if node.kind == "external":
        planned = day_to_date(start, node.planned_day).strftime("%Y-%m-%d")
        return f"Planned {planned}, delay {distribution_text(node.delay)}"
    unit = "working days" if node.weather != "none" else "days"
    return distribution_text(node.duration, unit)


def file_label(filename: str, meta_name: str | None = None) -> str:
    """Show a config file by its descriptive name, never by its file name."""
    if meta_name:
        return meta_name
    stem = filename.rsplit(".", 1)[0]
    for prefix in ("weather_", "rules_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    return stem.replace("_", " ").capitalize()


# ------------------------------------------------------ what the analysis supports
def days_text(n: float) -> str:
    """'1 day', '3 days'."""
    k = int(round(n))
    return f"{k} day" if k == 1 else f"{k} days"


def _lower_first(text: str) -> str:
    """Lower-case the first letter for use inside a sentence, unless it starts an acronym (GT, E&I)."""
    text = text.strip().rstrip(".")
    if len(text) > 1 and text[0].isupper() and not (text[1].isupper() or text[1] in "&/"):
        return text[0].lower() + text[1:]
    return text


def supported_action_text(fact: dict) -> tuple[str, str, str]:
    """
    Title, evidence and trade-off for one action from analysis.supported_actions,
    in a neutral voice: what the analysis supports, not what someone decided.
    """
    k = fact["key"]
    if k == "commit":
        hits = "none" if fact["hits"] == 0 else f"{fact['hits']:,}"
        return (f"Commit to {fact['p80_date']:%d %b %Y} (P80), not {fact['plan_date']:%d %b %Y}",
                f"The single-number plan holds in {hits} of {fact['n']:,} simulated futures; the P80 date holds in "
                f"four out of five. That is {days_text(fact['contingency'])} of contingency.",
                "The committed date is later than the plan, so the owner needs to hear why early.")
    if k == "focus":
        parts = []
        if "source" in fact:
            parts.append(f"{fact['source']} is the largest source of delay (+{days_text(fact['source_days'])} on "
                         f"average). {fact['source_action']}")
        if "risk" in fact:
            parts.append(f"Removing the costliest common risk, {_lower_first(fact['risk'])} (it occurs in "
                         f"{fact['risk_probability']:.0%} of futures), brings P80 {days_text(fact['risk_gain'])} earlier.")
        return ("Put mitigation effort where the days are", " ".join(parts),
                "Mitigation costs money (earlier orders, expediting, supervision); the days above say what it is worth.")
    if k == "watch":
        items = ", ".join(f"{name} ({m:+d} days)" for name, m in fact["tightest"])
        extra = []
        if fact.get("design_float") is not None:
            extra.append(f"design can slip up to {days_text(fact['design_float'])}")
        if fact.get("handover_float") is not None:
            extra.append(f"the site can be handed over up to {days_text(fact['handover_float'])} late")
        joined = " and ".join(extra)
        tail = (" " + joined[0].upper() + joined[1:] + " without putting that date at risk.") if extra else ""
        return ("Track the items with the least float every week",
                f"Measured against the P80 date, the tightest are {items}.{tail}",
                "Float is only real while these dates hold; a slip here uses the contingency first.")
    if k == "proposals":
        n_useful = len(fact["useful"])
        useful = "; ".join(f"\u201c{p}\u201d wins {days_text(g)}" for p, g in fact["useful"])
        together = (f" All {fact['n_tested']} together win {days_text(fact['together'])}."
                    if fact.get("together") else "")
        idle = ""
        if fact.get("idle"):
            name, share, cost = fact["idle"]
            idle = (f" Skip proposals such as \u201c{name}\u201d: that link drives first fire in {share:.0%} of "
                    f"futures, so its cost ({_lower_first(cost)}) buys no time.")
        title = ("Use the one proposal that wins time, skip the rest" if n_useful == 1
                 else f"Use the {n_useful} proposals that win time, skip the rest")
        return (title, f"At P50: {useful}.{together}{idle}",
                "Each proposal moves some risk elsewhere; its cost is listed on Win time back.")
    if k == "start":
        return ("Protect the site start",
                f"Starting {fact['weeks']} weeks late moves first fire (P50) by {days_text(fact['off_days'])}, or "
                f"{days_text(fact['on_days'])} with recorded weather, because the work is pushed into a worse season.",
                "The handover and the start-of-works approval sit with the owner and the authority; "
                "agree them early.")
    raise ValueError(f"Unknown action '{k}'")
