"""Late-start cost: with and without weather, does a late site start pass through to first fire one-for-one?"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from locus import analysis as A
from locus import labels as L
from views.shared import BLUE, MUTED, header, results, show, styled


R = results()
both, W = R["both_modes"], R["weather"]
station = W.get("station_name", "station")
found = A.late_start_headline(both)
if found:
    k, off_days, on_days = found
    headline = (f"Starting {k} weeks late moves P50 first fire by {off_days:.0f} days without weather "
                f"and by {on_days:.0f} days with the {station} weather.")
else:
    headline = "No late start was tested."
header("Late-start cost", headline, help_key="late_start")

off, on = both[False]["season"], both[True]["season"]
fig = go.Figure()
fig.add_trace(go.Scatter(x=off["start_delay_days"], y=off["start_delay_days"], mode="lines",
                         name="Delay passed through one-for-one", line=dict(color="#C9CED4", dash="dot")))
for df, name, color in ((off, "without weather", MUTED), (on, "with weather", BLUE)):
    fig.add_trace(go.Scatter(x=df["start_delay_days"], y=df["p50_shift_days"], mode="lines+markers",
                             name=f"P50, {name}", line=dict(color=color, width=2.5)))
    fig.add_trace(go.Scatter(x=df["start_delay_days"], y=df["p80_shift_days"], mode="lines+markers",
                             name=f"P80, {name}", line=dict(color=color, width=1.5, dash="dash")))
fig.update_xaxes(title="Site start delayed by (days); deliveries and calendar unchanged")
fig.update_yaxes(title="First fire moves by (days)")
show(styled(fig, 460, legend=True))
st.caption("Both sets of lines re-run the same simulated futures; the only difference is whether weather is "
           "applied. Without weather, a late start can never cost more than the delay itself (float can only "
           "absorb it); with weather, a delay that pushes civil work or lifts into a worse season can cost more. "
           "The weather lines use the rule under Weather parameters, whatever the switch is set to: "
           + L.weather_mode_text(True, W.get("settings")))

with st.expander("Every tested delay"):
    st.dataframe(pd.DataFrame({
        "Site start delayed by (weeks)": off["start_delay_weeks"],
        "P50 shift without weather (days)": off["p50_shift_days"].round(0).astype(int),
        "P50 shift with weather (days)": on["p50_shift_days"].round(0).astype(int),
        "P80 shift without weather (days)": off["p80_shift_days"].round(0).astype(int),
        "P80 shift with weather (days)": on["p80_shift_days"].round(0).astype(int),
    }), hide_index=True)
