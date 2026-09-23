"""LOC-12: one feature schema for train (LOC-18 dump), backtest and the agent adapter; offline."""

import json
import pickle
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from windagent.agent.runtime import read_archive_run
from windagent.dump_single_runs_train import to_frame
from windagent.model import FEATURES, KEYS, build_features, predict, schema, v1
from windagent.model import artifact as artifact_mod
from windagent.schemas import PowerForecast

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "data/nwp/single_runs_ecmwf_ifs_train.parquet"
RUN_JSON = ROOT / "data/nwp_cache/single_runs/ecmwf_ifs/2026-01-31T0600Z.json"
RUN = datetime(2026, 1, 31, 6, tzinfo=UTC)
ISSUE = pd.Timestamp("2026-01-31T18:00", tz="UTC")


class Linear:
    """Stand-in for a trained regressor: p = ws100 / 20 (+ shift)."""

    def __init__(self, shift=0.0):
        self.shift = shift

    def predict(self, X):
        return (X["ws100"].to_numpy() / 20 + self.shift).clip(0, 1)


def stub_artifact(**overrides):
    art = {"model_version": "stub", "features": FEATURES, "p50": Linear(),
           "p10": Linear(-0.1), "p90": Linear(0.1)}
    return {**art, **overrides}


def live_run_frame() -> pd.DataFrame:
    return to_frame(RUN, json.loads(RUN_JSON.read_text()))


def test_public_contract_imports():
    assert len(FEATURES) == len(set(FEATURES))
    assert set(schema.FEATURE_SOURCES) == set(FEATURES)
    assert not set(KEYS) & set(FEATURES)


def test_every_feature_is_available_live():
    live = {v for source in schema.LIVE_SOURCES.values() for v in source["variables"]}
    for feature, sources in schema.FEATURE_SOURCES.items():
        assert set(sources) <= live, feature
    assert "ecmwf_ifs" in schema.LIVE_SOURCES["single_runs"]["models"]


@pytest.mark.skipif(not TRAIN.exists(), reason="LOC-18 dump not present")
def test_train_schema_equals_live_fixture_schema():
    runs = pd.read_parquet(TRAIN)
    sample = runs[runs.issue_day == runs.issue_day.max() - pd.Timedelta(days=30)]
    train = schema.build_training_frame(sample)
    live = build_features(live_run_frame(), ISSUE, "T1")
    assert list(train.columns) == [*KEYS, *FEATURES]
    assert schema.schema_of(train) == schema.schema_of(live)


@pytest.mark.skipif(not TRAIN.exists(), reason="LOC-18 dump not present")
def test_train_lead_distribution_covers_dayahead_leads():
    runs = pd.read_parquet(TRAIN, columns=["lead_h", "in_dayahead_window", "run_init_utc"])
    leads = set(runs.loc[runs.in_dayahead_window, "lead_h"])
    assert set(range(12, 60)) <= leads


def test_agent_request_path_matches_train_path():
    """Same run through runtime.read_archive_run -> v1.nwp_frame gives the same features as the dump path."""
    forecast = read_archive_run(RUN_JSON, RUN)
    request = {"weather_run_time_utc": "2026-01-31T06:00:00Z",
               "hourly": [row.model_dump(mode="json") for row in forecast.hourly]}
    served = build_features(v1.nwp_frame(request), ISSUE, "turbine_1")
    trained = build_features(live_run_frame(), ISSUE, "T1")
    pd.testing.assert_frame_equal(served, trained, check_dtype=False)
    assert served.lead_h.tolist() == list(range(12, 60))
    assert (served.run_cycle == 6).all()


def test_run_published_after_issue_is_rejected():
    with pytest.raises(ValueError, match="NWP_LEAKAGE"):
        build_features(live_run_frame(), pd.Timestamp("2026-01-31T12:00", tz="UTC"), "T1")


def test_scada_lags_only_when_fresh_and_never_from_the_future():
    hours = pd.date_range("2026-01-30T00:00", "2026-02-01T00:00", freq="h", tz="UTC")
    scada = pd.DataFrame({"p": np.linspace(0, 1, len(hours)), "ws": 5.0}, index=hours)
    fresh = build_features(live_run_frame(), ISSUE, "T1", scada)
    assert (fresh.scada_age_h == 0).all()
    assert fresh.p_lag.iloc[0] == scada.p[ISSUE - pd.Timedelta(hours=1)]  # hour 17:00-18:00, no later

    stale = scada[scada.index < ISSUE - pd.Timedelta(hours=8)]
    f = build_features(live_run_frame(), ISSUE, "T1", stale)
    assert (f.scada_age_h == 8).all()
    assert f[schema.LAG_FEATURES].isna().all(axis=None)

    none = build_features(live_run_frame(), ISSUE, "T1")
    assert none[schema.SCADA_FEATURES].isna().all(axis=None)


