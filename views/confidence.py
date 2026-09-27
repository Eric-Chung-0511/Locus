"""Milestone confidence: how likely is first fire on the plan date, and how much contingency is needed?"""

from __future__ import annotations

import streamlit as st

from locus import analysis as A
from locus import labels as L
from views.shared import (confidence_figure, futures_count, gap_figure, gap_table, header, lang, pct,
                          results, share_of_futures, show)

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

show(confidence_figure(base.milestone_finish(), S, start), toolbar=True)

st.caption("The single-number plan uses most-likely durations, deliveries on their planned day and average "
           "weather, the way a typical schedule does. Why it is optimistic, and by how much for each reason, "
           "is shown under Why the plan misses.")

# ------------------------------------------------------------- why the plan misses
st.subheader("Why the plan misses")
st.write(
    f"The single-number plan takes four best cases at once. Each bar removes one of them and shows how far "
    f"first fire moves; together they take the plan to the simulated average (+{mean_offset} days), and the "
    f"spread of outcomes adds the rest of the contingency up to P80 (+{contingency:.0f} days).")

order = list(gap_days["step"])
labels = [L.plan_gap_label(k, weather_applied) for k in order]
texts = [L.plan_gap_text(k, weather_applied) for k in order]
show(gap_figure(gap_days, labels, texts, start, S["plan_day"], set(A.GAP_STEPS)))
st.caption(
    "Dark blue: the four optimistic assumptions, removed one at a time in this order on the same random "
    "numbers, so they add up exactly. Grey: where first fire lands on average. Light blue: the spread up to "
    "P80. Near-black: the contingency needed. The steps interact, so another order would move a few days "
    "between them, never the total. The chain uses the average; P50 is "
    f"{S['p50_day'] - S['plan_day']:+.0f} days, close to it."
    + (" Common risks here is how far they move the average; the Common risks page reports how far they "
       "move P80, which is more because risks also widen the spread." if gap["has_risks"] else ""))

with st.expander("What each step means and what you can do about it"):
    gap_table(labels, gap_days, texts, [L.PLAN_GAP_STEPS[k].get("action", "") for k in order])
