"""Assumptions and sources: where does every number come from?"""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from locus import labels as L
from locus.model import HARD_LINK_TYPES
from views.shared import header, results

R = results()
model, base, start = R["model"], R["base"], R["start"]

# Rule-created items carry "process/duration" grades. The headline counts the
# grade of the number the simulation uses (the duration grade), and separately
# how many reviews rest on law text for their process.
grades = Counter(n.source_grade.split("/")[-1] for n in model.nodes.values())
grade_text = ", ".join(f"{grades[g]} grade {g}" for g in sorted(grades))
law_based = sum(1 for n in model.nodes.values() if n.rule_id and n.source_grade.startswith("A/"))
header("Assumptions and sources",
       f"All {len(model.nodes)} items state a source for their duration or arrival: {grade_text}; "
       f"{law_based} reviews follow a process taken from law text.", help_key="assumptions")
st.caption("A: law text or official data. B: industry or public documents. C: explicit assumption or "
           "practitioner estimate. Items added by a rule show two grades: process / duration. "
           "Weather-sensitive durations are working days.")

st.dataframe(pd.DataFrame([{
    "Item": n.name, "Area or gate": n.group,
    "Uncertainty type": L.condition_label(n.condition),
    "Weather-sensitive": L.weather_label(n.weather),
    "Duration or arrival": L.node_duration_text(n, start),
    "Source grade": n.source_grade, "Source note": n.source_note,
    "Added by": f"Rule {n.rule_id}" if n.rule_id else "Plant file",
} for n in model.nodes.values()]), hide_index=True, height=420)

W = R["weather"]
weather_src = W.get("table") or {}
cfg, pars = W.get("settings"), W.get("parameters") or {}
if cfg and pars:
    st.subheader("Weather parameters: value, source and verification status")
    st.caption(L.weather_mode_text(W["on"], cfg))
    g = float(cfg["gust_factor"])
    shown = {
        "rain_mm": f"{cfg['rain_mm']:g} mm/day",
        "wind_warning_ms": f"{cfg['wind_warning_ms']:g} m/s (≈ gust {cfg['wind_warning_ms'] * g:.1f} m/s)",
        "wind_stop_ms": f"{cfg['wind_stop_ms']:g} m/s (≈ gust {cfg['wind_stop_ms'] * g:.1f} m/s)",
        "stop_share": f"{float(cfg['stop_share']):.0%}",
        "remobilisation_days": f"{int(cfg['remobilisation_days'])} day{'' if int(cfg['remobilisation_days']) == 1 else 's'}",
        "gust_factor": f"{g:.2f}",
    }
    rows = [{"Parameter": "Apply weather to the schedule", "Value used": "On" if W["on"] else "Off (warnings only)",
             "Default": "Off", "Source": "Author's design: weather is a warning unless the user switches it on",
             "Verification status": "Design choice"}]
    for key, value in shown.items():
        spec = pars.get(key, {})
        default = spec.get("default")
        unit = spec.get("unit", "")
        rows.append({"Parameter": spec.get("label", key), "Value used": value,
                     "Default": (f"{float(default):.0%}" if key == "stop_share" else f"{default:g} {unit}".strip())
                     if default is not None else "",
                     "Source": spec.get("source", ""), "Verification status": spec.get("status", "")})
    st.dataframe(pd.DataFrame(rows), hide_index=True)

if weather_src.get("provenance"):
    with st.expander("Weather data source", expanded=True):
        st.dataframe(pd.DataFrame([{"Item": r["item"], "Detail": r["value"]} for r in weather_src["provenance"]]),
                     hide_index=True)
        st.caption(" ".join(x for x in (weather_src.get("citation"), weather_src.get("disclaimer")) if x))

with st.expander(f"Links ({len(model.links)})"):
    st.dataframe(pd.DataFrame([{
        "From": model.nodes[l.src].name, "To": model.nodes[l.dst].name,
        "Logic": L.relation_label(l.rel, l.lag),
        "Link type": L.link_type_label(l.type),
        "Can it be broken?": "No" if l.type in HARD_LINK_TYPES else "Yes",
        "Proposal if broken": (l.relax or {}).get("proposal", ""),
        "Why": l.why, "Defined in": L.origin_label(l.origin),
    } for l in model.links]), hide_index=True)

risks = R["risks"]["model"].risks
if risks:
    with st.expander(f"Common risks ({len(risks)})" + ("" if R["risks"]["enabled"] else ", switched off")):
        st.dataframe(pd.DataFrame([{
            "Common risk": r.name, "Chance it occurs": f"{r.probability:.0%}",
            "Size when it occurs": L.risk_impact_text(r.effect, r.impact),
            "Applies to": f"{len(r.targets)} items",
            "Source grade": r.source_grade, "Source note": r.source_note,
        } for r in risks]), hide_index=True)

if base.overflow_count:
    st.caption(f"{base.overflow_count} weather calculations ran past the simulation horizon.")
