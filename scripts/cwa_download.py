"""
One-time, throttled download of CWA CODiS station reports for Locus.

資料來源：交通部中央氣象署 CODiS 氣候觀測資料查詢服務，依政府資料開放授權條款第 1 版使用。
Files written here are raw CWA data; every table derived from them is the
author's own processing and must be cited as such (see README, "Weather data").

What it downloads (the same request the CODiS web page makes)
    POST https://codis.cwa.gov.tw/api/station   (form-encoded, JSON response, no session needed)
        stn_ID    station id, e.g. 467050
        stn_type  cwb (staffed station) | auto_C0 (automatic weather station)
        type      report_month (one row per day) | report_date (one row per hour)
                  | report_year (one row per month, with CWA's own monthly counts)
        date, start, end
                  report_month: first day 00:00:00 to last day 00:00:00 of the month
                  report_date : the day 00:00:00 to 23:59:59
        more      empty

    The web page builds its CSV in the browser from that JSON. This script
    stores the JSON unchanged (lossless: quality flags, 10-minute maximum wind)
    and writes a CSV with the page's two header rows (Chinese, English) and the
    page's display rules (SpecialVal in CODiS global.js), for the columns Locus uses:
        null -> "--"; precipitation -9.8 -> "T" (trace), -9.5 -> "X" (fault),
        -999.9 -> "/"; other values below -90 by last digit: 1/5/9 -> "X",
        7 -> "/", 6 -> "&"; wind direction 999.9 -> "V"; one decimal place.
    Two extra columns come from the JSON only (not in the web CSV): the daily
    maximum 10-minute mean wind (WSMax10) and its time.

Politeness (CWA advises against automated retrieval; this is one small batch)
    - at least MIN_INTERVAL seconds between requests; cannot be lowered
    - retries with exponential backoff (2, 4, 8, 16 s), then the file is logged as failed
    - files already present and valid are skipped, so a rerun only fetches what is missing
    - every attempt is appended to download_log.csv

Usage
    python scripts/cwa_download.py monthly --station 467050 --start 2016-01 --end 2025-12
    python scripts/cwa_download.py hourly  --station 467050 --year 2024 --day 15
    python scripts/cwa_download.py yearly  --station 467050 --first-year 2016 --last-year 2025
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

API_URL = "https://codis.cwa.gov.tw/api/station"
MIN_INTERVAL = 2.0                     # seconds between requests (hard floor)
BACKOFF = (2, 4, 8, 16)                # seconds before each retry
USER_AGENT = "Locus-research/1.0 (one-time download for a schedule-risk demonstration)"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "raw" / "cwa"

# (English header, Chinese header, JSON path, display type)
MONTHLY_COLUMNS = [
    ("ObsTime", "觀測時間(day)", None, None),
    ("WS", "風速(m/s)", ("WindSpeed", "Mean"), "default"),
    ("WD", "風向(360degree)", ("WindDirection", "Prevailing"), "WindDirection"),
    ("WSGust", "最大瞬間風(m/s)", ("PeakGust", "Maximum"), "default"),
    ("WDGust", "最大瞬間風風向(360degree)", ("PeakGust", "Direction"), "WindDirection"),
    ("WGustTime", "最大瞬間風風速時間(LST)", ("PeakGust", "MaximumTime"), "time"),
    ("Precp", "降水量(mm)", ("Precipitation", "Accumulation"), "Precipitation"),
    ("PrecpHour", "降水時數(hour)", ("PrecipitationDuration", "Total"), "Precipitation"),
    ("WSMax10", "最大十分鐘風速(m/s)", ("WindSpeed", "TenMinutelyMaximum"), "default"),
    ("WSMax10Time", "最大十分鐘風速時間(LST)", ("WindSpeed", "TenMinutelyMaximumTime"), "time"),
]
HOURLY_COLUMNS = [
    ("ObsTime", "觀測時間(hour)", None, None),
    ("WS", "風速(m/s)", ("WindSpeed", "Mean"), "default"),
    ("WD", "風向(360degree)", ("WindDirection", "Mean"), "WindDirection"),
    ("WSGust", "最大瞬間風(m/s)", ("PeakGust", "Maximum"), "default"),
    ("WDGust", "最大瞬間風風向(360degree)", ("PeakGust", "Direction"), "WindDirection"),
    ("Precp", "降水量(mm)", ("Precipitation", "Accumulation"), "Precipitation"),
    ("PrecpHour", "降水時數(hour)", ("PrecipitationDuration", "Total"), "Precipitation"),
]
REQUIRED_HEADERS = ("ObsTime", "WS", "WSGust", "Precp")

_SPECIAL = {
    "Precipitation": {-9.8: "T", -9.5: "X", -999.9: "/"},
    "WindDirection": {999.9: "V"},
}
_LAST_DIGIT = {"1": "X", "5": "X", "9": "X", "7": "/", "6": "&"}
_PRECISION = {"default": 1, "WindDirection": 0, "Precipitation": 1}


class DownloadError(RuntimeError):
    """A request failed after every retry, or its response did not validate."""


# ------------------------------------------------------------------ display
def display_value(value, kind: str | None) -> str:
    """Render one JSON value the way the CODiS web table and CSV do (SpecialVal)."""
    if value is None or value == "":
        return "--"
    if kind == "time":
        return datetime.fromisoformat(str(value)).strftime("%Y/%m/%d %H:%M:%S")
    special = _SPECIAL.get(kind or "", {})
    if isinstance(value, (int, float)) and float(value) in special:
        return special[float(value)]
    if isinstance(value, (int, float)) and value < -90:
        mark = _LAST_DIGIT.get(str(value)[-1])
        if mark:
            return mark
    if not isinstance(value, (int, float)):
        return str(value)
    digits = _PRECISION.get(kind or "default", 1)
    # JavaScript Math.round(x * 10**d) / 10**d: halves round up (7.85 -> 7.9), unlike Python's format
    scaled = math.floor(float(value) * 10 ** digits + 0.5)
    return f"{scaled / 10 ** digits:.{digits}f}"


def _get(row: dict, path: tuple[str, str] | None):
    if path is None:
        return None
    block = row.get(path[0])
    return block.get(path[1]) if isinstance(block, dict) else None


def rows_to_csv(rows: list[dict], columns: list[tuple], time_key: str, hourly: bool, path: Path) -> int:
    """Write the two-header-row CSV (utf-8 with BOM, like the web download). Returns data rows."""
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        out = csv.writer(fh)
        out.writerow([c[1] for c in columns])
        out.writerow([c[0] for c in columns])
        for row in rows:
            stamp = datetime.fromisoformat(row[time_key])
            obs = (24 if stamp.hour == 23 and stamp.minute == 59 else stamp.hour) if hourly else stamp.day
            out.writerow([f"{obs:02d}" if c[2] is None else display_value(_get(row, c[2]), c[3])
                          for c in columns])
    return len(rows)


# ------------------------------------------------------------------ network
class Client:
    """Throttled POST client: never sends two requests less than MIN_INTERVAL apart."""

    def __init__(self, interval: float = MIN_INTERVAL):
        self.interval = max(float(interval), MIN_INTERVAL)
        self._last = 0.0

    def post(self, form: dict) -> dict:
        body = urllib.parse.urlencode(form).encode()
        last_error: Exception | None = None
        for attempt, wait in enumerate((0,) + BACKOFF):
            if wait:
                time.sleep(wait)
            pause = self.interval - (time.monotonic() - self._last)
            if pause > 0:
                time.sleep(pause)
            self._last = time.monotonic()
            req = urllib.request.Request(API_URL, data=body, method="POST",
                                         headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.load(resp)
                if data.get("code") != 200:
                    raise DownloadError(f"API code {data.get('code')}: {data.get('message')}")
                return data
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError,
                    DownloadError) as exc:
                last_error = exc
                print(f"  attempt {attempt + 1} failed: {exc}", file=sys.stderr)
        raise DownloadError(f"gave up after {len(BACKOFF) + 1} attempts: {last_error}")


def _form(stn: str, stn_type: str, kind: str, start: str, end: str) -> dict:
    return {"date": f"{start}.000+08:00", "type": kind, "stn_ID": stn, "stn_type": stn_type,
            "more": "", "start": start, "end": end}


def _rows(data: dict) -> list[dict]:
    blocks = data.get("data") or []
    return blocks[0].get("dts", []) if blocks else []


# ------------------------------------------------------------------ validation
def validate_csv(path: Path, expected_rows: int) -> None:
    """English header row holds ObsTime/WS/WSGust/Precp; data rows = expected (days or hours)."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        lines = list(csv.reader(fh))
    if len(lines) < 2:
        raise DownloadError(f"{path.name}: missing header rows")
    missing = [h for h in REQUIRED_HEADERS if h not in lines[1]]
    if missing:
        raise DownloadError(f"{path.name}: English header lacks {missing}")
    if len(lines) - 2 != expected_rows:
        raise DownloadError(f"{path.name}: {len(lines) - 2} data rows, expected {expected_rows}")


