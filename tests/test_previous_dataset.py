"""LOC-15 acceptance checks against committed Open-Meteo responses."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from windagent.dump_previous_runs import dump
from windagent.tools.weather import PREVIOUS_MODELS, ROOT

CACHE = ROOT / "data/nwp_cache/previous_runs"


def test_february_ticket_window_and_skill():
    manifest = json.loads((CACHE / "manifest.json").read_text())
    assert set(manifest["models"]) == set(PREVIOUS_MODELS)
    assert manifest["raw_request_count"] == 198
    assert manifest["estimated_weighted_calls"] < 500
    for model, info in manifest["models"].items():
        path = CACHE / f"{model}.parquet"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == info["parquet_sha256"]
        frame = pd.read_parquet(path)
        assert str(frame.valid_utc.dt.tz) == "UTC"
        assert frame.valid_utc.is_unique
        window = frame[frame.valid_utc.between("2026-01-31", "2026-02-28 23:00")]
        assert len(window) == 696
        assert (
            not window[
                ["wind_speed_100m_previous_day1", "wind_speed_100m_previous_day2"]
            ]
            .isna()
            .any()
            .any()
        )
        assert manifest["skill"][model]["day1"]["n"] == 2200


def test_full_archive_rebuild_without_any_network(tmp_path: Path):
    shutil.copytree(CACHE / "T1", tmp_path / "data/nwp_cache/previous_runs/T1")
    with patch(
        "requests.adapters.HTTPAdapter.send", side_effect=AssertionError("network")
    ):
        rebuilt = dump(tmp_path)
    original = json.loads((CACHE / "manifest.json").read_text())
    assert rebuilt == original
    for model in PREVIOUS_MODELS:
        actual = pd.read_parquet(
            tmp_path / f"data/nwp_cache/previous_runs/{model}.parquet"
        )
        expected = pd.read_parquet(CACHE / f"{model}.parquet")
        pd.testing.assert_frame_equal(actual, expected)
    assert (tmp_path / "docs/research/nwp-sources.md").read_bytes() == (
        ROOT / "docs/research/nwp-sources.md"
    ).read_bytes()
