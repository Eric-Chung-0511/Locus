"""Reviews and latest dates: how late can deliveries arrive and submissions go in?"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from locus import analysis as A
from locus import labels as L
from views.shared import BLUE, LATE, MUTED, header, results, show, styled

R = results()
model, confidence = R["model"], R["confidence"]
lat = R["latest"].copy()

if lat.empty:
    header("Reviews and latest dates", "No external input or review feeds the milestone.", help_key="reviews")
else:
    worst = A.tightest_item(lat, model)
    if worst["margin_days"] < 0:
        headline = (f"{worst['short_name']} is {L.days_text(-worst['margin_days'])} past its latest "
                    f"acceptable date; {int((lat['margin_days'] < 0).sum())} of {len(lat)} items are already late.")
    else:
        headline = f"Every item has margin; the tightest, {worst['short_name']}, has {L.days_text(worst['margin_days'])}."
    header("Reviews and latest dates", headline, help_key="reviews")

    lat["label"] = lat["short_name"].map(L.cap)
    plot = lat.iloc[::-1]
    fig = go.Figure()
    for _, r in plot.iterrows():
        color = LATE if r["margin_days"] < 0 else BLUE
        fig.add_trace(go.Scatter(x=[r["reference"], r["latest_ok"]], y=[r["label"]] * 2, mode="lines",
                                 line=dict(color=color, width=3), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=plot["reference"], y=plot["label"], mode="markers", name="Planned or expected",
                             marker=dict(color=MUTED, size=10), customdata=plot[["name", "reference_basis"]],
                             hovertemplate="%{customdata[0]}<br>%{customdata[1]}: %{x|%Y-%m-%d}<extra></extra>"))
    fig.add_trace(go.Scatter(x=plot["latest_ok"], y=plot["label"], mode="markers", name="Latest acceptable",
                             marker=dict(color=BLUE, size=10, symbol="diamond"),
                             customdata=plot[["name", "margin_days"]],
                             hovertemplate="%{customdata[0]}<br>Latest acceptable %{x|%Y-%m-%d}"
                                           "<br>Margin %{customdata[1]} days<extra></extra>"))
    fig.update_yaxes(title=None, categoryorder="array", categoryarray=list(plot["label"]))
    fig.update_xaxes(tickformat="%b %Y")
    show(styled(fig, 150 + 30 * len(lat), legend=True))
    st.caption(f"Latest dates hold in {confidence:.0%} of simulated futures, with everything else as "
               "simulated. A red line means the plan or expectation is already later than the latest "
               "acceptable date.")
    starters = lat[lat["id"].map(lambda nid: model.nodes[nid].condition == "handover")]
    if not starters.empty and starters["margin_days"].min() < 0:
        st.caption(f"The site handover and the start-of-works approval start every path, so their margin "
                   f"({L.days_text(starters['margin_days'].min())}) is the whole plan's shortfall against the "
                   "target, not a late handover. With the target on the plan date, which few futures meet, "
                   "most items show red; set the target to a committed date (for example the P80 date) to "
                   "see the float each item really has.")

    with st.expander("Latest dates in detail"):
        st.dataframe(pd.DataFrame({
            "Item": lat["name"], "Kind": lat["kind"], "Rule": lat["rule"], "Measure": lat["measure"],
            "Compared with": lat["reference_basis"],
            "Planned or expected": pd.to_datetime(lat["reference"]).dt.strftime("%Y-%m-%d"),
            "Latest acceptable": pd.to_datetime(lat["latest_ok"]).dt.strftime("%Y-%m-%d"),
            "Margin (days)": lat["margin_days"],
            "P80 review time (days)": lat["p80_duration_days"].map(lambda v: "" if pd.isna(v) else f"{v:.0f}"),
            "Source grade": lat["source_grade"],
        }), hide_index=True)

with st.expander("Which reviews apply, and why"):
    st.dataframe(pd.DataFrame([{
        "Rule": r.rule_id, "Review": r.rule_name, "Applies to": r.asset_name,
        "Status": L.status_label(r.status),
        "In the model": "Yes" if r.gate_nodes else "Listed only",
        "Legal basis": r.legal_basis,
        "Process / duration grade": f"{r.process_grade} / {r.duration_grade}",
        "Note": r.note,
    } for r in model.register]), hide_index=True)
