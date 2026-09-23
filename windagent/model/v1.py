"""v1 adapter for the agent runtime: `--model-adapter windagent.model.v1:predict_power`.

request (runtime.predict_power) -> Single Run frame -> build_features -> predict -> PowerForecast dict.
Optional request keys, both as-of issue time and in the long forms build_features expects:
    "scada_hourly":  [{"ts": ..., "p": ..., "ws": ...}, ...]           (hourly, UTC interval start)
    "previous_runs": [{"model": ..., "valid_utc": ..., "wind_speed_100m_previous_day1": ...}, ...]
Absent -> the corresponding features are NaN, as for a stale SCADA feed in the test window.
"""

from __future__ import annotations

import pandas as pd

from windagent.model.artifact import ARTIFACT_PATH, load_artifact, predict
from windagent.model.schema import build_features

REQUEST_TO_RAW = {
    "wind_speed_100m_ms": "wind_speed_100m",
    "wind_speed_80m_ms": "wind_speed_80m",
    "wind_speed_10m_ms": "wind_speed_10m",
    "wind_direction_100m_deg": "wind_direction_100m",
    "temperature_2m_c": "temperature_2m",
    "surface_pressure_hpa": "surface_pressure",
}


def nwp_frame(request: dict) -> pd.DataFrame:
    rows = [{"valid_utc": row["valid_time_utc"], **{raw: row.get(key) for key, raw in REQUEST_TO_RAW.items()}}
            for row in request["hourly"]]
    frame = pd.DataFrame(rows)
    frame["valid_utc"] = pd.to_datetime(frame["valid_utc"], utc=True)
    frame["run_init_utc"] = pd.Timestamp(request["weather_run_time_utc"])
    return frame.astype({raw: float for raw in REQUEST_TO_RAW.values()})


def predict_power(request: dict) -> dict:
    scada = pd.DataFrame(request["scada_hourly"]) if request.get("scada_hourly") else None
    if scada is not None:
        scada["ts"] = pd.to_datetime(scada["ts"], utc=True)
    prev = pd.DataFrame(request["previous_runs"]) if request.get("previous_runs") else None
    features = build_features(nwp_frame(request), request["forecast_origin_utc"], request["turbine_id"],
                              scada, prev, horizon_h=request["horizon_hours"])
    artifact = load_artifact(ARTIFACT_PATH)
    out = predict(features, artifact)
    return {
        "schema_version": "1.0",
        "model_version": artifact["model_version"],
        "prediction_kind": "model",
        "turbine_id": request["turbine_id"],
        "forecast_origin_utc": request["forecast_origin_utc"],
        "horizon_hours": request["horizon_hours"],
        "interval_label": "start",
        "hourly": [
            {
                "valid_time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "power_normalized": round(float(r.p50), 6),
                "p10": round(float(r.p10), 6),
                "p90": round(float(r.p90), 6),
            }
            for t, r in zip(features["valid_utc"], out.itertuples())
        ],
    }
