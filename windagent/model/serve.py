"""Stable LOC-12 serving contract backed by the LOC-11 distribution models.

    models/lgbm_q_v1/{p10,p50,p90,mean}.txt
    p10/p50/p90 = non-crossing LightGBM quantiles
    point        = P50 for MAE, conditional mean for RMSE

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

from windagent.model import quantiles, v1
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
def load_quantile_models(
    metadata_path: Path = quantiles.METADATA_PATH,
) -> tuple[dict[str, lgb.Booster], dict]:
    """Load and schema-check the four LOC-11 boosters."""
    if not Path(metadata_path).exists():
        raise FileNotFoundError(
            f"MODEL_NOT_FOUND: {metadata_path} "
            "(train with `python -m windagent.model.quantiles`)"
        )
    meta = json.loads(Path(metadata_path).read_text())
    models = {
        name: lgb.Booster(model_file=str(quantiles.ROOT / relative_path))
        for name, relative_path in meta["models"].items()
    }
    expected = set((*quantiles.QUANTILES, "mean"))
    if set(models) != expected:
        raise ValueError(f"MODEL_SET_MISMATCH: expected {sorted(expected)}")
    if meta.get("features") != FEATURES or any(
        model.feature_name() != FEATURES for model in models.values()
    ):
        raise ValueError("SCHEMA_MISMATCH: quantile models use another feature schema")
    return models, meta


@cache
def previous_runs_archive(path: Path = PREV_ARCHIVE) -> pd.DataFrame | None:
    return pd.read_parquet(path, columns=list(PREV_COLUMNS)) if Path(path).exists() else None


def predict_distribution(
    features: pd.DataFrame,
    models: dict[str, lgb.Booster] | None = None,
) -> pd.DataFrame:
    """Return P10/P50/P90 plus the conditional mean on the input index."""
    missing = [c for c in FEATURES if c not in features.columns]
    if missing:
        raise ValueError(f"INVALID_INPUT: features lack {missing}; build them with build_features()")
    if models is None:
        models, meta = load_quantile_models()
        calibration = meta.get("calibration")
    else:
        calibration = load_quantile_models()[1].get("calibration")
    return quantiles.predict(models, features, calibration)


def predict(
    features: pd.DataFrame,
    models: dict[str, lgb.Booster] | None = None,
) -> pd.DataFrame:
    """features[FEATURES] -> DataFrame[p10,p50,p90], preserving the index."""
    return predict_distribution(features, models)[["p10", "p50", "p90"]]


def nwp_frame(request: dict) -> pd.DataFrame:
    """request["hourly"] (WeatherHour dicts) -> one-run frame in Open-Meteo names."""
    frame = pd.DataFrame([{"valid_utc": row["valid_time_utc"], **{raw: row.get(key) for key, raw in REQUEST_TO_RAW.items()}}
                          for row in request["hourly"]])
    frame["valid_utc"] = pd.to_datetime(frame["valid_utc"], utc=True)
    frame["run_init_utc"] = pd.Timestamp(request["weather_run_time_utc"])
    return frame.astype({raw: float for raw in REQUEST_TO_RAW.values()})


def predict_power(request: dict) -> dict:
    models, meta = load_quantile_models()
    prev = pd.DataFrame(request["previous_runs"]) if request.get("previous_runs") else previous_runs_archive()
    features = build_features(nwp_frame(request), request["forecast_origin_utc"], request["turbine_id"],
                              prev, horizon_h=request["horizon_hours"])
    out = predict_distribution(features, models)
    point_estimate = request.get("point_estimate", "median")
    if point_estimate not in {"median", "mean", "cost"}:
        raise ValueError("INVALID_INPUT: point_estimate must be median, mean or cost")
    # LOC-31 will choose a cost-optimal quantile once imbalance coefficients are
    # available in the request.  Until then cost safely follows the median.
    point = out["mean"] if point_estimate == "mean" else out["p50"]
    lower = np.minimum(out["p10"], point)
    upper = np.maximum(out["p90"], point)
    return {
        "schema_version": "1.0",
        "model_version": meta["model_version"],
        "prediction_kind": "model",
        "turbine_id": request["turbine_id"],
        "forecast_origin_utc": request["forecast_origin_utc"],
        "horizon_hours": request["horizon_hours"],
        "interval_label": "start",
        "hourly": [
            {"valid_time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "power_normalized": float(value),
             "p10": float(lo), "p90": float(hi)}
            for t, value, lo, hi in zip(features["valid_utc"], point, lower, upper)
        ],
    }
