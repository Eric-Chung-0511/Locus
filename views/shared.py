"""
Look and helpers shared by every page.

Layout principles:
    one page, one question; the answer comes first as one sentence with the key
    number; one primary chart, full width; supporting tables in expanders.

UI rule: never show internal ids, snake_case codes or raw dictionaries.
All display text goes through locus.labels.
"""

from __future__ import annotations

import textwrap
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from locus import help as H
from locus import labels as L
from locus.weather import day_to_date

# ----------------------------------------------------------------- visual tokens
# Off-white base, light-blue accents, faint grid.
BG = "#FBFAF6"
GRID = "#E6EBF0"
INK = "#243240"
BLUE = "#3C7DB5"
BLUE_LIGHT = "#A9CBE8"
MUTED = "#8C99A6"
LATE = "#C8553D"
CONDITION_COLORS = {
    L.condition_label("weather"): "#6BA6D9",
    L.condition_label("productivity"): "#A9B7C6",
    L.condition_label("supply"): "#7DB9A5",
    L.condition_label("regulatory"): "#D9A35F",
    L.condition_label("milestone"): INK,
    L.condition_label("design"): "#9FB8D0",
    L.condition_label("handover"): "#B7A7C9",
    L.condition_label("mixed"): "#C9B8A6",
}
LINK_COLORS = {
    L.link_type_label("physical"): "#8C99A6",
    L.link_type_label("regulatory"): "#D9A35F",
    L.link_type_label("means"): "#6BA6D9",
    L.link_type_label("resource"): "#7DB9A5",
    L.link_type_label("logistics"): "#B39DDB",
    L.link_type_label("contractual"): "#E3B7A0",
}

ILLUSTRATIVE_NOTE = ("Weather values are an illustrative placeholder, not measured data: "
                     "these results demonstrate the method, not a forecast.")
DEFAULT_DISCLAIMER = "Simulation for demonstrating the method; not a forecast."

# Page files, used by st.navigation in app.py and by st.page_link on the Summary page.
PAGES = {
    "start": "views/start.py",
    "guide": "views/guide.py",
    "summary": "views/summary.py",
    "confidence": "views/confidence.py",
    "drivers": "views/drivers.py",
    "risks": "views/risks.py",
    "recovery": "views/recovery.py",
    "reviews": "views/reviews.py",
    "late_start": "views/late_start.py",
    "weather": "views/weather.py",
    "assumptions": "views/assumptions.py",
}


# ----------------------------------------------------------------- charts
def styled(fig: go.Figure, height: int = 420, legend: bool = False,
           legend_title: str | None = None) -> go.Figure:
    """
    Shared chart styling.

    automargin lets Plotly grow the margins to fit long category labels and date
    ticks, so nothing is clipped. The legend sits below the plot, clear of the
    toolbar, and is hidden for single-series charts (legend=False).
    """
    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=INK, size=13),
        margin=dict(l=10, r=10, t=16, b=10), height=height, showlegend=legend,
        hoverlabel=dict(bgcolor="white", font_color=INK, align="left"),
    )
    if legend:
        fig.update_layout(
            legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", x=0, xanchor="left",
                        yref="container", y=0, yanchor="bottom",
                        title=dict(text=f"{legend_title}  " if legend_title else "")),
            margin=dict(b=90),
        )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, automargin=True)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, automargin=True)
    return fig


def show(fig: go.Figure, toolbar: bool = False, **kwargs: Any):
    """Render a styled chart. The Plotly toolbar is hidden unless asked for."""
    return st.plotly_chart(fig, theme=None, config={"displayModeBar": toolbar, "displaylogo": False},
                           **kwargs)