def test_previous_runs_masked_by_publication():
    valid = pd.date_range(ISSUE - pd.Timedelta(days=3), periods=24 * 6, freq="h")
    prev = pd.DataFrame({"model": "icon_global", "valid_utc": valid,
                         "wind_speed_100m_previous_day1": 5.0, "wind_speed_100m_previous_day2": 6.0})
    f = build_features(live_run_frame(), ISSUE, "T1", prev_runs=prev)
    d1, d2 = f.pr_icon_global_ws100_d1, f.pr_icon_global_ws100_d2
    assert d1.notna().tolist() == [h <= 16 for h in range(48)]  # valid - 24 + 8 <= issue
    assert d2.notna().tolist() == [h <= 40 for h in range(48)]
    assert f.pr_gfs_global_ws100_d1.isna().all()
    assert (f.n_models == 2).iloc[:41].all() and (f.n_models == 1).iloc[41:].all()


def test_mask_lags_drops_whole_issues():
    hours = pd.date_range(pd.Timestamp("2026-01-30", tz="UTC"), ISSUE, freq="h", inclusive="left")
    scada = pd.DataFrame({"p": 0.5, "ws": 5.0}, index=hours)
    frames = [build_features(live_run_frame(), ISSUE, t, scada) for t in ("T1", "T2")]
    frames[1]["issue_time_utc"] = ISSUE + pd.Timedelta(days=1)
    masked = schema.mask_lags(pd.concat(frames, ignore_index=True), frac=0.5, seed=1)
    per_issue = masked.groupby("issue_time_utc").p_lag.apply(lambda s: s.isna().all())
    assert per_issue.sum() == 1


def test_predict_quantiles_are_ordered_and_clipped():
    f = build_features(live_run_frame(), ISSUE, "T2")
    out = predict(f, stub_artifact())
    assert list(out.columns) == ["p10", "p50", "p90"] and out.index.equals(f.index)
    assert ((out.p10 <= out.p50) & (out.p50 <= out.p90)).all()
    assert out.p50.between(0.01, 0.99).all()

    binned = stub_artifact(p10=None, p90=None, bins=[0, 0.5, 1.0001], resid_q10=[-0.05, -0.2], resid_q90=[0.1, 0.05])
    out = predict(f, binned)
    assert ((out.p10 <= out.p50) & (out.p50 <= out.p90)).all()


def test_artifact_with_other_features_is_rejected(tmp_path):
    path = tmp_path / "old.pkl"
    path.write_bytes(pickle.dumps(stub_artifact(features=FEATURES[:-1])))
    with pytest.raises(ValueError, match="SCHEMA_MISMATCH"):
        artifact_mod.load_artifact(path)
    with pytest.raises(FileNotFoundError, match="MODEL_NOT_FOUND"):
        artifact_mod.load_artifact(tmp_path / "missing.pkl")


def test_v1_adapter_returns_valid_power_forecast(tmp_path, monkeypatch):
    path = tmp_path / "lgbm_v1.pkl"
    path.write_bytes(pickle.dumps(stub_artifact()))
    monkeypatch.setattr(v1, "ARTIFACT_PATH", path)
    forecast = read_archive_run(RUN_JSON, RUN)
    rows = [r.model_dump(mode="json") for r in forecast.hourly if r.valid_time_utc >= ISSUE][:48]
    request = {"schema_version": "1.0", "turbine_id": "turbine_2", "forecast_origin_utc": "2026-01-31T18:00:00Z",
               "horizon_hours": 48, "weather_run_time_utc": "2026-01-31T06:00:00Z", "hourly": rows,
               "scada_hourly": [{"ts": "2026-01-31T16:00:00Z", "p": 0.4, "ws": 7.0}]}
    result = PowerForecast.model_validate(v1.predict_power(request))
    assert result.prediction_kind == "model" and len(result.hourly) == 48


def test_write_metadata(tmp_path):
    meta = artifact_mod.write_metadata(model_version="lgbm-v1-test", train_range=("2024-03-14", "2025-12-31"),
                                       holdout_metrics={"jan2026_mae": None}, path=tmp_path / "metadata.json")
    assert json.loads((tmp_path / "metadata.json").read_text())["features"] == FEATURES
    assert meta["features_hash"] == artifact_mod.features_hash()
