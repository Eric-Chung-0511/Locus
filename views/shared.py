"""
Look and helpers shared by every page.

Layout principles:
    one page, one question; the answer comes first as one sentence with the key
    number; one primary chart, full width; supporting tables in expanders.

UI rule: never show internal ids, snake_case codes or raw dictionaries.
All display text goes through locus.labels.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from locus import help as H
from locus import labels as L

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
        hoverlabel=dict(bgcolor="white", font_color=INK),
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
    Page title, then the answer first: one sentence with the key number, the
    illustrative-weather note when it applies, and the page's help panel.
    """
    st.title(title)
    st.subheader(headline)
    source_note()
    if help_key:
        how_to_read(help_key)


def source_note() -> None:
    """
    Small note on every page: the results are a simulation, not a forecast;
    whether weather is applied to the schedule or only shown as warnings; and
    the weather statistics come from CWA records processed by the author (the
    citation required by the data licence). No agency logo, no endorsement.
    """
    R = results()
    W = R["weather"]
    table = W.get("table") or {}
    parts = [ILLUSTRATIVE_NOTE if R["illustrative"] else (table.get("disclaimer") or DEFAULT_DISCLAIMER),
             L.weather_mode_text(W["on"], W.get("settings")),
             table.get("citation") or ""]
    st.caption(" ".join(x for x in parts if x))
