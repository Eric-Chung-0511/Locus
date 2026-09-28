"""What drives the date: Criticality Index, with items that are always critical together merged."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from locus import labels as L
from views.shared import BLUE, CONDITION_COLORS, LINK_COLORS, header, pct, results, show, styled

R = results()
model, base, start = R["model"], R["base"], R["start"]
chains = R["chains"].copy()
_, link_on = base.driving_path()


@st.dialog("What this item waits for", width="large")
def inspect(members: list[str]) -> None:
    """Item inspector: source, duration and each predecessor with how often it drives."""
    for nid in members:
        node = model.nodes[nid]
        st.markdown(f"**{node.name}**  \n{node.group}. Source grade {node.source_grade}. "
                    f"{L.node_duration_text(node, start)}")
        if node.source_note:
            st.caption(node.source_note)
        rows = [{
            "Waits for": model.nodes[model.links[li].src].name,
            "Link type": L.link_type_label(model.links[li].type),
            "Logic": L.relation_label(model.links[li].rel, model.links[li].lag),
            "Drives it": pct(link_on[li].mean()),
            "Why": model.links[li].why,
        } for li in model.incoming[nid]]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True)
        else:
            st.caption("No predecessors: starts on its own date or arrives from outside the site.")


if chains.empty:
    header("What drives the date", "No item drives first fire in the simulated futures.", help_key="drivers")
    st.stop()

top = chains.iloc[0]
header("What drives the date",
       f"{L.plain_label(top['label'])} drives first fire in {pct(top['criticality'])} of futures.", help_key="drivers")

chains["Uncertainty type"] = chains["condition"].map(L.condition_label)
chains["Drives first fire"] = chains["criticality"].map(pct)
chains["hover_items"] = chains["members"].map(
    lambda ids: "<br>".join(L.wrap_hover(model.nodes[n].name) for n in ids))
plot = chains.iloc[::-1]
fig = px.bar(plot, x="criticality", y="label", color="Uncertainty type", orientation="h",
             color_discrete_map=CONDITION_COLORS,
             custom_data=["key", "hover_items", "Drives first fire", "Uncertainty type"])
fig.update_traces(hovertemplate="<b>%{customdata[1]}</b><br>Drives first fire in %{customdata[2]} "
                                "of futures<br>%{customdata[3]}<br><i>Click for details</i><extra></extra>")
fig.update_xaxes(tickformat=".0%", title="Share of futures in which this item drives first fire", range=[0, 1])
fig.update_yaxes(title=None, categoryorder="array", categoryarray=list(plot["label"]))
event = show(styled(fig, 470, legend=True, legend_title="Uncertainty type"),
             key="chain_chart", on_select="rerun", selection_mode="points")
st.caption("Items that are always on the driving path together (a series chain) share one row. "
           "Click a bar to see what the item waits for.")

# Open the inspector once per new click; the selection persists across reruns.
members_by_key = dict(zip(chains["key"], chains["members"]))
try:
    points = event.selection.points if event else []
    picked = points[0]["customdata"][0] if points else None
except (AttributeError, KeyError, IndexError, TypeError):
    picked = None
if picked is None:
    st.session_state["_inspected"] = None
elif picked != st.session_state.get("_inspected") and picked in members_by_key:
    st.session_state["_inspected"] = picked
    inspect(members_by_key[picked])

crit = R["crit"]
crit = crit[crit["id"] != model.milestone]
c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
choice = c1.selectbox("Inspect any item", list(crit["id"]), format_func=lambda nid: model.nodes[nid].name)
if c2.button("Show details", width="stretch"):
    inspect([choice])

st.markdown("**What the driving path is made of** (hatched: cannot be broken)")
mix = R["mix"].copy()
mix["Link type"] = mix["link_type"].map(L.link_type_label)
mix["Can it be broken?"] = np.where(mix["breakable"], "Yes", "No")
fig = px.bar(mix, x="share", y="Link type", color="Link type", orientation="h",
             color_discrete_map=LINK_COLORS, pattern_shape="Can it be broken?",
             pattern_shape_map={"Yes": "", "No": "/"},
             hover_data={"share": ":.0%", "Link type": False}, labels={"share": "Share"})
fig.update_xaxes(tickformat=".0%", title="Share of driving-path links")
fig.update_yaxes(title=None, categoryorder="total ascending")
show(styled(fig, 240))

with st.expander("Where the risk sits, by area and gate"):
    tree = crit.assign(size=crit["criticality"] + 0.01)
    fig = px.treemap(tree, path=["group", "short_name"], values="size", color="criticality",
                     color_continuous_scale=[[0, "#F1F5F9"], [1, BLUE]])
    fig.update_traces(hovertemplate="%{label}<br>Drives first fire in %{color:.0%} of futures<extra></extra>")
    fig.update_layout(coloraxis_showscale=False)
    show(styled(fig, 440))

with st.expander("Every item, one row each"):
    st.dataframe(pd.DataFrame({
        "Item": crit["name"], "Area or gate": crit["group"],
        "Uncertainty type": crit["condition"].map(L.condition_label),
        "Drives first fire": crit["criticality"].map(pct),
        "P80 finish": pd.to_datetime(crit["p80_finish"]).dt.strftime("%Y-%m-%d"),
        "Source grade": crit["source_grade"],
    }), hide_index=True)
