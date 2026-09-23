"""LOC-12: the LOC-10 model is served from the same features it was trained on; offline."""

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from windagent.agent.runtime import read_archive_run
from windagent.dump_single_runs_train import to_frame
from windagent.model import FEATURES, KEYS, build_features, predict, schema, serve, v1
from windagent.schemas import PowerForecast

ROOT = Path(__file__).resolve().parents[1]
RUN_JSON = ROOT / "data/nwp_cache/single_runs/ecmwf_ifs/2026-01-31T0600Z.json"
RUN = datetime(2026, 1, 31, 6, tzinfo=UTC)
ISSUE = pd.Timestamp("2026-01-31T18:00", tz="UTC")
PREV = serve.previous_runs_archive()


def live_run_frame() -> pd.DataFrame:
    return to_frame(RUN, json.loads(RUN_JSON.read_text()))


def test_public_contract():
    assert FEATURES == list(v1.FEATURES) and len(FEATURES) == len(set(FEATURES))
    assert set(schema.FEATURE_SOURCES) == set(FEATURES)
    assert not set(KEYS) & set(FEATURES)
    booster, meta = serve.load_model()
    assert booster.feature_name() == FEATURES == meta["features"]


def test_every_feature_is_available_live():
    live = {v for source in schema.LIVE_SOURCES.values() for v in source["variables"]}
    for feature, sources in schema.FEATURE_SOURCES.items():
        assert set(sources) <= live, feature
    assert set(schema.LIVE_SOURCES["previous_runs"]["models"]) == set(v1.PREVIOUS_MODELS)


@pytest.mark.skipif(not v1.SINGLE_RUNS_PATH.exists(), reason="LOC-18 dump not present")
def test_serving_features_equal_training_features():
    """build_features on one run of the train dump == v1.build_dataset rows the model was fit on."""
    train = v1.build_dataset()
    day = pd.Timestamp("2025-12-20")
    runs = pd.read_parquet(v1.SINGLE_RUNS_PATH)
    run = runs[runs.issue_day == day]
    for turbine in ("T1", "T2"):
        served = build_features(run, day.tz_localize("UTC") + pd.Timedelta(hours=18), turbine, PREV)
        trained = train[(train.issue_day == day) & (train.turbine_id == turbine)].reset_index(drop=True)
        pd.testing.assert_frame_equal(served[FEATURES], trained[FEATURES], check_dtype=False)
        assert served.forecast_lead_h.tolist() == trained.forecast_lead_h.tolist()


@pytest.mark.skipif(not v1.SINGLE_RUNS_PATH.exists(), reason="LOC-18 dump not present")
def test_train_lead_distribution_covers_dayahead_leads():
    runs = pd.read_parquet(v1.SINGLE_RUNS_PATH, columns=["lead_h", "in_dayahead_window"])
    assert set(range(12, 60)) <= set(runs.loc[runs.in_dayahead_window, "lead_h"])


def test_agent_request_path_matches_archive_path():
    """Same run through runtime.read_archive_run -> serve.nwp_frame gives the dump-path features."""
    forecast = read_archive_run(RUN_JSON, RUN)
    request = {"weather_run_time_utc": "2026-01-31T06:00:00Z",
               "hourly": [row.model_dump(mode="json") for row in forecast.hourly]}
    served = build_features(serve.nwp_frame(request), ISSUE, "turbine_1", PREV)
    archived = build_features(live_run_frame(), ISSUE, "T1", PREV)
    pd.testing.assert_frame_equal(served, archived, check_dtype=False)
    assert served.nwp_lead_h.tolist() == list(range(12, 60))


def test_run_published_after_issue_is_rejected():
    with pytest.raises(ValueError, match="NWP_LEAKAGE"):
        build_features(live_run_frame(), pd.Timestamp("2026-01-31T12:00", tz="UTC"), "T1")


def test_reissue_origin_shifts_previous_runs_mask():
    """A 20:00 reissue counts hours and Previous Runs publication from 20:00, not 18:00."""
    run = live_run_frame()
    at18 = build_features(run, ISSUE, "T1", PREV, horizon_h=46)
    at20 = build_features(run, ISSUE + pd.Timedelta(hours=2), "T1", PREV, horizon_h=46)
    assert at20.hours_since_issue.tolist() == list(range(46))
    day1_18 = at18.set_index("valid_utc").prev_icon_global_age_days.eq(1)
    day1_20 = at20.set_index("valid_utc").prev_icon_global_age_days.eq(1)
    shared = day1_18.index.intersection(day1_20.index)
    assert (day1_20[shared] >= day1_18[shared]).all()  # later origin: never less day1, never more leakage


def test_missing_previous_runs_fall_back_to_single_run():
    f = build_features(live_run_frame(), ISSUE, "T1")
    assert f[[c for c in FEATURES if c.startswith("prev_") and c.endswith("_ws100")]].isna().all(axis=None)
    np.testing.assert_allclose(f.ensemble_ws100_mean, f.ws100)


def test_predict_is_ordered_and_blended():
    f = build_features(live_run_frame(), ISSUE, "T2", PREV)
    out = predict(f)
    assert list(out.columns) == ["p10", "p50", "p90"] and out.index.equals(f.index)
    assert ((out.p10 <= out.p50) & (out.p50 <= out.p90)).all()
    assert ((0 <= out) & (out <= 1)).all(axis=None)


def test_v1_adapter_returns_valid_power_forecast():
    forecast = read_archive_run(RUN_JSON, RUN)
    rows = [r.model_dump(mode="json") for r in forecast.hourly if r.valid_time_utc >= ISSUE][:48]
    request = {"schema_version": "1.0", "turbine_id": "turbine_2", "forecast_origin_utc": "2026-01-31T18:00:00Z",
               "horizon_hours": 48, "weather_run_time_utc": "2026-01-31T06:00:00Z", "hourly": rows}
    result = PowerForecast.model_validate(v1.predict_power(request))
    assert result.prediction_kind == "model" and result.model_version == "lightgbm-q-v1"
    assert len(result.hourly) == 48

    mean_result = PowerForecast.model_validate(
        v1.predict_power({**request, "point_estimate": "mean"})
    )
    assert any(
        median.power_normalized != mean.power_normalized
        for median, mean in zip(result.hourly, mean_result.hourly, strict=True)
    )
