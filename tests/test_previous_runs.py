from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
import responses

from windagent.dump_previous_runs import model_variables, normalize
from windagent.tools.weather import (
    PREVIOUS_URL,
    CacheMissError,
    WeatherClient,
    previous_variable_names,
    site_coordinates,
)


def api_response(start: date, days: int) -> dict:
    times = [
        (datetime.combine(start, datetime.min.time()) + timedelta(hours=h)).strftime(
            "%Y-%m-%dT%H:%M"
        )
        for h in range(days * 24)
    ]
    return {
        "utc_offset_seconds": 0,
        "latitude": 43.625,
        "longitude": 78.5,
        "hourly_units": {
            "wind_speed_100m_previous_day1": "m/s",
            "wind_speed_100m_previous_day2": "m/s",
        },
        "hourly": {
            "time": times,
            "wind_speed_100m_previous_day1": [3.0] * len(times),
            "wind_speed_100m_previous_day2": [4.0] * len(times),
        },
    }


def test_model_and_site_validation():
    assert site_coordinates("T2") == (43.643198, 78.538828)
    with pytest.raises(ValueError, match="Unknown site_id"):
        site_coordinates("../../secret")
    with pytest.raises(ValueError, match="Unsupported Previous Runs model"):
        previous_variable_names("best_match", ("ws100",))
    with pytest.raises(ValueError, match="unavailable"):
        previous_variable_names("ecmwf_ifs025", ("ws80",))
    assert "gusts" not in model_variables("ecmwf_ifs")
    assert "gusts" in model_variables("icon_global")
    assert "ws80" not in model_variables("ecmwf_aifs025_single")


@responses.activate
def test_15_days_split_into_two_requests_and_rebuild_offline(tmp_path):
    responses.get(PREVIOUS_URL, json=api_response(date(2026, 2, 1), 14))
    responses.get(PREVIOUS_URL, json=api_response(date(2026, 2, 15), 1))
    with WeatherClient(tmp_path) as client:
        frame = client.previous_runs(
            "icon_global", "2026-02-01", "2026-02-15", ("ws100",), site_id="T2"
        )
        assert len(frame) == 15 * 24
        assert client.network_attempts == 2
        assert frame.valid_utc.is_unique
        assert "latitude=43.643198" in responses.calls[0].request.url
        assert "wind_speed_unit=ms" in responses.calls[0].request.url
    with (
        WeatherClient(tmp_path, cache_only=True) as client,
        patch(
            "requests.adapters.HTTPAdapter.send", side_effect=AssertionError("network")
        ),
    ):
        again = client.previous_runs(
            "icon_global", "2026-02-01", "2026-02-15", ("ws100",), site_id="T2"
        )
        pd.testing.assert_frame_equal(again, frame)
        assert client.network_attempts == 0
    normalized = normalize("icon_global", frame)
    assert normalized["wind_speed_80m_previous_day1"].isna().all()


def test_previous_cache_miss_mentions_key(tmp_path):
    with WeatherClient(tmp_path, cache_only=True) as client:
        with pytest.raises(CacheMissError, match="key=.*artifact="):
            client.previous_runs("icon_global", "2026-02-01", "2026-02-01", ("ws100",))


@pytest.mark.parametrize(
    ("model", "start", "end"),
    [
        ("icon_global", "2026-03-01", "2026-02-01"),
        ("icon_global", "2026-02-01T01:00", "2026-02-02"),
        ("ecmwf_ifs", "2025-09-30", "2025-10-01"),
    ],
)
def test_invalid_date_ranges_rejected(tmp_path, model, start, end):
    with WeatherClient(tmp_path, cache_only=True) as client:
        with pytest.raises(ValueError):
            client.previous_runs(model, start, end, ("ws100",))
