"""Milestone confidence: how likely is first fire on the plan date, and how much contingency is needed?"""

from __future__ import annotations

import textwrap

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from locus import analysis as A
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

# Why the plan misses: the plan gap in whole days (steps add up to the totals shown).
gap = R["gap"]
weather_applied = gap["weather_applied"]
gap_days = A.plan_gap_days(gap)
causes = gap_days[gap_days["step"].isin(A.GAP_STEPS)].sort_values("days", ascending=False)
mean_offset = int(gap_days.loc[gap_days["step"] == "mean", "days"].iloc[0])


def cause(row) -> str:
    return f"{L.plan_gap_phrase(row['step'])} (+{row['days']} days)"


top = [r for _, r in causes.head(2).iterrows() if r["days"] > 0]
if len(top) == 2:
    share = (top[0]["days"] + top[1]["days"]) / mean_offset if mean_offset > 0 else 0
    verb = "explain most of the gap" if share > 0.5 else "are the largest causes"
    why = f"{cause(top[0])} and {cause(top[1])} {verb}"
elif top:
    why = f"the largest cause is {cause(top[0])}"
else:
    why = "the four optimistic assumptions cost almost nothing here"

header("Milestone confidence",
       f"The plan date holds in {share_of_futures(S['p_on_plan'], n)}: {why}. "
       f"P80 needs {contingency:.0f} more days.",
       help_key="confidence")

lg = lang()
cols = st.columns(4 if same_target else 5)
cols[0].metric("Single-number plan", S["plan_date"].strftime("%Y-%m-%d"), help=L.metric_help("plan", lg))
cols[1].metric("P50 first fire", S["p50_date"].strftime("%Y-%m-%d"),
               f"{S['p50_day'] - S['plan_day']:+.0f} days vs plan", delta_color="inverse",
               help=L.metric_help("p50", lg))
cols[2].metric("P80 first fire", S["p80_date"].strftime("%Y-%m-%d"),
               f"{contingency:+.0f} days vs plan", delta_color="inverse", help=L.metric_help("p80", lg))
cols[3].metric("Chance of meeting plan", pct(S["p_on_plan"]), futures_count(S["p_on_plan"], n),
               delta_color="off", delta_arrow="off", help=L.metric_help("p_plan", lg))
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

st.caption("The single-number plan uses most-likely durations, deliveries on their planned day and average "
           "weather, the way a typical schedule does. Why it is optimistic, and by how much for each reason, "
           "is shown under Why the plan misses.")

# ------------------------------------------------------------- why the plan misses
st.subheader("Why the plan misses")
st.write(
    f"The single-number plan takes four best cases at once. Each bar removes one of them and shows how far "
    f"first fire moves; together they take the plan to the simulated average (+{mean_offset} days), and the "
    f"spread of outcomes adds the rest of the contingency up to P80 (+{contingency:.0f} days).")

plan_date = S["plan_date"]
order = list(gap_days["step"])
labels = [L.plan_gap_label(k, weather_applied) for k in order]
role = {"mean": MUTED, "p80": INK, "spread": BLUE_LIGHT}
colors = [role.get(k, BLUE) for k in order]
lengths = (gap_days["to_offset"] - gap_days["from_offset"]).tolist()
text = [f"{d:+d} d" if k in A.GAP_STEPS or k == "spread" else f"+{d} d, {day_to_date(start, S['plan_day'] + d):%d %b %Y}"
        for k, d in zip(order, gap_days["days"])]
hover = [f"<b>{lab}</b><br>{L.plan_gap_text(k, weather_applied)}" for k, lab in zip(order, labels)]
wrapped = ["<br>".join(textwrap.wrap(h, 70, break_long_words=False, replace_whitespace=False)) for h in hover]
fig = go.Figure(go.Bar(
    y=labels, x=lengths, base=gap_days["from_offset"], orientation="h", marker_color=colors,
    text=text, textposition="outside", cliponaxis=False, customdata=wrapped,
    hovertemplate="%{customdata}<extra></extra>"))
fig.add_vline(x=0, line=dict(color=MUTED, dash="dot", width=1))
fig.update_yaxes(autorange="reversed", title=None)
fig.update_xaxes(title=f"Days after the single-number plan ({plan_date:%d %b %Y})", rangemode="tozero")
styled(fig, 360)
fig.update_layout(bargap=0.35, margin=dict(r=110))
show(fig)
st.caption(
    "Dark blue: the four optimistic assumptions, removed one at a time in this order on the same random "
    "numbers, so they add up exactly. Grey: where first fire lands on average. Light blue: the spread up to "
    "P80. Near-black: the contingency needed. The steps interact, so another order would move a few days "
    "between them, never the total. The chain uses the average; P50 is "
    f"{S['p50_day'] - S['plan_day']:+.0f} days, close to it."
    + (" Common risks here is how far they move the average; the Common risks page reports how far they "
       "move P80, which is more because risks also widen the spread." if gap["has_risks"] else ""))

with st.expander("What each step means and what you can do about it"):
    # A Markdown table wraps long text; a dataframe would cut it off.
    lines = ["| Step | Days | What it means | What you can do |", "|---|---:|---|---|"]
    for key, lab, d in zip(order, labels, gap_days["days"]):
        lines.append(f"| {lab} | {d:+d} | {L.plan_gap_text(key, weather_applied)} | "
                     f"{L.PLAN_GAP_STEPS[key].get('action', '')} |")
    st.markdown("\n".join(lines))
