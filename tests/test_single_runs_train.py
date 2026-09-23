from datetime import UTC, date, datetime

import pandas as pd

from windagent.dump_single_runs_train import candidates, to_frame, window

VARS = (
    "wind_speed_100m",
    "wind_speed_80m",
    "wind_speed_10m",
    "wind_direction_100m",
    "wind_gusts_10m",
    "temperature_2m",
    "surface_pressure",
)


def response(run: datetime) -> dict:
    times = pd.date_range(run, periods=96, freq="h").strftime("%Y-%m-%dT%H:%M")
    hourly = {"time": list(times), **{name: [1.0] * 96 for name in VARS}}
    hourly["wind_gusts_10m"][0] = None
    units = {name: "m/s" for name in VARS if name != "wind_direction_100m"}
    return {"utc_offset_seconds": 0, "hourly_units": units, "hourly": hourly}


def test_dayahead_window_maps_to_convention_leads():
    start, end = window(date(2025, 1, 10))
    assert start == pd.Timestamp("2025-01-10T18:00", tz="UTC")
    assert end == pd.Timestamp("2025-01-12T17:00", tz="UTC")
    expected = {"06Z": (12, 59), "00Z": (18, 65), "18Z_prev": (24, 71)}
    for kind, run in candidates(date(2025, 1, 10)):
        frame = to_frame(run, response(run))
        leads = frame[frame.valid_utc.between(start, end)].lead_h
        assert (leads.min(), leads.max()) == expected[kind]
        assert len(leads) == 48


def test_fallback_runs_are_published_before_issue():
    lag = {0: 8, 6: 7, 18: 7}
    issue = datetime(2025, 1, 10, 18, tzinfo=UTC)
    for _, run in candidates(date(2025, 1, 10)):
        assert run + pd.Timedelta(hours=lag[run.hour]) <= issue
