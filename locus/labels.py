"""
Display helpers.

Rule: the UI never shows internal identifiers (TX_DELIV), snake_case codes
(regulatory, site_start) or raw dictionaries. Everything shown to a reader goes
through these functions, so wording stays consistent across every view.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .weather import day_to_date

CONDITION_LABELS = {
    "weather": "Weather",
    "productivity": "Productivity",
    "supply": "Supply",
    "regulatory": "Review or permit",
    "milestone": "Milestone",
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
                "can be late but never early, and on average it arrives after the planned day.",
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
    "mean": {
        "label": "Simulated average",
        "what": "Where first fire lands on average: the plan plus the four steps above.",
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
