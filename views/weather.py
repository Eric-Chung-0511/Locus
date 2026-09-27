"""Weather risk: what if bad weather stops the site for a week, and does it matter that bad weather comes in spells?"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from locus import labels as L
from locus.weather import day_to_date, transition_probabilities
from views.shared import BLUE, BLUE_LIGHT, MUTED, days, header, pct, results, show, styled

R = results()
W, start = R["weather"], R["start"]
sweep, n = W["sweep"], W["stoppage_days"]

# ------------------------------------------------------------------ headline
if sweep.empty:
    headline = "No weather-sensitive work was found, so a stoppage cannot move first fire."
else:
    worst = sweep.sort_values(["p80_shift_days", "mean_shift_days"], ascending=False).iloc[0]
    if worst["p80_shift_days"] >= 1:
        headline = (f"A {n}-day stoppage costs most when it starts around {worst['first_date']:%d %b %Y}: "
                    f"P80 first fire moves {L.days_text(worst['p80_shift_days'])}.")
    else:
        headline = f"A {n}-day stoppage never moves P80 first fire by a whole day."
header("Weather risk", headline, help_key="weather")

# ------------------------------------------------------------ stoppage curve
if not sweep.empty:
    k1, k2, k3 = st.columns(3)
    k1.metric("Worst start date for the stoppage", f"{worst['first_date']:%Y-%m-%d}")
    k2.metric("Futures delayed at that date", pct(worst["share_delayed"]))
    k3.metric(f"Futures delayed by more than {n} days", pct(worst["share_more_than_window"]))

    hover = ("%{x|%d %b %Y}<br>%{y:.1f} days<br>"
             "Futures delayed: %{customdata[0]:.0%}<extra></extra>")
    custom = sweep[["share_delayed"]].to_numpy()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sweep["first_date"], y=[n] * len(sweep), mode="lines",
                             name=f"Stoppage passed through one-for-one ({n} days)",
                             line=dict(color=MUTED, dash="dot"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=sweep["first_date"], y=sweep["mean_shift_days"], mode="lines+markers",
                             name="Average first-fire shift", customdata=custom, hovertemplate=hover,
                             line=dict(color=BLUE_LIGHT, width=2.5)))
    fig.add_trace(go.Scatter(x=sweep["first_date"], y=sweep["p80_shift_days"], mode="lines+markers",
                             name="P80 first-fire shift", customdata=custom, hovertemplate=hover,
                             line=dict(color=BLUE, width=2.5, shape="hv")))
    fig.update_xaxes(title=f"First day of a {n}-day stoppage of all weather-sensitive work")
    fig.update_yaxes(title="First fire moves by (days)", rangemode="tozero")
    show(styled(fig, 440, legend=True))
    st.caption("Each point re-runs the same simulated futures with every weather-sensitive activity "
               f"stopped for {n} days from that date, on top of the simulated weather. Where the curve "
               "is near zero, the work running then has float; where it is near the dotted line, it "
               "drives first fire. Change the stoppage length under Advanced in the sidebar.")

    with st.expander("Every tested date"):
        table = pd.DataFrame({
            "Stoppage starts": sweep["first_date"].dt.strftime("%Y-%m-%d"),
            "P50 shift (days)": sweep["p50_shift_days"].map(days),
            "P80 shift (days)": sweep["p80_shift_days"].map(days),
            "Average shift (days)": sweep["mean_shift_days"].round(1),
            "Futures delayed": sweep["share_delayed"].map(pct),
            f"Delayed more than {n} days": sweep["share_more_than_window"].map(pct),
        })
        if "delta_p_on_target" in sweep:
            table["Change in chance of target"] = sweep["delta_p_on_target"].map(lambda v: f"{v * 100:+.1f} pts")
        st.dataframe(table, hide_index=True)

# ---------------------------------------------------------- weather warnings
warn = W.get("warnings")
if warn is not None and not warn.empty:
    cfg = W["settings"]
    st.subheader("Weather warnings for weather-sensitive work")
    (st.info if W["on"] else st.warning)(L.weather_mode_text(W["on"], cfg))
    rain = warn[warn["kind"] == "rain"]
    wind = warn[warn["kind"] == "wind"]
    window = lambda df: [f"{a:%Y-%m-%d} to {b:%Y-%m-%d}" for a, b in zip(df["p50_start"], df["p50_finish"])]
    if not wind.empty:
        st.markdown("**Wind-limited lifts**")
        st.dataframe(pd.DataFrame({
            "Activity": wind["name"], "P50 window": window(wind), "Days": wind["window_days"],
            "In north-east monsoon (Oct-Mar)": wind["monsoon_days"],
            f"Expected days ≥ {cfg['wind_warning_ms']:g} m/s (warning)": wind["days_warning"].round(0).astype(int),
            f"Expected days ≥ {cfg['wind_stop_ms']:g} m/s (stoppage)": wind["days_stop"].round(0).astype(int),
            "Note": wind["source_note"],
        }), hide_index=True)
    if not rain.empty:
        st.markdown("**Rain-sensitive civil and outdoor work**")
        st.dataframe(pd.DataFrame({
            "Activity": rain["name"], "P50 window": window(rain), "Days": rain["window_days"],
            f"Expected days with rain ≥ {cfg['rain_mm']:g} mm": rain["days_stop"].round(0).astype(int),
        }), hide_index=True)
    g = float(cfg["gust_factor"])
    st.caption(f"Expected days = the chance, for each calendar day of the P50 window, that the station record "
               f"reaches the threshold, added up (by calendar month). Wind is the daily maximum 10-minute mean at "
               f"the station anemometer, about 10 m above ground; wind at crane height is stronger. In gust terms "
               f"(factor {g:.2f}): {cfg['wind_warning_ms']:g} m/s ≈ {cfg['wind_warning_ms'] * g:.1f} m/s, "
               f"{cfg['wind_stop_ms']:g} m/s ≈ {cfg['wind_stop_ms'] * g:.1f} m/s. Rain stops civil and outdoor work "
               "only; indoor work continues once the envelope is closed (usual, not certain). Thresholds and their "
               "sources are listed on Assumptions and sources.")

# ----------------------------------------------------------------- spells
st.subheader("Does it matter that bad weather comes in spells?")
st.caption("This comparison always applies weather (with the rule under Weather parameters), whatever the switch "
           "is set to, because without weather there are no lost days to compare.")
compare = W["compare"]
first, last = W["exposed"]
if compare is None:
    st.info("This weather table has no spell lengths, so every day is drawn independently and a "
            "whole lost week is almost impossible. Add mean_spell_days to the table to model spells.")
else:
    ind, sp = compare[False], compare[True]
    span = (f"{day_to_date(start, first):%b %Y} to {day_to_date(start, last):%b %Y}")
    rain_ind = ind["spells"].set_index("kind").loc["rain"]
    rain_sp = sp["spells"].set_index("kind").loc["rain"]
    p80_change = sp["summary"]["p80_day"] - ind["summary"]["p80_day"]
    st.write(
        f"While weather-sensitive work runs ({span}), a week or more of consecutive rain days is lost in "
        f"{pct(rain_sp['share_with_run'])} of futures with spells, against {pct(rain_ind['share_with_run'])} "
        f"with independent days. The share of days lost is the same; spells regroup it into runs. "
        f"P80 first fire moves {p80_change:+.0f} days.")

    def column(entry: dict) -> list[str]:
        s, sp_ = entry["summary"], entry["spells"].set_index("kind")
        return [pct(sp_.loc["rain", "lost_share"]), pct(sp_.loc["rain", "share_with_run"]),
                f"{L.days_text(sp_.loc['rain', 'median_longest_run'])}",
                pct(sp_.loc["wind", "lost_share"]), pct(sp_.loc["wind", "share_with_run"]),
                f"{L.days_text(sp_.loc['wind', 'median_longest_run'])}",
                f"{s['p50_date']:%Y-%m-%d}", f"{s['p80_date']:%Y-%m-%d}", f"{s['p90_date']:%Y-%m-%d}"]

    used = " (used on every page)"
    st.dataframe(pd.DataFrame({
        "": ["Rain: share of days lost", "Rain: futures losing 7+ days in a row", "Rain: longest run, median",
             "Wind: share of days lost", "Wind: futures losing 7+ days in a row", "Wind: longest run, median",
             "P50 first fire", "P80 first fire", "P90 first fire"],
        "Independent days" + ("" if W["spells"] else used): column(ind),
        "Spells" + (used if W["spells"] else ""): column(sp),
    }), hide_index=True)
    st.caption("Both columns use the same random numbers; only the day-to-day dependence differs. "
               "When P80 barely moves, the long weather-sensitive activities average the spells out "
               "or have float; the stoppage curve above shows when a lost week does bite.")

with st.expander("Monthly weather table for this station"):
    stn = W["station"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    data = {"Month": months}
    spells = stn.get("mean_spell_days") or {}

    def add(label: str, p_values, spell_values) -> None:
        p = pd.Series(p_values, dtype=float)
        data[f"{label}: share of days"] = p.map(pct)
        if spell_values is not None:
            p11, _ = transition_probabilities(p.to_numpy(), spell_values)
            data[f"{label}: mean spell (days)"] = [f"{v:.1f}" for v in spell_values]
            data[f"{label}: after such a day"] = pd.Series(p11).map(pct)

    cfg = W.get("settings")
    if stn.get("rain") is not None:                                    # fixed stoppage table
        add("Rain stoppage", stn["rain"], spells.get("rain"))
        add("Wind stoppage", stn["wind"], spells.get("wind"))
    else:
        pick = lambda mapping, key: next(v for k, v in mapping.items() if float(k) == float(key))
        v = pick(stn["rain_by_threshold"], cfg["rain_mm"])
        add(f"Rain ≥ {cfg['rain_mm']:g} mm", v["p"], v["mean_spell_days"])
        for t in sorted({cfg["wind_stop_ms"], cfg["wind_warning_ms"]}, reverse=True):
            v = pick(stn["wind_exceedance"], t)[0]
            add(f"Wind ≥ {t:g} m/s", v["p"], v["mean_spell_days"])
    st.dataframe(pd.DataFrame(data), hide_index=True)
    st.caption("\"After such a day\" is the chance that a day qualifies when the day before did. With "
               "independent days it equals the share of days; the gap between the two is what makes spells. "
               "Columns follow the thresholds under Weather parameters; wind is the daily maximum 10-minute mean. "
               "They become lost days only when weather is applied to the schedule.")
