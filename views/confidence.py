"""Milestone confidence: how likely is first fire on the plan date, and how much contingency is needed?"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from locus import labels as L
from locus.weather import day_to_date
from views.shared import (BLUE, BLUE_LIGHT, INK, MUTED, futures_count, header, lang, pct, results,
                          share_of_futures, show, styled)

R = results()
S, base, start = R["summary"], R["base"], R["start"]
contingency = S["p80_day"] - S["plan_day"]
n = base.milestone_finish().size
# The target defaults to the plan date; a second, identical chance would read like an error.
same_target = abs(S["plan_day"] - S["target_day"]) < 1

header("Milestone confidence",
       f"The plan date holds in {share_of_futures(S['p_on_plan'], n)}; P80 needs {contingency:.0f} more days.",
       help_key="confidence")

lg = lang()
cols = st.columns(4 if same_target else 5)
k1, k2, k3, k4 = cols[:4]
k1.metric("Single-number plan", S["plan_date"].strftime("%Y-%m-%d"), help=L.metric_help("plan", lg))
k2.metric("Chance of meeting plan", pct(S["p_on_plan"]), futures_count(S["p_on_plan"], n),
          delta_color="off", delta_arrow="off", help=L.metric_help("p_plan", lg))
k3.metric("P50 first fire", S["p50_date"].strftime("%Y-%m-%d"),
          f"{S['p50_day'] - S['plan_day']:+.0f} days vs plan", delta_color="inverse",
          help=L.metric_help("p50", lg))
k4.metric("P80 first fire", S["p80_date"].strftime("%Y-%m-%d"),
          f"{contingency:+.0f} days vs plan", delta_color="inverse", help=L.metric_help("p80", lg))
if same_target:
    st.caption("The target is the plan date. Set **Target first-fire date** in the sidebar to test a "
               "committed date; its chance then appears next to the plan's.")
else:
    cols[4].metric(f"Chance of meeting target ({S['target_date']:%Y-%m-%d})", pct(S["p_on_target"]),
                   futures_count(S["p_on_target"], n), delta_color="off", delta_arrow="off",
                   help=L.metric_help("p_target", lg))

ms = np.sort(base.milestone_finish())
cdf = np.arange(1, ms.size + 1) / ms.size
fig = go.Figure(go.Scatter(x=day_to_date(start, ms), y=cdf, mode="lines",
                           line=dict(color=BLUE, width=2.5, shape="hv"),
                           name="Chance of first fire by this date",
                           hovertemplate="%{x|%Y-%m-%d}<br>%{y:.0%}<extra></extra>"))

# Reference lines. Plan and target often coincide: show one merged label then.
markers = []
if abs(S["plan_day"] - S["target_day"]) < 1:
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
styled(fig, 420)
fig.update_layout(margin=dict(t=40))  # room for the modebar above the marker labels
show(fig, toolbar=True)

st.caption("The single-number plan uses most-likely durations, planned deliveries and average weather, "
           "the way a typical schedule does. It is optimistic because durations skew late, deliveries "
           "rarely arrive early, and first fire waits for the last of several converging paths (merge bias).")
