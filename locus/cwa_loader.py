"""
Parser for CWA CODiS station reports saved by scripts/cwa_download.py.

資料來源：交通部中央氣象署 CODiS 氣候觀測資料查詢服務，依政府資料開放授權條款第 1 版使用。
Tables built from this module are the author's processing of that data, not CWA figures.

File layout
    data/raw/cwa/{station_id}/{station_id}-{YYYY}-{MM}.csv   one row per day
    ObsTime holds only the day of the month, so the year and month come from
    the file name.

Parsing rules
    - encoding utf-8-sig (the files start with a byte-order mark)
    - two header rows: Chinese first, English second; the English row is used
    - "--" (no value), "/" (unknown), "X" (instrument fault) and "&" (amount
      accumulated into a later reading) -> NaN
    - "T" in precipitation (trace, under 0.1 mm) -> 0.0: it rained, too little
      to measure, which is not missing data
    - any other text that is not a number raises CWAFormatError naming the
      file, row and column, so a format change never passes silently
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

MISSING_MARKS = frozenset({"--", "/", "X", "&"})
TRACE_MARK = "T"
FILE_PATTERN = re.compile(r"^(?P<stn>[0-9A-Z]+)-(?P<year>\d{4})-(?P<month>\d{2})\.csv$")

# English header -> tidy column. WSMax10 is only in files written by cwa_download.py
# (taken from the API JSON), so it is optional.
COLUMNS = {"Precp": "precip_mm", "WS": "ws_mean", "WSGust": "ws_gust", "WSMax10": "ws_max10"}
REQUIRED = ("ObsTime", "Precp", "WS", "WSGust")
TIME_COLUMNS = {"WGustTime": "gust_time", "WSMax10Time": "max10_time"}


class CWAFormatError(ValueError):
    """A CODiS file does not have the expected name, headers, rows or values."""


def _to_number(text: str, precip: bool, where: str) -> float:
    text = str(text).strip()
    if text in MISSING_MARKS or text == "":
        return np.nan
    if text == TRACE_MARK:
        if precip:
            return 0.0
        raise CWAFormatError(f"{where}: 'T' (trace) is only valid for precipitation")
    try:
        return float(text)
    except ValueError as exc:
        raise CWAFormatError(f"{where}: unexpected value {text!r}") from exc


def parse_month_file(path: str | Path) -> pd.DataFrame:
    """
    One monthly report (daily rows) -> tidy DataFrame with columns
    station_id, date, precip_mm, ws_mean, ws_gust [, ws_max10, gust_time, max10_time].
    """
    path = Path(path)
    m = FILE_PATTERN.match(path.name)
    if not m:
        raise CWAFormatError(f"{path.name}: expected {{station_id}}-{{YYYY}}-{{MM}}.csv")
    stn, year, month = m["stn"], int(m["year"]), int(m["month"])
    raw = pd.read_csv(path, encoding="utf-8-sig", header=None, dtype=str, keep_default_na=False)
    if len(raw) < 2:
        raise CWAFormatError(f"{path.name}: missing the two header rows")
    header = [h.strip() for h in raw.iloc[1]]                 # row 0 Chinese, row 1 English
    missing = [h for h in REQUIRED if h not in header]
    if missing:
        raise CWAFormatError(f"{path.name}: English header row lacks {missing}")
    body = raw.iloc[2:].reset_index(drop=True)
    body.columns = header

    days = calendar.monthrange(year, month)[1]
    if len(body) != days:
        raise CWAFormatError(f"{path.name}: {len(body)} rows, expected {days} days")
    try:
        day = body["ObsTime"].astype(int)
    except ValueError as exc:
        raise CWAFormatError(f"{path.name}: ObsTime must hold day numbers") from exc
    if list(day) != list(range(1, days + 1)):
        raise CWAFormatError(f"{path.name}: ObsTime must run 1..{days} in order")

    out = pd.DataFrame({"station_id": stn,
                        "date": pd.to_datetime([date(year, month, d) for d in day])})
    for src, dst in COLUMNS.items():
        if src not in body:
            continue
        out[dst] = [_to_number(v, src == "Precp", f"{path.name} row {i + 1} {src}")
                    for i, v in enumerate(body[src])]
    for src, dst in TIME_COLUMNS.items():
        if src in body:
            out[dst] = pd.to_datetime(body[src].where(~body[src].isin(MISSING_MARKS)),
                                      format="%Y/%m/%d %H:%M:%S", errors="coerce")
    return out


def load_station(folder: str | Path) -> pd.DataFrame:
    """Every monthly file of one station, in date order, with duplicate dates rejected."""
    files = sorted(p for p in Path(folder).glob("*.csv") if FILE_PATTERN.match(p.name))
    if not files:
        raise CWAFormatError(f"No monthly report files in {folder}")
    df = pd.concat([parse_month_file(p) for p in files], ignore_index=True)
    dup = df.duplicated(["station_id", "date"])
    if dup.any():
        raise CWAFormatError(f"{folder}: duplicate dates, e.g. {df.loc[dup, 'date'].iloc[0]:%Y-%m-%d}")
    return df.sort_values(["station_id", "date"], ignore_index=True)


def coverage(df: pd.DataFrame) -> pd.DataFrame:
    """
    Share of calendar days with a value, per station-year and variable.
    Days absent from the files count as missing, so a lost month shows up too.
    """
    rows = []
    value_cols = [c for c in ("precip_mm", "ws_mean", "ws_gust", "ws_max10") if c in df]
    for (stn, year), g in df.groupby([df["station_id"], df["date"].dt.year]):
        n_days = 366 if calendar.isleap(year) else 365
        row = {"station_id": stn, "year": int(year), "days_in_files": len(g)}
        for c in value_cols:
            row[c] = g[c].notna().sum() / n_days
        rows.append(row)
    return pd.DataFrame(rows)