def confidence_figure(finish: np.ndarray, S: dict, start, height: int = 420,
                      show_target: bool = True) -> go.Figure:
    """
    Cumulative chance of first fire by each date (the CDF of the simulated
    finish days), with vertical lines for the plan (and target), P50 and P80.
    """
    ms = np.sort(finish[np.isfinite(finish)])
    cdf = np.arange(1, ms.size + 1) / ms.size
    fig = go.Figure(go.Scatter(x=day_to_date(start, ms), y=cdf, mode="lines",
                               line=dict(color=BLUE, width=2.5, shape="hv"),
                               name="Chance of first fire by this date",
                               hovertemplate="%{x|%Y-%m-%d}<br>%{y:.0%}<extra></extra>"))
    # Reference lines. Plan and target often coincide: show one merged label then.
    markers = []
    if not show_target:
        markers.append(("Plan", S["plan_day"], INK, "dash"))
    elif abs(S["plan_day"] - S["target_day"]) < 1:
        markers.append(("Plan and target", S["plan_day"], INK, "dash"))
    else:
        markers += [("Plan", S["plan_day"], MUTED, "dot"), ("Target", S["target_day"], INK, "dash")]
    markers += [("P50", S["p50_day"], BLUE_LIGHT, "solid"), ("P80", S["p80_day"], BLUE, "solid")]
    markers.sort(key=lambda m: m[1])
    last_x, level = None, 0
    for label, day, color, dash in markers:
        # Stagger labels that sit within about ten days of each other.
        level = level + 1 if last_x is not None and day - last_x < 10 else 0
        last_x = day
        x = pd.Timestamp(day_to_date(start, day))
        fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, line=dict(color=color, dash=dash, width=1.5))
        fig.add_annotation(x=x, y=1.03 + 0.06 * level, text=label, showarrow=False,
                           font=dict(color=color, size=12), yanchor="bottom")
    fig.update_yaxes(tickformat=".0%", range=[0, 1.18], title="Chance of first fire by this date",
                     tickvals=[0, 0.2, 0.4, 0.6, 0.8, 1.0])
    fig.update_xaxes(title=None, tickformat="%b %Y")
    styled(fig, height)
    fig.update_layout(margin=dict(t=40))  # room for the modebar above the marker labels
    return fig


