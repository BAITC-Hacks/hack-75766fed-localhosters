import json
import shutil
from unittest.mock import patch

import pytest
import requests
import responses

from windagent.tools.weather import (
    ROOT,
    SINGLE_URL,
    CacheMissError,
    WeatherClient,
    request_key,
    run_datetime,
)

PAYLOAD = {"hourly": {"time": []}, "latitude": 43, "longitude": 78}


def test_cache_only_miss_never_uses_network(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_METEO_CACHE_ONLY", "1")
    with (
        WeatherClient(tmp_path) as client,
        patch(
            "requests.adapters.HTTPAdapter.send", side_effect=AssertionError("network")
        ),
    ):
        with pytest.raises(CacheMissError, match="key=.*artifact="):
            client.single_run("2026-01-31T00:00")
        assert client.network_attempts == 0


@responses.activate
def test_retries_and_portable_cache(tmp_path):
    responses.get(SINGLE_URL, status=429, headers={"Retry-After": "0"})
    responses.get(SINGLE_URL, status=503)
    responses.get(SINGLE_URL, json=PAYLOAD)
    with WeatherClient(tmp_path) as client, patch("time.sleep") as sleep:
        assert client.single_run("2026-01-31T00:00") == PAYLOAD
        assert client.network_attempts == 3
        assert sleep.call_count == 2
        assert "wind_speed_unit=ms" in responses.calls[-1].request.url
        assert "timezone=UTC" in responses.calls[-1].request.url
    # Reproduce a fresh checkout: only versioned JSON, no SQLite cache.
    destination = tmp_path / "fresh"
    shutil.copytree(tmp_path / "data", destination / "data")
    with (
        WeatherClient(destination, cache_only=True) as client,
        patch(
            "requests.adapters.HTTPAdapter.send", side_effect=AssertionError("network")
        ),
    ):
        assert client.single_run("2026-01-31T00:00") == PAYLOAD
        assert client.network_attempts == 0


@responses.activate
def test_http_cache_alone_supports_offline(tmp_path):
    responses.get(SINGLE_URL, json=PAYLOAD)
    with WeatherClient(tmp_path) as client:
        client.single_run("2026-01-31T00:00")
    shutil.rmtree(tmp_path / "data")
    with WeatherClient(tmp_path, cache_only=True) as client:
        assert client.single_run("2026-01-31T00:00") == PAYLOAD
        assert client.network_attempts == 0
    assert len(responses.calls) == 1


@responses.activate
def test_permanent_http_error_is_not_retried(tmp_path):
    responses.get(SINGLE_URL, status=400)
    with WeatherClient(tmp_path) as client:
        with pytest.raises(requests.HTTPError):
            client.single_run("2026-01-31T00:00")
        assert client.network_attempts == 1


@responses.activate
def test_retry_budget(tmp_path):
    responses.get(SINGLE_URL, status=503)
    with WeatherClient(tmp_path, request_budget=2) as client, patch("time.sleep"):
        with pytest.raises(RuntimeError, match="budget"):
            client.single_run("2026-01-31T00:00")
        assert len(responses.calls) == 2


def test_keys_include_model_run_and_coordinates():
    params = {"run": "2026-01-31T00:00", "latitude": 43, "models": "ecmwf_ifs"}
    base = request_key(SINGLE_URL, params)
    for key, value in [
        ("run", "2026-01-31T06:00"),
        ("latitude", 44),
        ("models", "gfs"),
    ]:
        assert request_key(SINGLE_URL, {**params, key: value}) != base
    assert request_key(SINGLE_URL, dict(reversed(list(params.items())))) == base


@pytest.mark.parametrize(
    "run", ["2026-01-31T01:00", "2026-01-31T06:01", "2026-01-31T06:00:01"]
)
def test_reject_invalid_cycle(run):
    with pytest.raises(ValueError):
        run_datetime(run)


def test_offset_normalized_to_utc():
    assert run_datetime("2026-01-31T11:00+05:00").hour == 6


def test_committed_cache_integrity():
    manifest = json.loads((ROOT / "data/nwp_cache/manifest.json").read_text())
    import hashlib

    for record in manifest["requests"]:
        assert (
            hashlib.sha256((ROOT / record["path"]).read_bytes()).hexdigest()
            == record["sha256"]
        )


@responses.activate
def test_corrupt_portable_cache_is_rejected(tmp_path):
    responses.get(SINGLE_URL, json=PAYLOAD)
    with WeatherClient(tmp_path) as client:
        client.single_run("2026-01-31T00:00")
    path = next((tmp_path / "data/nwp_cache/single_runs/ecmwf_ifs").glob("*Z.json"))
    path.write_text("{}")
    with WeatherClient(tmp_path, cache_only=True) as client:
        with pytest.raises(ValueError, match="checksum"):
            client.single_run("2026-01-31T00:00")
