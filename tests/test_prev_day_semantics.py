"""Empirical regression against committed, unmodified API responses."""

from unittest.mock import patch

import pytest

from windagent.dump_weather import to_frame
from windagent.tools.weather import ROOT, WeatherClient


@pytest.mark.parametrize("hour", [0, 6, 12, 18])
def test_previous_day1_matches_single_run(hour):
    with (
        WeatherClient(ROOT, cache_only=True) as client,
        patch(
            "requests.adapters.HTTPAdapter.send", side_effect=AssertionError("network")
        ),
    ):
        previous = client.previous_day()["hourly"]
        values = dict(
            zip(
                previous["time"], previous["wind_speed_100m_previous_day1"], strict=True
            )
        )
        run = f"2026-01-31T{hour:02}:00"
        frame = to_frame(run, client.single_run(run)).set_index("lead_h")
        for lead in range(24, 30):
            row = frame.loc[lead]
            assert row.wind_speed_100m == pytest.approx(
                values[row.valid_utc.strftime("%Y-%m-%dT%H:%M")], abs=1e-6, rel=0
            )
