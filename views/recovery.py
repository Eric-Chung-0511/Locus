"""Win time back: which proposals gain time, how often their link really drives, and what they cost."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from locus import labels as L
from views.shared import LINK_COLORS, header, pct, pts, results, show, styled

R = results()
rec = R["recovery"].copy()
single = rec[~rec["combined"]].copy()
combined = rec[rec["combined"]]

if single.empty:
    header("Win time back", "The plant file defines no breakable links to test.", help_key="recovery")
    st.stop()

best = single.iloc[0]
all_gain = combined["gain_p50_days"].iloc[0]
header("Win time back",
       f"The best single proposal gains {best['gain_p50_days']:.0f} days at P50; "
       f"all proposals together gain {all_gain:.0f}.", help_key="recovery")

m1, m2, m3 = st.columns(3)
m1.metric("All proposals together: P50 gain", f"{all_gain:.0f} days")
m2.metric("All proposals together: chance of meeting the target", pts(combined["delta_p_on_target"].iloc[0]))
m3.metric("Proposals with a measurable effect", f"{int(single['measurable'].sum())} of {len(single)}")

single["Link type"] = single["type"].map(L.link_type_label)
single["label"] = single["proposal"].map(L.cap)
single["Drives first fire today"] = single["on_driving_path"].map(pct)
single["Change in chance"] = single["delta_p_on_target"].map(pts)
single["Breaks the link"] = single["link"].str.replace(" -> ", " → ", regex=False)
single["bar_text"] = single.apply(lambda r: f"{r['gain_p50_days']:+.0f} d, {pts(r['delta_p_on_target'])}", axis=1)


def table(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Proposal": df["proposal"],
        "Drives first fire today": df["Drives first fire today"],
        "P50 gain (days)": df["gain_p50_days"],
        "Change in chance": df["Change in chance"],
        "Cost or risk": df["cost_or_risk"],
        "Breaks the link": df["Breaks the link"],
        "Change in logic": df["change"],
    })


useful = single[single["measurable"]]
if useful.empty:
    st.info("No single proposal has a measurable effect on first fire.")
else:
    plot = useful.iloc[::-1]
    fig = px.bar(plot, x="gain_p50_days", y="label", color="Link type", orientation="h",
                 color_discrete_map=LINK_COLORS, text="bar_text",
                 custom_data=["proposal", "Breaks the link", "Drives first fire today", "Change in chance",
                              "cost_or_risk"])
    fig.update_traces(textposition="outside", cliponaxis=False,
                      hovertemplate="<b>%{customdata[0]}</b><br>Breaks: %{customdata[1]}"
                                    "<br>Drives first fire today: %{customdata[2]}"
                                    "<br>P50 gain: %{x:.1f} days, chance %{customdata[3]}"
                                    "<br>Cost or risk: %{customdata[4]}<extra></extra>")
    # Leave room right of the longest bar for its text label.
    fig.update_xaxes(title="P50 gain (days)", range=[0, max(1.0, float(useful["gain_p50_days"].max())) * 1.3])
    fig.update_yaxes(title=None, categoryorder="array", categoryarray=list(plot["label"]))
    show(styled(fig, 130 + 52 * len(useful), legend=True, legend_title="Link type"))
    st.caption("Each proposal breaks one soft link and re-runs the same simulated futures, so the "
               "difference comes from the logic change alone. A proposal whose link rarely drives first "
               "fire gains little, because another path takes over.")
    st.dataframe(table(useful), hide_index=True)

rest = single[~single["measurable"]]
if not rest.empty:
    with st.expander(f"Tested, no measurable effect ({len(rest)})"):
        st.caption("These proposals change first fire by less than half a day at P50 and less than "
                   "0.1 percentage point in the chance of meeting the target. Their cost buys nothing today.")
        st.dataframe(table(rest), hide_index=True)
