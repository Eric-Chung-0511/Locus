"""
Build a Locus weather table (config/weather_*.yaml) from CWA CODiS daily records.

資料來源：交通部中央氣象署 CODiS 氣候觀測資料查詢服務，依政府資料開放授權條款第 1 版使用。
The table is the author's processing of those records (thresholds, monthly
shares, spell lengths); it is not a CWA product and must be cited as such.

Input  data/raw/cwa/{station}/{station}-YYYY-MM.csv  (scripts/cwa_download.py)
       data/raw/cwa/{station}/hourly/*.json          (optional, for the gust factor)
Output one YAML file with, per calendar month:
    rain_by_threshold[T]     share and mean run of days with precipitation >= T mm
    wind_exceedance[T][r]    share and mean run of days whose maximum 10-minute
                             mean wind is >= T m/s, extended by r remobilisation
                             days after each one
for every threshold the app offers (RAIN_MM, WIND_MS, REMOBILISATION_DAYS), a
parameters block (default, options, source and verification status of every
setting) and a provenance block. Nothing in the table stops work by itself: the
app applies weather to the schedule only when the user switches it on.

Usage
    python scripts/build_weather_table.py --station 467050 --name "Xinwu 新屋" \
        --start 2016-01 --end 2025-12 --out config/weather_cwa_xinwu.yaml
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from locus.cwa_loader import coverage, load_station  # noqa: E402
from locus.weather_stats import extend_stoppage, gust_factor, monthly_spell_stats  # noqa: E402

# Threshold grid offered in the app (Streamlit Cloud has no raw data, so every
# option is computed here). Defaults are marked in PARAMETERS below.
RAIN_MM = (5, 10, 15, 20, 30)                  # daily precipitation, mm
WIND_MS = (8, 10, 12, 14, 16, 18, 20)          # daily maximum 10-minute mean wind, m/s
REMOBILISATION_DAYS = tuple(range(0, 11))      # days lost after each wind stop
P_MAX = 0.999                                  # cap on a monthly share of lost days (see _p_and_spells)
WORK_HOURS = (7, 18)          # [start, end) used to report when daily maxima happen
CITATION = ("資料來源：交通部中央氣象署 CODiS 氣候觀測資料查詢服務（測站：{name} {stn}，期間 {y0}–{y1}），"
            "依政府資料開放授權條款第 1 版使用，經作者加工計算。")


def _fmt(values, digits: int) -> str:
    return "[" + ", ".join(f"{float(v):.{digits}f}" for v in values) + "]"


def _p_and_spells(stats: pd.DataFrame) -> tuple[str, str]:
    """
    Rounded p (4 decimals) and spell lengths (3 decimals). Spell lengths are
    rounded UP to at least 1 / (1 - p) of the ROUNDED p, so the written pair
    always satisfies the model's check L >= 1 / (1 - p).
    """
    # p = 1 (no workable day in any year) would make the chain degenerate: cap it
    # just below 1, which in practice means "essentially never workable".
    p = np.minimum(np.round(stats["p"].to_numpy(dtype=float), 4), P_MAX)
    floor = 1.0 / (1.0 - p)
    L = stats["mean_spell_days"].to_numpy(dtype=float)
    L = np.where(np.isfinite(L), L, floor)          # p = 1 before the cap: no run ever ended
    L = np.maximum(L, floor)
    L = np.ceil(L * 1000 - 1e-9) / 1000
    return _fmt(p, 4), _fmt(L, 3)


def _hourly_sample(folder: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(glob.glob(str(folder / "hourly" / "*.json"))):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for r in (data.get("data") or [{}])[0].get("dts", []):
            rows.append({"ws": (r.get("WindSpeed") or {}).get("Mean"),
                         "gust": (r.get("PeakGust") or {}).get("Maximum")})
    return pd.DataFrame(rows, dtype=float)


def cross_check(s: pd.DataFrame, folder: Path) -> str:
    """
    Compare the monthly counts computed here with the counts in CWA's own yearly
    reports (days with rain >= 10 mm; days with 10-min maximum wind >= 10 m/s).
    """
    rows = []
    for path in sorted(glob.glob(str(folder / "*.json"))):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for r in (data.get("data") or [{}])[0].get("dts", []):
            rows.append({"month": pd.Timestamp(r["DataYearMonth"][:10]),
                         "cwa_rain": (r.get("Precipitation") or {}).get("GE10Days"),
                         "cwa_wind": (r.get("WindSpeed") or {}).get("TenMinutelyMaximumGE10Days")})
    if not rows:
        return "Not run (no CWA yearly reports in the raw folder)"
    cwa = pd.DataFrame(rows).set_index("month")
    mine = pd.DataFrame({"rain": (s["precip_mm"] >= 10).resample("MS").sum(),
                         "wind": (s["ws_max10"] >= 10).resample("MS").sum()})
    both = cwa.join(mine, how="inner").dropna()
    same = int(((both["cwa_rain"] == both["rain"]) & (both["cwa_wind"] == both["wind"])).sum())
    if same != len(both):
        bad = both[(both["cwa_rain"] != both["rain"]) | (both["cwa_wind"] != both["wind"])]
        print(f"Cross-check differences in {len(bad)} months:\n{bad}", file=sys.stderr)
    return (f"Monthly counts of days with rain >= 10 mm and with 10-min maximum wind >= 10 m/s match the CWA "
            f"yearly reports in {same} of {len(both)} months")


def _days(n: float) -> str:
    return f"{n:.0f} day{'' if round(n) == 1 else 's'}"


def build(station: str, name: str, start: str, end: str, raw: Path) -> tuple[str, dict]:
    df = load_station(raw / station)
    df = df[(df["date"] >= pd.Timestamp(start + "-01")) & (df["date"] < pd.Timestamp(end + "-01") + pd.offsets.MonthBegin())]
    s = df.set_index("date")
    y0, y1 = s.index.min().year, s.index.max().year
    first, last = f"{s.index.min():%Y-%m-%d}", f"{s.index.max():%Y-%m-%d}"
    if "ws_max10" not in s:
        raise SystemExit("The records have no maximum 10-minute wind (WSMax10); re-download with cwa_download.py")

    rain = {t: monthly_spell_stats((s["precip_mm"] >= t).where(s["precip_mm"].notna())) for t in RAIN_MM}
    windy = {t: (s["ws_max10"] >= t).where(s["ws_max10"].notna()) for t in WIND_MS}
    wind = {t: {r: monthly_spell_stats(extend_stoppage(windy[t], r)) for r in REMOBILISATION_DAYS} for t in WIND_MS}

    cov = coverage(df)
    hourly = _hourly_sample(raw / station)
    gf = gust_factor(hourly["ws"], hourly["gust"]) if not hourly.empty else None
    t10 = df["max10_time"].dropna()
    outside = ~t10.dt.hour.between(WORK_HOURS[0], WORK_HOURS[1] - 1)
    night_share = float(outside[df.loc[t10.index, "ws_max10"] >= 10].mean())
    raised = sum(int(r["raised"].sum()) for r in rain.values()) + sum(
        int(w[r]["raised"].sum()) for w in wind.values() for r in w)
    check = cross_check(s, raw / station / "yearly")
    n_years = ((s.index.max() - s.index.min()).days + 1) / 365.25
    per_year = {t: float(windy[t].sum() / n_years) for t in WIND_MS}
    rain_per_year = {t: float((s["precip_mm"] >= t).sum() / n_years) for t in RAIN_MM}
    cov_y = cov.set_index("year")
    stats = {"rain": rain, "wind": wind, "coverage": cov, "gust_factor": gf, "night_share": night_share,
             "first": first, "last": last, "raised": raised, "cross_check": check}

    label = f"{name} ({station})"
    citation = CITATION.format(name=name.split()[-1], stn=station, y0=y0, y1=y1)
    gust_src = (f"Estimated from {label} hourly data (15th of each month, 2024): median gust / hourly mean wind "
                f"over {gf[3]} hours with mean wind >= 3 m/s; interquartile range {gf[1]:.2f}-{gf[2]:.2f}"
                if gf else "No hourly sample")
    parameters = [
        # key, label, default, options, unit, source, status
        ("rain_mm", "Rain stoppage threshold", 10, list(RAIN_MM), "mm/day",
         f"Author's assumption for civil and outdoor work; {label}: {_days(rain_per_year[10])} a year at 10 mm",
         "Assumption, no standard cited"),
        ("wind_warning_ms", "Wind warning threshold", 10, list(WIND_MS), "m/s, 10-min mean",
         f"Author's working threshold; {label}: {_days(per_year[10])} a year at 10 m/s",
         "Legal basis pending verification"),
        ("wind_stop_ms", "Wind stoppage threshold", 16, list(WIND_MS), "m/s, 10-min mean",
         f"Author's working threshold; {label}: {_days(per_year[16])} a year at 16 m/s",
         "Legal basis pending verification"),
        ("stop_share", "Share of windy spells that stop work", 1.0, None, "share",
         "User setting: not every windy spell stops every lift", "Assumption"),
        ("remobilisation_days", "Remobilisation days after each wind stop", 1, list(REMOBILISATION_DAYS), "days",
         "Author's assumption: re-rigging, checks, crew back on the lift", "Assumption"),
        ("gust_factor", "Gust factor", round(gf[0], 2) if gf else 1.0, None, "gust / 10-min mean",
         gust_src, "Estimate; converts thresholds to gust values for display only"),
    ]
    provenance = [
        ("Source", f"CWA CODiS station reports (交通部中央氣象署 CODiS 氣候觀測資料查詢服務), station {label}"),
        ("Period", f"{first} to {last}, daily records"),
        ("Licence", "政府資料開放授權條款第 1 版 (Open Government Data License, version 1). Processed by the author; not a CWA product"),
        ("Coverage", f"Share of days with data, lowest year: precipitation {cov_y['precip_mm'].min():.1%}, "
                     f"maximum 10-min wind {cov_y['ws_max10'].min():.1%} (year {int(cov_y['ws_max10'].idxmin())}; "
                     "CWA station note: works 2020-01-01 to 2020-02-15)"),
        ("Rain", "Daily precipitation (Precp) at or above the rain threshold stops rain-sensitive (civil and outdoor) work that day"),
        ("Wind", "Daily maximum 10-minute mean wind (from the station's 10-minute records) at or above a threshold; "
                 "measured directly, not converted from gusts"),
        ("Time of daily maximum", f"On days with 10-min maximum >= 10 m/s, {night_share:.0%} had it outside "
                                  f"{WORK_HOURS[0]:02d}:00-{WORK_HOURS[1]:02d}:00 (upper bound on night-only exceedances)"),
        ("Anemometer height", "Station anemometer about 10 m above ground; wind at crane working height is stronger"),
        ("Cross-check", check),
    ]

    def q(text: str) -> str:
        return '"' + str(text).replace('"', "'") + '"'

    L = []
    L.append("# " + "=" * 77)
    L.append(f"# Weather table built from CWA CODiS daily records: {label}, {first} to {last}.")
    L.append("# GENERATED by scripts/build_weather_table.py. Do not edit by hand; rebuild instead.")
    L.append("#")
    L.append("# " + citation)
    L.append("# The monthly shares and spell lengths below are the author's processing, not CWA figures.")
    L.append("#")
    L.append("# rain_by_threshold[T]      share of days with precipitation >= T mm, and mean run of such days")
    L.append("# wind_exceedance[T][r]     share and mean run of days with maximum 10-minute mean wind >= T m/s,")
    L.append("#                           with r remobilisation days added after each one")
    L.append("# Monthly values Jan..Dec. Mean runs are rounded up so that L >= 1 / (1 - p). Shares are")
    L.append(f"# capped at {P_MAX} (a month with no workable day in any year).")
    L.append("# Nothing here stops work by itself: the app applies weather only when the user switches it on.")
    L.append("# " + "=" * 77)
    L.append("")
    L.append(f"display_name: {q(f'{label}, CWA CODiS {y0}-{y1}')}")
    L.append("is_illustrative: false")
    L.append(f"citation: {q(citation)}")
    L.append('disclaimer: "Simulation for demonstrating the method; not a forecast."')
    L.append("parameters:")
    for key, lab, default, options, unit, src, status in parameters:
        opts = "" if options is None else f", options: [{', '.join(str(o) for o in options)}]"
        L.append(f"  {key}: {{label: {q(lab)}, default: {default}{opts}, unit: {q(unit)},")
        L.append(f"    source: {q(src)},")
        L.append(f"    status: {q(status)}}}")
    L.append("provenance:")
    for item, value in provenance:
        L.append(f"  - {{item: {q(item)}, value: {q(value)}}}")
    L.append("stations:")
    L.append(f"  {q(label)}:")
    L.append("    rain_by_threshold:")
    for t in RAIN_MM:
        rp, rl = _p_and_spells(rain[t])
        L.append(f"      {t}: {{p: {rp},")
        L.append(f"          mean_spell_days: {rl}}}")
    L.append("    wind_exceedance:")
    for t in WIND_MS:
        L.append(f"      {t}:")
        for r in REMOBILISATION_DAYS:
            wp, wl = _p_and_spells(wind[t][r])
            L.append(f"        {r}: {{p: {wp},")
            L.append(f"            mean_spell_days: {wl}}}")
    return "\n".join(L) + "\n", stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--station", required=True)
    ap.add_argument("--name", required=True, help='display name, e.g. "Xinwu 新屋"')
    ap.add_argument("--start", required=True, help="YYYY-MM")
    ap.add_argument("--end", required=True, help="YYYY-MM")
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw" / "cwa")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    text, stats = build(args.station, args.name, args.start, args.end, args.raw)
    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote {args.out} ({stats['first']} to {stats['last']}).")
    print(stats["coverage"].round(3).to_string(index=False))
    print(stats["cross_check"])
    if stats["raised"]:
        print(f"Note: {stats['raised']} monthly spell lengths were raised to the independent-days value.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