def _is_done(csv_path: Path, json_path: Path, expected: int) -> bool:
    if not (csv_path.exists() and json_path.exists()):
        return False
    try:
        validate_csv(csv_path, expected)
        return True
    except DownloadError:
        return False


def _log(log_path: Path, **entry) -> None:
    new = not log_path.exists()
    with open(log_path, "a", encoding="utf-8", newline="") as fh:
        out = csv.DictWriter(fh, fieldnames=["time", "station", "period", "kind", "status", "rows", "message"])
        if new:
            out.writeheader()
        out.writerow({"time": datetime.now().isoformat(timespec="seconds"), **entry})


# ------------------------------------------------------------------ jobs
def download_month(client: Client, stn: str, stn_type: str, year: int, month: int, out: Path) -> str:
    days = calendar.monthrange(year, month)[1]
    folder = out / stn
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{stn}-{year}-{month:02d}"
    csv_path, json_path = folder / f"{stem}.csv", folder / f"{stem}.json"
    if _is_done(csv_path, json_path, days):
        return "skipped"
    start, end = f"{year}-{month:02d}-01T00:00:00", f"{year}-{month:02d}-{days:02d}T00:00:00"
    data = client.post(_form(stn, stn_type, "report_month", start, end))
    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    rows_to_csv(_rows(data), MONTHLY_COLUMNS, "DataDate", False, csv_path)
    validate_csv(csv_path, days)
    return "ok"


