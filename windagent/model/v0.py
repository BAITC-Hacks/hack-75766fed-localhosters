"""v0: линейный MOS по ветру NWP + логистическая кривая мощности. Страховочная модель MVP.

    ws_site = a * ws100_nwp + b            (MOS, подгонка на Previous Runs day1 vs SCADA-ветер)
    p       = 1 / (1 + exp(-0.705 * (ws_site - 7.89)))   (кривая, подогнанная на SCADA, R² 0.96)
    p10/p90 = p + квантили остатков по бинам p (эмпирические, на тех же данных)

Подгонка: `python -m windagent.model.v0 --fit` -> models/v0_params.json.
Обучающее окно: 2025-11-01..2025-12-31 (Jan 2026 оставлен как dev-окно бэктеста).
Контракт LOC-12: predict_power(request) -> dict в форме PowerForecast (prediction_kind="model").
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PARAMS_PATH = ROOT / "models" / "v0_params.json"
PREV_RUNS_JSON = ROOT / "data/nwp_cache/previous_runs_nov2025_jan2026/ecmwf_ifs.json"
FIT_WINDOW = ("2025-11-01", "2025-12-31")
CURVE_K, CURVE_X0 = 0.705, 7.89
P_MIN, P_MAX = 0.01, 0.99
BINS = [0.0, 0.15, 0.5, 0.85, 1.0001]
MODEL_VERSION = "mos-curve-v0"

_params_cache: dict | None = None


def curve(ws: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-CURVE_K * (np.asarray(ws, dtype=float) - CURVE_X0)))


def load_params() -> dict:
    global _params_cache
    if _params_cache is None:
        if not PARAMS_PATH.exists():
            raise FileNotFoundError(f"{PARAMS_PATH} missing: run `python -m windagent.model.v0 --fit`")
        _params_cache = json.loads(PARAMS_PATH.read_text())
    return _params_cache


def predict_series(ws_nwp, params: dict | None = None) -> pd.DataFrame:
    """ws100 NWP (м/с) -> DataFrame[p50, p10, p90], без утечки: только параметры из fit."""
    params = params or load_params()
    ws_site = params["mos_a"] * np.asarray(ws_nwp, dtype=float) + params["mos_b"]
    p = np.clip(curve(ws_site), P_MIN, P_MAX)
    bin_idx = np.clip(np.digitize(p, BINS) - 1, 0, len(BINS) - 2)
    q10 = np.array(params["resid_q10"])[bin_idx]
    q90 = np.array(params["resid_q90"])[bin_idx]
    p10 = np.clip(p + q10, 0.0, 1.0)
    p90 = np.clip(p + q90, 0.0, 1.0)
    p10 = np.minimum(p10, p)
    p90 = np.maximum(p90, p)
    return pd.DataFrame({"p50": p, "p10": p10, "p90": p90})


def predict_power(request: dict) -> dict:
    """Контракт LOC-12 / runtime агента: request["hourly"][i]["wind_speed_100m_ms"] -> PowerForecast-словарь."""
    ws = [row["wind_speed_100m_ms"] for row in request["hourly"]]
    out = predict_series(ws)
    return {
        "schema_version": "1.0",
        "model_version": MODEL_VERSION,
        "prediction_kind": "model",
        "turbine_id": request["turbine_id"],
        "forecast_origin_utc": request["forecast_origin_utc"],
        "horizon_hours": request["horizon_hours"],
        "interval_label": "start",
        "hourly": [
            {
                "valid_time_utc": row["valid_time_utc"],
                "power_normalized": round(float(out.p50[i]), 6),
                "p10": round(float(out.p10[i]), 6),
                "p90": round(float(out.p90[i]), 6),
            }
            for i, row in enumerate(request["hourly"])
        ],
    }


# ---------------------------------------------------------------- fit


def _load_prev_day1() -> pd.Series:
    js = json.loads(PREV_RUNS_JSON.read_text())
    h = js["hourly"]
    s = pd.Series(h["wind_speed_100m_previous_day1"], index=pd.to_datetime(h["time"], utc=True), dtype=float)
    if js["hourly_units"]["wind_speed_100m_previous_day1"] != "m/s":
        raise ValueError("expected m/s")
    return s.rename("ws_nwp")


def fit(window=FIT_WINDOW, out: Path = PARAMS_PATH) -> dict:
    from research.scada_load import load_hourly  # noqa: WPS433 (только для подгонки)

    nwp = _load_prev_day1()
    frames = []
    for t in ("T1", "T2"):
        h = load_hourly(t)
        frames.append(pd.DataFrame({"ws_obs": h["ws"], "p_obs": h["p"], "turbine": t}).join(nwp, how="inner"))
    df = pd.concat(frames)
    start, end = pd.Timestamp(window[0], tz="UTC"), pd.Timestamp(window[1], tz="UTC") + pd.Timedelta(hours=23)
    df = df[(df.index >= start) & (df.index <= end)].dropna()
    # MOS: ws_obs ~ a*ws_nwp + b (МНК)
    a, b = np.polyfit(df.ws_nwp.values, df.ws_obs.values, 1)
    p_hat = np.clip(curve(a * df.ws_nwp.values + b), P_MIN, P_MAX)
    resid = df.p_obs.values - p_hat
    bin_idx = np.clip(np.digitize(p_hat, BINS) - 1, 0, len(BINS) - 2)
    q10 = [float(np.quantile(resid[bin_idx == k], 0.10)) if (bin_idx == k).any() else -0.1 for k in range(len(BINS) - 1)]
    q90 = [float(np.quantile(resid[bin_idx == k], 0.90)) if (bin_idx == k).any() else 0.1 for k in range(len(BINS) - 1)]
    params = {
        "model_version": MODEL_VERSION,
        "mos_a": float(a),
        "mos_b": float(b),
        "curve_k": CURVE_K,
        "curve_x0": CURVE_X0,
        "bins": BINS,
        "resid_q10": q10,
        "resid_q90": q90,
        "fit_window_utc": list(window),
        "fit_source": "previous_runs ecmwf_ifs wind_speed_100m_previous_day1 (lead 24-29h) vs SCADA nacelle wind, T1+T2 pooled",
        "n_fit": int(len(df)),
        "fit_mae_power": float(np.mean(np.abs(resid))),
        "fit_bias_wind_ms": float(np.mean(df.ws_obs.values - df.ws_nwp.values)),
        "fitted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(params, indent=2, ensure_ascii=False) + "\n")
    return params


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fit", action="store_true")
    args = ap.parse_args()
    if args.fit:
        print(json.dumps(fit(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(load_params(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
