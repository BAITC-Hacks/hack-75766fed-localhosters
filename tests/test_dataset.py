import json
from unittest.mock import patch

import pandas as pd
import pytest

from windagent.dump_weather import dump, runs, to_frame
from windagent.tools.weather import ROOT, VARIABLES, WeatherClient


def test_dataset_coverage():
    frame = pd.read_parquet(ROOT / "data/nwp/single_runs_ecmwf_ifs_feb2026.parquet")
    assert set(frame.run_init_utc) == set(pd.to_datetime(runs(), utc=True))
    assert not frame.duplicated(["run_init_utc", "valid_utc"]).any()
    horizon = frame[frame.lead_h.between(1, 72)]
    assert len(horizon) == 116 * 72
    assert not horizon[list(VARIABLES)].isna().any().any()
    assert (
        (frame.valid_utc - frame.run_init_utc).dt.total_seconds() == frame.lead_h * 3600
    ).all()


def test_fresh_checkout_full_offline_rebuild(tmp_path, monkeypatch):
    import shutil

    shutil.copytree(ROOT / "data/nwp_cache", tmp_path / "data/nwp_cache")
    monkeypatch.setenv("OPEN_METEO_CACHE_ONLY", "1")
    with patch(
        "requests.adapters.HTTPAdapter.send", side_effect=AssertionError("network")
    ):
        result = dump(tmp_path)
    assert result["network_attempts_this_execution"] == 0
    expected = pd.read_parquet(ROOT / "data/nwp/single_runs_ecmwf_ifs_feb2026.parquet")
    actual = pd.read_parquet(
        tmp_path / "data/nwp/single_runs_ecmwf_ifs_feb2026.parquet"
    )
    pd.testing.assert_frame_equal(actual, expected)
    manifest = json.loads((tmp_path / "data/nwp_cache/manifest.json").read_text())
    assert len(manifest["requests"]) == 118


def test_incomplete_or_null_horizon_rejected():
    run = runs()[0]
    with WeatherClient(ROOT, cache_only=True) as client:
        data = client.single_run(run)
    data["hourly"]["wind_speed_100m"][10] = None
    with pytest.raises(ValueError, match="Missing weather"):
        to_frame(run, data)
