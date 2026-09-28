"""
Start here: the story for a first-time reader.

1. What is being simulated: a generic plant, its phases on a plain-language timeline.
2. What the plan says: the single-number date a typical schedule produces.
3. What the simulated futures say: the chance of that date, P50 and P80.
4. Where the delay comes from: the gap split by source (design, equipment,
   permits, ...), each measured by leaving it out on the same random numbers.
5. What the analysis supports: five actions, each with its evidence and trade-off.
6. What if: three precomputed comparisons.
Then how the numbers are checked, who built the tool, and links to every page.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

from locus import analysis as A
from locus import labels as L
from locus.weather import day_to_date
from views.shared import (BLUE, INK, PAGES, confidence_figure, futures_count, gap_figure, header, pct,
                          results, show, styled)

ABOUT = Path(__file__).resolve().parents[1] / "config" / "about.yaml"

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
       f"{L.days_text(contingency)} later.",
       help_key="start_here")

# --------------------------------------------------------------- 1. scenario
st.subheader("1. What is being simulated")
st.write(
    "A generic single-shaft combined-cycle power unit, built in Taiwan for a utility owner: a gas turbine (GT), "
    "a generator and a steam turbine on one shaft, with a heat recovery steam generator (HRSG) that turns the "
    "gas turbine's exhaust heat into steam. The main equipment comes from overseas makers. The simulation runs "
    "from the site handover and the start-of-works approval, through construction and equipment setting, to "
    "commissioning and the gas turbine's **first fire**, the first time it burns fuel. The plant, its durations "
    "and its risks are illustrative: this demonstrates a method, it is not a forecast of any real project. "
    "The commissioning gates (Gate 0, A, B, C) are the author's own simplified grouping of generic "
    "commissioning logic, not an industry or manufacturer standard.")


def phase_table() -> pd.DataFrame:
    """Plan span of each timeline phase (plant file `timeline`), or of each group without one."""
    spans: dict[str, tuple[float, float]] = {}
    for nid, (s_day, f_day) in R["plan_times"].items():
        g = model.nodes[nid].group
        lo, hi = spans.get(g, (s_day, f_day))
        spans[g] = (min(lo, s_day), max(hi, f_day))
    phases = model.timeline or [{"label": g, "groups": [g]} for g in (model.groups or list(spans))]
    rows, covered = [], set()
    for ph in phases:
        members = [g for g in ph["groups"] if g in spans]
        covered |= set(ph["groups"])
        if members:
            rows.append({"label": ph["label"], "start": min(spans[g][0] for g in members),
                         "finish": max(spans[g][1] for g in members), "groups": ", ".join(members)})
    for g, (a, b) in spans.items():                  # a group left out of the timeline still shows
        if g not in covered:
            rows.append({"label": g, "start": a, "finish": b, "groups": g})
    return pd.DataFrame(rows)


phases = phase_table()
to_date = lambda d: pd.Timestamp(day_to_date(start, d))
fig = go.Figure()
bars = phases[phases["finish"] > phases["start"]]
fig.add_trace(go.Bar(
    y=bars["label"], x=[(to_date(b) - to_date(a)).total_seconds() * 1000 for a, b in zip(bars["start"], bars["finish"])],
    base=[to_date(a) for a in bars["start"]], orientation="h", marker_color=BLUE,
    customdata=[[f"{to_date(a):%d %b %Y} to {to_date(b):%d %b %Y}", L.wrap_hover(g)]
                for a, b, g in zip(bars["start"], bars["finish"], bars["groups"])],
    hovertemplate="<b>%{y}</b><br>%{customdata[0]}<br>%{customdata[1]}<extra></extra>"))
points = phases[phases["finish"] <= phases["start"]]
if not points.empty:
    fig.add_trace(go.Scatter(y=points["label"], x=[to_date(a) for a in points["start"]], mode="markers",
                             marker=dict(symbol="diamond", size=12, color=INK),
                             hovertemplate="%{y}<br>%{x|%d %b %Y}<extra></extra>"))
milestone_x = to_date(S["plan_day"])
fig.add_shape(type="line", x0=milestone_x, x1=milestone_x, y0=0, y1=1, yref="paper",
              line=dict(color=INK, dash="dash", width=1.5))
fig.add_annotation(x=milestone_x, y=1.0, yref="paper", text="Planned first fire", showarrow=False,
                   xanchor="right", yanchor="bottom", font=dict(color=INK, size=12))
fig.update_yaxes(autorange="reversed", title=None, categoryorder="array", categoryarray=list(phases["label"]))
fig.update_xaxes(title=None, type="date", tickformat="%b %Y")
styled(fig, 90 + 32 * len(phases))
fig.update_layout(bargap=0.3, margin=dict(t=30), showlegend=False)
show(fig)
st.caption("The plan's phases in logical order, each from its first start to its last finish. Design starts "
           "before site work because drawings must be issued first. Commissioning starts at mechanical "
           "completion, once the turbine hall, the HRSG and the stack are built and their E&I is complete, "
           "and after power is received from the grid. Hover over a bar for what it includes.")

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
             "first fire be on average?** The last dark-blue bar is what they add on top when they happen together.")
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
             f"Tested delays are on: {', '.join(f'{model.nodes[k].short_name} +{L.days_text(v)}' for k, v in tested.items())}. ")
st.caption(zero_note + "Each bar is measured on the same random numbers, and the bars add up exactly to the "
           "simulated average. Hover over a bar for what it covers. The expert view, by mechanism "
           "(skewed durations, merge bias), is on Milestone confidence.")
with st.expander("What each bar means"):
    lines = ["| Source | Days | What it covers |", "|---|---:|---|"]
    for lab, d, t in zip(labels, gap_days["days"], texts):
        lines.append(f"| {lab} | {d:+d} | {t} |")
    st.markdown("\n".join(lines))

# ------------------------------------------------ 5. what the analysis supports
st.subheader("5. What the analysis supports")
st.write("Actions that follow from the numbers above, each with its evidence and what it costs. "
         "They change when the settings change.")
for i, fact in enumerate(R["actions"], start=1):
    title, evidence, trade_off = L.supported_action_text(fact)
    with st.container(border=True):
        st.markdown(f"**{i}. {title}**")
        st.write(evidence)
        st.caption(f"Trade-off: {trade_off}")
        if fact["page"] != "start":
            st.page_link(PAGES[fact["page"]], label="See the evidence")
st.caption("This shows the reasoning the method supports on an illustrative plant; decisions on a real "
           "project need its own schedule, ranges and risk register.")

# ------------------------------------------------------------------ 6. what if
st.subheader("6. What if...")
both = R["both_modes"]
risk_table = R["risks"]["table"]
options = ["Site start slips 4 weeks", "Weather is applied", "The costliest common risk is removed"]
choice = st.segmented_control("Try one", options, default=options[0])
if choice == options[0]:
    found = A.late_start_headline(both)
    if found:
        k, off_days, on_days = found
        st.info(f"If the site handover or the start-of-works approval slips {k} weeks, first fire (P50) moves "
                f"**{L.days_text(off_days)}** without weather and **{L.days_text(on_days)}** with recorded weather. "
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
                f"brings P80 first fire **{L.days_text(top['p80_gain_if_removed'])}** earlier. "
                "That is what mitigating it is worth. See Common risks.")

# ---------------------------------------------------------- how numbers are checked
st.subheader("How the numbers are checked")
checks = [
    "Every scenario is compared on the same random numbers, so a difference comes from the change, not from luck.",
    "An automated test suite checks the engine against exact answers: with nothing uncertain every simulated "
    "future equals the plan; a late start without weather never costs more than the delay itself; the split "
    "of the delay adds up exactly; commissioning never starts before power is received; every page renders.",
]
cross = next((p["value"] for p in (R["weather"].get("table") or {}).get("provenance") or []
              if p.get("item") == "Cross-check"), None)
if cross:
    checks.append(f"Weather statistics: {cross[0].lower() + cross[1:]}.")
checks.append("Every input carries a source grade (A law or official data, B public document, C assumption), "
              "listed on Assumptions and sources.")
st.markdown("\n".join(f"- {c}" for c in checks))

# ------------------------------------------------------------------ about
try:
    about = yaml.safe_load(ABOUT.read_text(encoding="utf-8")) or {}
except (OSError, yaml.YAMLError):
    about = {}
if about.get("name"):
    st.subheader("About")
    st.markdown(f"**{about['name']}** · {about.get('role', '')}")
    if about.get("summary"):
        st.write(str(about["summary"]).strip())
    about_links = [f"[{k}]({v})" for k, v in (about.get("links") or {}).items() if v]
    if about_links:
        st.markdown(" · ".join(about_links))

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
# One row per pair: on a phone the columns stack row by row, so the order holds;
# the description sits under the link, so nothing is cut off on a narrow screen.
for i in range(0, len(links), 2):
    for col, (key, title, what) in zip(st.columns(2), links[i:i + 2]):
        with col:
            st.page_link(PAGES[key], label=f"**{title}**")
            st.caption(what[0].upper() + what[1:] + ".")
