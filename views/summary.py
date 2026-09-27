"""Summary: the two-minute view. One finding per page, each one sentence plus one number."""

from __future__ import annotations

import streamlit as st

from locus import analysis as A
from locus import labels as L
from locus.model import HARD_LINK_TYPES
from views.shared import PAGES, how_to_read, pct, results, share_of_futures, status_line

R = results()
S, model = R["summary"], R["model"]

st.title("Locus")
st.subheader("Is the first-fire date trustworthy, what really drives it, "
             "and what can be done to win time back?")
status_line()
how_to_read("summary")


def card(title: str, sentence: str, page_key: str, link_label: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.write(sentence)
        st.page_link(PAGES[page_key], label=link_label)


cards = []

# What the analysis supports: the first two actions, worded as on Start here
acts = R.get("actions") or []
if acts:
    titles = [L.supported_action_text(f)[0] for f in acts[:2]]
    cards.append(("What does the analysis support?",
                  f"{titles[0]}." + (f" {titles[1]}." if len(titles) > 1 else "")
                  + f" {len(acts)} actions in all, each with its evidence and trade-off.",
                  "start", "See every action"))

# 0. The headline finding: a late start with and without weather (same random numbers)
found = A.late_start_headline(R["both_modes"])
if found:
    k, off_days, on_days = found
    cards.append((f"A {k}-week late start: without and with weather",
                  f"Without weather, first fire (P50) moves {L.days_text(off_days)}; with recorded "
                  f"weather it moves {L.days_text(on_days)}. "
                  "The gap is what weather adds to a late start.",
                  "late_start", "See both curves"))

# 1. Plan probability and contingency
contingency = S["p80_day"] - S["plan_day"]
gap_days = A.plan_gap_days(R["gap"])
largest = gap_days[gap_days["step"].isin(A.GAP_STEPS)].sort_values("days", ascending=False).iloc[0]
cards.append(("How likely is the plan date?",
              f"The single-number plan ({S['plan_date']:%d %b %Y}) holds in "
              f"{share_of_futures(S['p_on_plan'], R['base'].milestone_finish().size)}; the largest cause is "
              f"{L.plan_gap_phrase(largest['step'])} (+{largest['days']} days), and reaching P80 needs "
              f"{contingency:.0f} more days of contingency.",
              "confidence", "See why the plan misses"))

# 2. The chain that drives first fire
chains = R["chains"]
if not chains.empty:
    top = chains.iloc[0]
    mix = R["mix"]
    hard = float(mix.loc[mix["link_type"].isin(HARD_LINK_TYPES), "share"].sum())
    cards.append(("What drives the date?",
                  f"{L.plain_label(top['label'])} drives first fire in {pct(top['criticality'])} of futures; "
                  f"{pct(hard)} of the links on the driving path cannot be broken.",
                  "drivers", "See what drives the date"))

# 2b. Common risks
risk_table = R["risks"]["table"]
if not risk_table.empty:
    total = risk_table[risk_table["combined"]].iloc[0]
    top = risk_table[~risk_table["combined"]].iloc[0]
    state = "" if R["risks"]["enabled"] else " (switched off on the other pages)"
    cards.append((f"What do common risks cost?{state}",
                  f"Risks that slow many items at once add {L.days_text(total['p80_gain_if_removed'])} to P80 "
                  f"first fire; removing the costliest, {top['short_name'].lower()}, wins "
                  f"{L.days_text(top['p80_gain_if_removed'])} at P80.",
                  "risks", "See every common risk"))

# 3. Best proposal versus all proposals combined
rec = R["recovery"]
single = rec[~rec["combined"]]
combined = rec[rec["combined"]]
if not single.empty and not combined.empty:
    best = single.iloc[0]
    cards.append(("Can we win time back?",
                  f"The best single proposal, \"{best['proposal']}\", gains {L.days_text(best['gain_p50_days'])} "
                  f"at P50; all {len(single)} proposals together gain "
                  f"{L.days_text(combined['gain_p50_days'].iloc[0])}.",
                  "recovery", "See every proposal and its cost"))

# 4. The external input or review that is already latest
lat = R["latest"]
if not lat.empty:
    worst = A.tightest_item(lat, R["model"])
    if worst["margin_days"] < 0:
        text = (f"{worst['short_name']} is already {L.days_text(-worst['margin_days'])} past the latest date "
                f"that protects the target in {R['confidence']:.0%} of futures.")
    else:
        text = (f"Every external input and review has margin; the tightest, {worst['short_name']}, "
                f"has {L.days_text(worst['margin_days'])}.")
    cards.append(("What is already too late?", text, "reviews", "See latest dates"))

# 6. Forced weather stoppage
W = R["weather"]
sweep = W["sweep"]
if not sweep.empty:
    worst = sweep.sort_values(["p80_shift_days", "mean_shift_days"], ascending=False).iloc[0]
    quiet = int((sweep["p80_shift_days"] < 1).sum())
    tag = " (illustrative weather)" if R["illustrative"] else ""
    cards.append((f"What if bad weather stops the site?{tag}",
                  f"A {W['stoppage_days']}-day stoppage costs most from {worst['first_date']:%d %b %Y}, "
                  f"moving P80 first fire {L.days_text(worst['p80_shift_days'])}; at {quiet} of "
                  f"{len(sweep)} tested dates it moves P80 by less than a day.",
                  "weather", "See the weather stress test"))

# 7. Weather warnings: the activity most exposed, rain or wind
warn = W.get("warnings")
if warn is not None and not warn.empty:
    w = warn.copy()
    w["days"] = w["days_warning"].fillna(w["days_stop"])
    top = w.sort_values("days", ascending=False).iloc[0]
    what = (f"10-min wind of {W['settings']['wind_warning_ms']:g} m/s or more" if top["kind"] == "wind"
            else f"rain of {W['settings']['rain_mm']:g} mm or more")
    monsoon = (f" ({top['monsoon_days']} of its {top['window_days']} days in the north-east monsoon season)"
               if top["kind"] == "wind" and top["monsoon_days"] else "")
    cards.append(("Weather warnings",
                  f"{top['short_name']} runs {top['p50_start']:%b %Y} to {top['p50_finish']:%b %Y}{monsoon}; "
                  f"about {top['days']:.0f} of those days have {what}. "
                  + ("Weather is applied to the schedule." if W["on"]
                     else "Shown as a warning only: weather is not applied to the schedule."),
                  "weather", "See every warning"))

for row_start in range(0, len(cards), 3):
    cols = st.columns(3)
    for col, spec in zip(cols, cards[row_start:row_start + 3]):
        with col:
            card(*spec)
