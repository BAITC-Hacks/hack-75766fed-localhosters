"""MOS + empirical power curve, trained only on Nov–Dec 2025 SCADA wind."""
from functools import lru_cache

from windagent.backtest import fit_mos, power


@lru_cache(maxsize=1)
def coefficients():
    return fit_mos()


def predict(request: dict) -> dict:
    rows = request["hourly"]
    return {
        "schema_version": "1.0", "model_version": "mos-logistic-v0", "prediction_kind": "model",
        "turbine_id": request["turbine_id"], "forecast_origin_utc": request["forecast_origin_utc"],
        "horizon_hours": request["horizon_hours"], "interval_label": "start",
        "hourly": [{"valid_time_utc": row["valid_time_utc"],
                    "power_normalized": power(row["wind_speed_100m_ms"], coefficients())} for row in rows],
    }