def gap_figure(gap_days: pd.DataFrame, labels: list[str], texts: list[str], start, plan_day: float,
               cause_keys: set[str], height: int = 360) -> go.Figure:
    """
    Horizontal waterfall of the plan gap (analysis.plan_gap_days): dark blue
    causes, grey simulated average, light blue spread to P80, near-black P80.
    `texts` are the hover explanations, one per row.
    """
    order = list(gap_days["step"])
    role = {"mean": MUTED, "p80": INK, "spread": BLUE_LIGHT}
    colors = [role.get(k, BLUE) for k in order]
    lengths = (gap_days["to_offset"] - gap_days["from_offset"]).tolist()
    bar_text = [f"{d:+d} d" if k in cause_keys or k == "spread"
                else f"+{d} d, {day_to_date(start, plan_day + d):%d %b %Y}"
                for k, d in zip(order, gap_days["days"])]
    hover = ["<br>".join(textwrap.wrap(f"<b>{lab}</b><br>{t}", 70, break_long_words=False,
                                       replace_whitespace=False)) for lab, t in zip(labels, texts)]
    fig = go.Figure(go.Bar(
        y=labels, x=lengths, base=gap_days["from_offset"], orientation="h", marker_color=colors,
        text=bar_text, textposition="outside", cliponaxis=False, customdata=hover,
        hovertemplate="%{customdata}<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=MUTED, dash="dot", width=1))
    fig.update_yaxes(autorange="reversed", title=None)
    # A short axis title: long ones are cut off on a phone; the plan date is in the bar labels.
    fig.update_xaxes(title="Days after the plan date", rangemode="tozero")
    styled(fig, height)
    fig.update_layout(bargap=0.35, margin=dict(r=110))
    return fig


def gap_table(labels: list[str], gap_days: pd.DataFrame, texts: list[str], actions: list[str]) -> None:
    """The plan gap as a Markdown table (wraps long text; a dataframe would cut it off)."""
    lines = ["| Step | Days | What it means | What you can do |", "|---|---:|---|---|"]
    for lab, d, t, a in zip(labels, gap_days["days"], texts, actions):
        lines.append(f"| {lab} | {d:+d} | {t} | {a} |")
    st.markdown("\n".join(lines))


# ----------------------------------------------------------------- numbers
def pct(value: float | None) -> str:
    """Share as a whole percentage; shares that round to 0% or 100% but are not exactly that say so."""
    if value is None or pd.isna(value):
        return ""
    if 0 < value < 0.005:
        return "<1%"
    if 0.995 < value < 1:
        return ">99%"
    return f"{value:.0%}"


def futures_count(share: float, n: int) -> str:
    """The number of simulated futures a share stands for, e.g. '0 of 1,000 futures'."""
    return f"{int(round(share * n)):,} of {n:,} futures"


def share_of_futures(share: float, n: int) -> str:
    """
    A share of simulated futures in words. A bare "0%" reads like a bug, so the
    extremes are spelled out: "none of the 1,000 simulated futures".
    """
    k = int(round(share * n))
    if k == 0:
        return f"none of the {n:,} simulated futures"
    if k == n:
        return f"all {n:,} simulated futures"
    return f"{pct(share)} of simulated futures ({k:,} of {n:,})"


def pts(value: float | None) -> str:
    """Change in probability shown in percentage points."""
    return "" if value is None or pd.isna(value) else f"{value * 100:+.1f} pts"


def days(value: float | None) -> str:
    return "" if value is None or pd.isna(value) else f"{value:.0f}"


# ----------------------------------------------------------------- page frame
def results() -> dict:
    """Results of the last run (set by app.py before the page runs)."""
    return st.session_state["results"]


def lang() -> str:
    """
    Guide language ('en' or 'zh'), chosen on the Guide page. It is kept under a
    plain session key (not a widget key) so it survives moving between pages,
    where the switch itself is not rendered.
    """
    return st.session_state.get("lang") or "en"


def help_text(key: str, with_title: bool = True) -> str:
    """
    One section of the in-app guide in the chosen language. A broken guide file
    shows a clear message instead of stopping the page.
    """
    try:
        text = H.section(key, lang())
    except H.HelpError as exc:
        return f"The help text could not be loaded: {exc}"
    if not with_title and text.startswith("## "):
        text = text.split("\n", 1)[1].lstrip() if "\n" in text else ""
    return text


def how_to_read(key: str) -> None:
    """Collapsed explanation of the current page, from the guide files."""
    with st.expander("How to read this page"):
        st.markdown(help_text(key, with_title=False))


def header(title: str, headline: str, help_key: str | None = None) -> None:
    """
    Page title, then the answer first: one sentence with the key number, one
    short status line (simulation, weather mode) and the page's help panel.
    The full disclaimer and the data citation are in the page footer.
    """
    st.title(title)
    st.subheader(headline)
    status_line()
    if help_key:
        how_to_read(help_key)


def status_line() -> None:
    """One short line under the headline: a simulation, and whether weather changes the dates."""
    R = results()
    first = "Illustrative weather" if R["illustrative"] else "Simulation, not a forecast"
    st.caption(f"{first} · {L.weather_status(R['weather']['on'])} · Sources at the bottom of the page")


def page_footer() -> None:
    """
    Small print at the bottom of every page (app.py draws it after the page):
    the plant is fictional; the results are a simulation, not a forecast;
    whether weather is applied to the schedule or only shown as warnings; and
    the weather statistics come from CWA records processed by the author (the
    citation required by the data licence). No agency logo, no endorsement.
    """
    R = results()
    W = R["weather"]
    table = W.get("table") or {}
    parts = [R["model"].meta.get("disclaimer", "").strip(),
             ILLUSTRATIVE_NOTE if R["illustrative"] else (table.get("disclaimer") or DEFAULT_DISCLAIMER),
             L.weather_mode_text(W["on"], W.get("settings")),
             table.get("citation") or ""]
    st.divider()
    st.caption(" ".join(x for x in parts if x))
