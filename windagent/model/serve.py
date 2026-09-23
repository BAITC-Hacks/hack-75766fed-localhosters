"""LOC-12 serving for the LOC-10 model: predict(features) and the agent adapter predict_power(request).

    models/lightgbm_v1.txt + models/lightgbm_v1.metadata.json (written by `python -m windagent.model.v1`)
    p50     = v1.predict: 0.4 * LightGBM + 0.6 * v0, clipped to [0, 1]
    p10/p90 = interim until LOC-11: v0's empirical residual quantiles per p50 bin, around the v1 p50.

Agent: `--model-adapter windagent.model.v1:predict_power`. Previous Runs come from the request
("previous_runs", long form of data/baselines/previous_runs_ws100.parquet) or, offline, from that
committed archive; v1 masks every value whose run was not public at the forecast origin.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from windagent.model import v0, v1
from windagent.model.schema import FEATURES, PREV_COLUMNS, build_features

PREV_ARCHIVE = v1.PREVIOUS_RUNS_PATH
REQUEST_TO_RAW = {
    "wind_speed_100m_ms": "wind_speed_100m",
    "wind_speed_80m_ms": "wind_speed_80m",
    "wind_speed_10m_ms": "wind_speed_10m",
    "wind_gusts_10m_ms": "wind_gusts_10m",
    "wind_direction_100m_deg": "wind_direction_100m",
    "temperature_2m_c": "temperature_2m",
    "surface_pressure_hpa": "surface_pressure",
}


@cache
def load_model(model_path: Path = v1.MODEL_PATH, metadata_path: Path = v1.METADATA_PATH) -> tuple[lgb.Booster, dict]:
    if not Path(model_path).exists():
        raise FileNotFoundError(f"MODEL_NOT_FOUND: {model_path} (train with `python -m windagent.model.v1`)")
    meta = json.loads(Path(metadata_path).read_text())
    booster = lgb.Booster(model_file=str(model_path))
    if meta.get("features") != FEATURES or booster.feature_name() != FEATURES:
        raise ValueError(f"SCHEMA_MISMATCH: {model_path} was trained on other features than schema.FEATURES")
    return booster, meta


@cache
def previous_runs_archive(path: Path = PREV_ARCHIVE) -> pd.DataFrame | None:
    return pd.read_parquet(path, columns=list(PREV_COLUMNS)) if Path(path).exists() else None


def predict(features: pd.DataFrame, booster: lgb.Booster | None = None) -> pd.DataFrame:
    """features[FEATURES] -> DataFrame[p10, p50, p90] on the same index, p10 <= p50 <= p90."""
    missing = [c for c in FEATURES if c not in features.columns]
    if missing:
        raise ValueError(f"INVALID_INPUT: features lack {missing}; build them with build_features()")
    booster = booster or load_model()[0]
    p50 = v1.predict(booster, features)
    params = v0.load_params()
    idx = np.clip(np.digitize(p50, v0.BINS) - 1, 0, len(v0.BINS) - 2)
    p10 = np.minimum(np.clip(p50 + np.asarray(params["resid_q10"])[idx], 0.0, 1.0), p50)
    p90 = np.maximum(np.clip(p50 + np.asarray(params["resid_q90"])[idx], 0.0, 1.0), p50)
    return pd.DataFrame({"p10": p10, "p50": p50, "p90": p90}, index=features.index)


def nwp_frame(request: dict) -> pd.DataFrame:
    """request["hourly"] (WeatherHour dicts) -> one-run frame in Open-Meteo names."""
    frame = pd.DataFrame([{"valid_utc": row["valid_time_utc"], **{raw: row.get(key) for key, raw in REQUEST_TO_RAW.items()}}
                          for row in request["hourly"]])
    frame["valid_utc"] = pd.to_datetime(frame["valid_utc"], utc=True)
    frame["run_init_utc"] = pd.Timestamp(request["weather_run_time_utc"])
    return frame.astype({raw: float for raw in REQUEST_TO_RAW.values()})


def predict_power(request: dict) -> dict:
    booster, meta = load_model()
    prev = pd.DataFrame(request["previous_runs"]) if request.get("previous_runs") else previous_runs_archive()
    features = build_features(nwp_frame(request), request["forecast_origin_utc"], request["turbine_id"],
                              prev, horizon_h=request["horizon_hours"])
    out = predict(features, booster)
    return {
        "schema_version": "1.0",
        "model_version": meta["model_version"],
        "prediction_kind": "model",
        "turbine_id": request["turbine_id"],
        "forecast_origin_utc": request["forecast_origin_utc"],
        "horizon_hours": request["horizon_hours"],
        "interval_label": "start",
        "hourly": [
            {"valid_time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "power_normalized": float(r.p50),
             "p10": float(r.p10), "p90": float(r.p90)}
            for t, r in zip(features["valid_utc"], out.itertuples())
        ],
    }
