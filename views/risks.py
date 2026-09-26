"""Common risks: which risk that moves many items at once costs the most, and what is removing it worth?"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from locus import labels as L
from views.shared import BLUE, BLUE_LIGHT, days, header, pct, pts, results, show, styled

R = results()
RK = R["risks"]
table, full = RK["table"], RK["model"]

if table.empty:
    header("Common risks", "This plant file defines no common risks, so every duration varies independently.",
           help_key="risks")
    st.stop()

single = table[~table["combined"]]
total = table[table["combined"]].iloc[0]
top = single.iloc[0]
if RK["enabled"]:
    headline = (f"Common risks add {total['p80_gain_if_removed']:.0f} days to P80 first fire; "
                f"removing {top['short_name'].lower()} alone wins {top['p80_gain_if_removed']:.0f}.")
else:
    headline = (f"Common risks are switched off (Advanced). With them on, P80 first fire moves "
                f"{total['p80_gain_if_removed']:.0f} days later.")
header("Common risks", headline, help_key="risks")

k1, k2, k3 = st.columns(3)
k1.metric("P80 added by all common risks", f"{total['p80_gain_if_removed']:.0f} days")
k2.metric("P50 added by all common risks", f"{total['p50_gain_if_removed']:.0f} days")
k3.metric("Chance of target, change without them", pts(total["delta_p_if_removed"]))

# ------------------------------------------------------------------ chart
order = list(reversed(single["short_name"].tolist()))
fig = go.Figure()
fig.add_trace(go.Bar(y=single["short_name"], x=single["p80_added_alone"], orientation="h",
                     name="On its own (no other common risk)", marker_color=BLUE_LIGHT,
                     hovertemplate="%{y}<br>On its own: +%{x:.0f} days at P80<extra></extra>"))
fig.add_trace(go.Bar(y=single["short_name"], x=single["p80_gain_if_removed"], orientation="h",
                     name="Removed, with the others still in play", marker_color=BLUE,
                     hovertemplate="%{y}<br>Removing it: %{x:.0f} days earlier at P80<extra></extra>"))
fig.update_layout(barmode="group", bargap=0.3)
fig.update_yaxes(categoryorder="array", categoryarray=order)
fig.update_xaxes(title="Days of P80 first fire", rangemode="tozero")
fig = styled(fig, 120 + 70 * len(single), legend=True)
fig.update_layout(legend_traceorder="reversed")       # list the upper (dark) bar first
show(fig)
st.caption("Blue: how much earlier P80 first fire gets if this risk is eliminated and the others remain: "
           "what mitigating it is worth. Light blue: what it adds when it is the only common risk. "
           "They differ because risks interact: a delay costs only while its path drives first fire. "
           f"Neither column adds up to the total of {total['p80_gain_if_removed']:.0f} days.")

# ------------------------------------------------------------------ table
st.dataframe(pd.DataFrame({
    "Common risk": single["name"],
    "Applies to": single["n_items"].map(lambda n: f"{n} items"),
    "Chance it occurs": single["probability"].map(pct),
    "Size when it occurs": [L.risk_impact_text(e, i) for e, i in zip(single["effect"], single["impact"])],
    "P80 gain if removed (days)": single["p80_gain_if_removed"].map(days),
    "P50 gain if removed (days)": single["p50_gain_if_removed"].map(days),
    "Chance of target if removed": single["delta_p_if_removed"].map(pts),
    "P80 added on its own (days)": single["p80_added_alone"].map(days),
    "Source grade": single["source_grade"],
    "Source note": single["source_note"],
}), hide_index=True)

with st.expander("Which items each risk applies to"):
    for _, row in single.iterrows():
        names = [full.nodes[nid].name for nid in row["targets"]]
        st.markdown(f"**{row['short_name']}** ({len(names)} items): " + "; ".join(names))

st.caption("Every figure re-runs the same simulated futures with risks switched off or on, so differences "
           "come from the risks alone. Activity ranges should describe variation without these risks; "
           "otherwise the same risk is counted twice.")