def download_day(client: Client, stn: str, stn_type: str, day: date, out: Path) -> str:
    folder = out / stn / "hourly"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{stn}-{day:%Y-%m-%d}"
    csv_path, json_path = folder / f"{stem}.csv", folder / f"{stem}.json"
    if _is_done(csv_path, json_path, 24):
        return "skipped"
    start, end = f"{day:%Y-%m-%d}T00:00:00", f"{day:%Y-%m-%d}T23:59:59"
    data = client.post(_form(stn, stn_type, "report_date", start, end))
    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    rows_to_csv(_rows(data), HOURLY_COLUMNS, "DataTime", True, csv_path)
    validate_csv(csv_path, 24)
    return "ok"


def download_year(client: Client, stn: str, stn_type: str, year: int, out: Path) -> str:
    """Yearly report (one row per month): CWA's own monthly counts, used to cross-check derived tables."""
    folder = out / stn / "yearly"
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / f"{stn}-{year}.json"
    if json_path.exists() and len(_rows(json.loads(json_path.read_text(encoding="utf-8")))) == 12:
        return "skipped"
    data = client.post(_form(stn, stn_type, "report_year", f"{year}-01-01T00:00:00", f"{year}-12-31T00:00:00"))
    if len(_rows(data)) != 12:
        raise DownloadError(f"{stn} {year}: {len(_rows(data))} monthly rows, expected 12")
    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return "ok"


def _months(first: str, last: str):
    y, m = map(int, first.split("-"))
    y2, m2 = map(int, last.split("-"))
    while (y, m) <= (y2, m2):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("monthly", "hourly", "yearly"):
        p = sub.add_parser(mode)
        p.add_argument("--station", required=True)
        p.add_argument("--stn-type", default="cwb", choices=["cwb", "auto_C0"])
        p.add_argument("--out", type=Path, default=DEFAULT_OUT)
        p.add_argument("--interval", type=float, default=MIN_INTERVAL,
                       help=f"seconds between requests (at least {MIN_INTERVAL})")
        if mode == "monthly":
            p.add_argument("--start", required=True, help="YYYY-MM")
            p.add_argument("--end", required=True, help="YYYY-MM")
        elif mode == "yearly":
            p.add_argument("--first-year", type=int, required=True)
            p.add_argument("--last-year", type=int, required=True)
        else:
            p.add_argument("--year", type=int, required=True)
            p.add_argument("--day", type=int, default=15, help="day of each month")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    client, log_path = Client(args.interval), args.out / "download_log.csv"

    if args.mode == "monthly":
        jobs = [(f"{y}-{m:02d}", lambda y=y, m=m: download_month(client, args.station, args.stn_type, y, m, args.out))
                for y, m in _months(args.start, args.end)]
    elif args.mode == "yearly":
        jobs = [(str(y), lambda y=y: download_year(client, args.station, args.stn_type, y, args.out))
                for y in range(args.first_year, args.last_year + 1)]
    else:
        jobs = [(f"{args.year}-{m:02d}-{args.day:02d}",
                 lambda m=m: download_day(client, args.station, args.stn_type, date(args.year, m, args.day), args.out))
                for m in range(1, 13)]

    failures = 0
    for period, job in jobs:
        try:
            status = job()
            _log(log_path, station=args.station, period=period, kind=args.mode, status=status, rows="", message="")
            print(f"{args.station} {period}: {status}")
        except DownloadError as exc:
            failures += 1
            _log(log_path, station=args.station, period=period, kind=args.mode, status="failed", rows="",
                 message=str(exc))
            print(f"{args.station} {period}: FAILED ({exc})", file=sys.stderr)
    print(f"Done: {len(jobs) - failures} of {len(jobs)} files present; {failures} failed. Log: {log_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
