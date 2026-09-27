"""
Start here: the story for a first-time reader, in five steps.

1. The scenario: what is being simulated (a generic plant, the phases on a timeline).
2. What the plan says: the single-number date a typical schedule produces.
3. What the simulated futures say: the chance of that date, P50 and P80.
4. Where the delay comes from: the gap split by source (design, equipment,
   permits, ...), each measured by leaving it out on the same random numbers.
5. What if: three precomputed comparisons, then links to every other page.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from locus import analysis as A
from locus import labels as L
from locus.weather import day_to_date
from views.shared import (BLUE, INK, PAGES, confidence_figure, futures_count, gap_figure, header, pct,
                          results, show, styled)

R = results()
S, base, start, model = R["summary"], R["base"], R["start"], R["model"]
n = base.milestone_finish().size
contingency = S["p80_day"] - S["plan_day"]
gap = R["sources"] or R["gap"]
by_source = R["sources"] is not None
gap_days = A.plan_gap_days(gap)
mean_offset = int(gap_days.loc[gap_days["step"] == "mean", "days"].iloc[0])

header("Start here",
       f"A schedule says first fire on {S['plan_date']:%d %b %Y}. Across {n:,} simulated futures it lands "
       f"{mean_offset} days later on average, and a date you can promise with 80% confidence is "
       f"{contingency:.0f} days later.",
       help_key="start_here")

# --------------------------------------------------------------- 1. scenario
st.subheader("1. What is being simulated")
st.write(
    "A generic single-shaft combined-cycle unit (gas turbine, generator and steam turbine on one shaft), "
    "one unit, built in Taiwan for a utility owner. The main equipment comes from overseas makers. "
    "The simulation runs from the site handover and the start-of-works approval, through piling, "
    "buildings and equipment setting, to commissioning and the gas turbine's **first fire**. "
    "The plant, its durations and its risks are illustrative: this demonstrates a method, "
    "it is not a forecast of any real project.")

plan_times = R["plan_times"]
spans = {}
for nid, (s_day, f_day) in plan_times.items():
    group = model.nodes[nid].group
    lo, hi = spans.get(group, (s_day, f_day))
    spans[group] = (min(lo, s_day), max(hi, f_day))
phases = pd.DataFrame([{"group": g, "start": a, "finish": b} for g, (a, b) in spans.items()])
# Rows follow the plant file's `groups` order (the logical sequence: handover, design,
# construction, deliveries, reviews, then the commissioning gates 0, A, B, C).
rank = {g: i for i, g in enumerate(model.groups)}
phases["rank"] = phases["group"].map(lambda g: rank.get(g, len(rank)))
phases = phases.sort_values(["rank", "start"]).reset_index(drop=True)
to_date = lambda d: pd.Timestamp(day_to_date(start, d))
fig = go.Figure()
bars = phases[phases["finish"] > phases["start"]]
fig.add_trace(go.Bar(
    y=bars["group"], x=[(to_date(b) - to_date(a)).total_seconds() * 1000 for a, b in zip(bars["start"], bars["finish"])],
    base=[to_date(a) for a in bars["start"]], orientation="h", marker_color=BLUE,
    customdata=[f"{to_date(a):%d %b %Y} to {to_date(b):%d %b %Y}" for a, b in zip(bars["start"], bars["finish"])],
    hovertemplate="%{y}<br>%{customdata}<extra></extra>"))
points = phases[phases["finish"] <= phases["start"]]
if not points.empty:
    fig.add_trace(go.Scatter(
        y=points["group"], x=[to_date(a) for a in points["start"]], mode="markers",
        marker=dict(symbol="diamond", size=12, color=INK),
        hovertemplate="%{y}<br>%{x|%d %b %Y}<extra></extra>"))
milestone_x = to_date(S["plan_day"])
fig.add_shape(type="line", x0=milestone_x, x1=milestone_x, y0=0, y1=1, yref="paper",
              line=dict(color=INK, dash="dash", width=1.5))
fig.add_annotation(x=milestone_x, y=1.0, yref="paper", text="Planned first fire", showarrow=False,
                   xanchor="right", yanchor="bottom", font=dict(color=INK, size=12))
fig.update_yaxes(autorange="reversed", title=None, categoryorder="array", categoryarray=list(phases["group"]))
fig.update_xaxes(title=None, type="date", tickformat="%b %Y")
styled(fig, 420)
fig.update_layout(bargap=0.3, margin=dict(t=30))
show(fig)
st.caption("The plan's phases, from site handover to first fire, in logical order. Diamonds are single events "
           "(for example the site handover); bars span the first start to the last finish of each group. Design "
           "is dated before piling because drawings must be issued before the work that needs them. Power receipt "
           "starts early because its test reports are submitted months ahead; the commissioning gates A, B and C "
           "all follow power feeding.")

# ------------------------------------------------------------- 2. the plan
st.subheader("2. What the plan says")
c1, c2 = st.columns([1, 2])
c1.metric("Single-number plan", f"{S['plan_date']:%d %b %Y}")
c2.write("This is how a typical schedule (for example in Primavera P6) produces one date: every task takes "
         "its most likely duration, every delivery arrives on its planned day, weather is an average, and "
         "nothing unexpected happens.")

# ------------------------------------------------------ 3. simulated futures
st.subheader(f"3. What {n:,} simulated futures say")
st.write(
    f"The same schedule is re-run {n:,} times. In each run every duration, delivery and review is drawn "
    "from its range, and common risks such as low site productivity may or may not happen"
    + (", and bad weather falls on particular days" if gap["weather_applied"] else "") + ". "
    "Each run is one possible future.")
k1, k2, k3 = st.columns(3)
k1.metric("Chance the plan date holds", pct(S["p_on_plan"]), futures_count(S["p_on_plan"], n),
          delta_color="off", delta_arrow="off")
k2.metric("Half of the futures by (P50)", f"{S['p50_date']:%d %b %Y}",
          f"{S['p50_day'] - S['plan_day']:+.0f} days vs plan", delta_color="inverse")
k3.metric("80% of the futures by (P80)", f"{S['p80_date']:%d %b %Y}",
          f"{contingency:+.0f} days vs plan", delta_color="inverse")
show(confidence_figure(base.milestone_finish(), S, start, height=340, show_target=False))
st.caption("For each date, the share of futures that have reached first fire. The plan sits where the curve "
           "has barely started; P80 is the date to promise when you want to be right four times out of five.")

# ---------------------------------------------------- 4. where the delay comes from
st.subheader("4. Where does the delay come from?")
order = list(gap_days["step"])
if by_source:
    st.write("Each bar asks one question: **if only this source went exactly to plan, how much earlier would "
             "first fire be on average?** The last bar is what they add on top when they happen together.")
    label_of = lambda r: r["label"] if isinstance(r.get("label"), str) else L.plan_gap_label(r["step"])
    text_of = lambda r: r["what"] if isinstance(r.get("what"), str) else L.plan_gap_text(r["step"])
    labels = [label_of(r) for _, r in gap_days.iterrows()]
    texts = [text_of(r) for _, r in gap_days.iterrows()]
    causes = set(gap["sources"]) | {"weather", "risks", "combined"}
else:
    labels = [L.plan_gap_label(k, gap["weather_applied"]) for k in order]
    texts = [L.plan_gap_text(k, gap["weather_applied"]) for k in order]
    causes = set(A.GAP_STEPS)
show(gap_figure(gap_days, labels, texts, start, S["plan_day"], causes, height=420))
tested = R.get("extra_days") or {}
zero_note = ("Site handover and design are assumed on time, so they add nothing here; "
             "set a delay under **Delays to test** in the sidebar and press Run to see what one would cost. "
             if not tested else
             f"Tested delays are on: {', '.join(f'{model.nodes[k].short_name} +{v:.0f} days' for k, v in tested.items())}. ")
st.caption(zero_note + "Each bar is measured on the same random numbers, and the bars add up exactly to the "
           "simulated average. Hover over a bar for what it covers. The expert view, by mechanism "
           "(skewed durations, merge bias), is on Milestone confidence.")
with st.expander("What each bar means"):
    lines = ["| Source | Days | What it covers |", "|---|---:|---|"]
    for lab, d, t in zip(labels, gap_days["days"], texts):
        lines.append(f"| {lab} | {d:+d} | {t} |")
    st.markdown("\n".join(lines))

# ------------------------------------------------------------------ 5. what if
st.subheader("5. What if...")
both = R["both_modes"]
risk_table = R["risks"]["table"]
options = ["Site start slips 4 weeks", "Weather is applied", "The costliest common risk is removed"]
choice = st.segmented_control("Try one", options, default=options[0])
if choice == options[0]:
    found = A.late_start_headline(both)
    if found:
        k, off_days, on_days = found
        st.info(f"If the site handover or the start-of-works approval slips {k} weeks, first fire (P50) moves "
                f"**{off_days:.0f} days** without weather and **{on_days:.0f} days** with recorded weather. "
                "Float absorbs part of the slip; weather can add to it by pushing civil work and heavy lifts "
                "into a worse season. See Late-start cost.")
elif choice == options[1]:
    off, on = both[False]["summary"], both[True]["summary"]
    moved = "does not move" if abs(on["plan_day"] - off["plan_day"]) < 1 else \
        f"moves {on['plan_day'] - off['plan_day']:+.0f} days"
    st.info(f"With recorded weather applied, P80 first fire moves from {off['p80_date']:%d %b %Y} to "
            f"{on['p80_date']:%d %b %Y} (**{on['p80_day'] - off['p80_day']:+.0f} days**). The plan date {moved}. "
            "Weather is off by default and shown as warnings; switch it on in the sidebar. See Weather risk.")
elif choice == options[2]:
    single = risk_table[~risk_table["combined"]] if "combined" in risk_table else risk_table
    if single.empty or not R["risks"]["enabled"]:
        st.info("Common risks are switched off (sidebar, Advanced).")
    else:
        top = single.sort_values("p80_gain_if_removed", ascending=False).iloc[0]
        st.info(f"Removing **{top['short_name'].lower()}** (it happens in {top['probability']:.0%} of futures) "
                f"brings P80 first fire **{top['p80_gain_if_removed']:.0f} days** earlier. "
                "That is what mitigating it is worth. See Common risks.")

# ------------------------------------------------------------------ explore
st.subheader("Explore further")
links = [
    ("summary", "Summary", "one finding per page, in two minutes"),
    ("confidence", "Milestone confidence", "the curve and why the plan misses, by mechanism"),
    ("drivers", "What drives the date", "which chain of work decides first fire"),
    ("risks", "Common risks", "what each common risk costs"),
    ("recovery", "Win time back", "which proposals really win time, and at what cost"),
    ("reviews", "Reviews and latest dates", "how late a drawing, delivery or permit can be"),
    ("late_start", "Late-start cost", "a late start with and without weather"),
    ("weather", "Weather risk", "wind and rain warnings, a forced stoppage, spells"),
    ("assumptions", "Assumptions and sources", "where every number comes from"),
    ("guide", "Guide", "how to read everything, in English or Chinese"),
]
cols = st.columns(2)
for i, (key, title, what) in enumerate(links):
    with cols[i % 2]:
        st.page_link(PAGES[key], label=f"**{title}**: {what}")
