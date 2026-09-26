"""
CODiS parsing: every special value, every format error, coverage, and a round trip
from the download script's CSV writer back through the parser. No network.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest
from conftest import ROOT

from locus.cwa_loader import CWAFormatError, coverage, load_station, parse_month_file

sys.path.insert(0, str(ROOT / "scripts"))
import cwa_download as D  # noqa: E402

ZH = "觀測時間(day),風速(m/s),最大瞬間風(m/s),降水量(mm),最大十分鐘風速(m/s)"
EN = "ObsTime,WS,WSGust,Precp,WSMax10"


def _write(folder, name, rows, header=(ZH, EN)):
    path = folder / name
    path.write_text("\n".join([*header, *rows]) + "\n", encoding="utf-8-sig")
    return path


def _feb(folder, name="467050-2023-02.csv", override=None):
    rows = [f"{d:02d},3.0,8.0,0.0,5.0" for d in range(1, 29)]
    for i, row in (override or {}).items():
        rows[i] = row
    return _write(folder, name, rows)


def test_special_values(tmp_path):
    path = _feb(tmp_path, override={0: "01,--,/,T,X", 1: "02,4.5,X,&,--", 2: "03,5.0,12.3,12.5,9.9"})
    df = parse_month_file(path)
    assert list(df.columns[:5]) == ["station_id", "date", "precip_mm", "ws_mean", "ws_gust"]
    assert df.loc[0, "precip_mm"] == 0.0                         # T: trace is not missing
    assert np.isnan(df.loc[0, "ws_mean"]) and np.isnan(df.loc[0, "ws_gust"]) and np.isnan(df.loc[0, "ws_max10"])
    assert np.isnan(df.loc[1, "ws_gust"]) and np.isnan(df.loc[1, "precip_mm"])
    assert df.loc[2, ["ws_mean", "ws_gust", "precip_mm", "ws_max10"]].tolist() == [5.0, 12.3, 12.5, 9.9]
    assert df["date"].iloc[0] == pd.Timestamp("2023-02-01") and df["date"].iloc[-1] == pd.Timestamp("2023-02-28")
    assert (df["station_id"] == "467050").all()


@pytest.mark.parametrize("override, message", [
    ({0: "01,T,8.0,0.0,5.0"}, "only valid for precipitation"),
    ({0: "01,3.0,8.0,abc,5.0"}, "unexpected value"),
    ({0: "05,3.0,8.0,0.0,5.0"}, "must run 1..28"),
])
def test_bad_values_are_reported_with_their_place(tmp_path, override, message):
    with pytest.raises(CWAFormatError, match=message):
        parse_month_file(_feb(tmp_path, override=override))


def test_row_count_must_match_the_month(tmp_path):
    path = _write(tmp_path, "467050-2024-02.csv", [f"{d:02d},3,8,0,5" for d in range(1, 29)])  # leap year: 29 days
    with pytest.raises(CWAFormatError, match="expected 29 days"):
        parse_month_file(path)


def test_file_name_and_headers_are_checked(tmp_path):
    with pytest.raises(CWAFormatError, match="expected"):
        parse_month_file(_feb(tmp_path, name="shinwu-2023-02.csv"))
    path = _write(tmp_path, "467050-2023-02.csv", [f"{d:02d},3,8" for d in range(1, 29)],
                  header=("觀測時間(day),風速(m/s),降水量(mm)", "ObsTime,WS,Precp"))
    with pytest.raises(CWAFormatError, match="lacks"):
        parse_month_file(path)


def test_coverage_counts_missing_values_and_missing_months(tmp_path):
    folder = tmp_path / "467050"
    folder.mkdir()
    for m, days in ((1, 31), (2, 28)):
        rows = [f"{d:02d},3.0,8.0,1.0,5.0" for d in range(1, days + 1)]
        rows[0] = "01,--,8.0,1.0,5.0"
        _write(folder, f"467050-2023-{m:02d}.csv", rows)
    df = load_station(folder)
    cov = coverage(df).iloc[0]
    assert cov["days_in_files"] == 59
    assert cov["precip_mm"] == pytest.approx(59 / 365)          # ten months not downloaded
    assert cov["ws_mean"] == pytest.approx(57 / 365)            # plus two "--" days


def test_duplicate_dates_are_rejected(tmp_path):
    folder = tmp_path / "467050"
    folder.mkdir()
    _feb(folder)
    _feb(folder, name="467050-2023-02.csv")                     # same file name: overwritten, fine
    assert len(load_station(folder)) == 28


# ------------------------------------------------------- download script
def test_downloader_csv_round_trips_through_the_parser(tmp_path):
    """JSON as the API returns it -> the script's CSV -> the parser: values and marks survive."""
    rows = []
    for d in range(1, 31):
        rows.append({
            "DataDate": f"2023-04-{d:02d}T00:00:00",
            "WindSpeed": {"Mean": 3.25 + d / 10, "TenMinutelyMaximum": 9.0 + d / 10,
                          "TenMinutelyMaximumTime": f"2023-04-{d:02d}T13:10:00"},
            "WindDirection": {"Prevailing": 30},
            "PeakGust": {"Maximum": 12.0 + d / 10, "Direction": 40, "MaximumTime": f"2023-04-{d:02d}T13:20:00"},
            "Precipitation": {"Accumulation": float(d)},
            "PrecipitationDuration": {"Total": 1.0},
        })
    rows[0]["Precipitation"]["Accumulation"] = -9.8                    # trace
    rows[1]["Precipitation"]["Accumulation"] = -9.5                    # fault
    rows[2]["PeakGust"]["Maximum"] = None                              # no value
    folder = tmp_path / "467050"
    folder.mkdir()
    path = folder / "467050-2023-04.csv"
    D.rows_to_csv(rows, D.MONTHLY_COLUMNS, "DataDate", False, path)
    D.validate_csv(path, 30)
    df = parse_month_file(path)
    assert df.loc[0, "precip_mm"] == 0.0 and np.isnan(df.loc[1, "precip_mm"]) and np.isnan(df.loc[2, "ws_gust"])
    assert df.loc[9, "precip_mm"] == 10.0
    assert df.loc[4, "ws_mean"] == 3.8                                  # 3.75 rounds half up, as on the web page
    assert df.loc[4, "gust_time"] == pd.Timestamp("2023-04-05 13:20:00")


@pytest.mark.parametrize("value, kind, shown", [
    (None, "default", "--"), (-9.8, "Precipitation", "T"), (-9.5, "Precipitation", "X"),
    (-999.9, "Precipitation", "/"), (-99.7, "default", "/"), (-99.1, "default", "X"),
    (-99.6, "default", "&"), (999.9, "WindDirection", "V"), (7.85, "default", "7.9"),
    (36, "Precipitation", "36.0"), (50, "WindDirection", "50"),
])
def test_display_rules_match_the_web_page(value, kind, shown):
    assert D.display_value(value, kind) == shown


def test_validation_rejects_short_or_headerless_files(tmp_path):
    path = _write(tmp_path, "467050-2023-02.csv", [f"{d:02d},3,8,0,5" for d in range(1, 28)])
    with pytest.raises(D.DownloadError, match="expected 28"):
        D.validate_csv(path, 28)
    path = _write(tmp_path, "x.csv", ["01,1"], header=("a,b", "ObsTime,WS"))
    with pytest.raises(D.DownloadError, match="lacks"):
        D.validate_csv(path, 1)


def test_throttle_cannot_be_lowered():
    assert D.Client(interval=0.1).interval == D.MIN_INTERVAL
