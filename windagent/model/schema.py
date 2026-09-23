"""LOC-12 feature contract: one build_features() for training (LOC-18 Single Runs dump) and inference.

    build_features(nwp, issue_time, turbine_id, scada_hist=None, prev_runs=None) -> DataFrame
    frame[FEATURES] is exactly what the model sees; KEYS are carried for joins and audit.

Inputs
- nwp: one Single Run of ecmwf_ifs, columns run_init_utc, valid_utc and RAW_NWP (Open-Meteo names,
  m/s, deg, degC, hPa) — a group of data/nwp/single_runs_ecmwf_ifs_*.parquet or a live response.
- scada_hist: hourly SCADA of this turbine (windagent.data.scada.load_hourly, or the processed parquet),
  UTC index or `ts` column, columns p and ws. Only hours complete by issue_time are used.
- prev_runs: LOC-15 Previous Runs in long form (model, valid_utc, *_previous_day{1,2}). Values whose
  producing run could not be published by issue_time are masked to NaN, identically in train and serve.

Leads: lead_h counts from the NWP run (12..59 for the 06Z dayahead run); the horizon counts from issue.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from windagent import clock
from windagent.config import HOURLY_LABEL

SCHEMA_VERSION = "1.0"
HORIZON_H = clock.HORIZON_H

# Raw inputs, Open-Meteo variable names. Each is requested by name in live mode (see LIVE_SOURCES).
RAW_NWP = (
    "wind_speed_100m",
    "wind_speed_80m",
    "wind_speed_10m",
    "wind_direction_100m",
    "temperature_2m",
    "surface_pressure",
)
PREV_MODELS = ("icon_global", "ecmwf_ifs025", "gfs_global", "ecmwf_aifs025_single", "ecmwf_ifs")
PREV_DAYS = (1, 2)
PREV_VARIABLE = "wind_speed_100m"
# previous_dayN = "predicted 24*N hours before valid time" (Open-Meteo docs), i.e. a run initialised at or
# before valid - 24*N h. Assume the latest such run and the slowest publication among the five models
# (ECMWF 00Z/12Z: +8 h, windagent.clock) -> available iff valid - 24*N + 8 <= issue_time.
PREV_AVAIL_LAG_H = 8

LAG_MAX_AGE_H = 6  # SCADA lags are features only when the last complete hour is this fresh

LIVE_SOURCES = {
    "single_runs": {
        "url": "https://api.open-meteo.com/v1/forecast",  # same variables as single-runs-api (LOC-14/18)
        "models": ("ecmwf_ifs",),
        "variables": RAW_NWP,
    },
    "previous_runs": {
        "url": "https://previous-runs-api.open-meteo.com/v1/forecast",
        "models": PREV_MODELS,
        "variables": tuple(f"{PREV_VARIABLE}_previous_day{d}" for d in PREV_DAYS),
    },
    "scada": {"url": "site SCADA feed (hourly p, ws)", "variables": ("p", "ws")},
}

NWP_FEATURES = [
    "ws100", "ws80", "ws10", "ws100_cubed", "dir100_sin", "dir100_cos",
    "temperature_2m", "surface_pressure", "rho", "ws100_rho", "shear_ln",
]
TIME_FEATURES = ["lead_h", "run_cycle", "hour_sin", "hour_cos", "doy_sin", "doy_cos"]
PREV_FEATURES = [f"pr_{m}_ws100_d{d}" for m in PREV_MODELS for d in PREV_DAYS]
ENSEMBLE_FEATURES = ["ws100_models_mean", "ws100_models_std", "n_models"]
SCADA_FEATURES = ["scada_age_h", "p_lag", "ws_lag"]
LAG_FEATURES = ["p_lag", "ws_lag"]
CATEGORICAL = ["turbine_id"]
FEATURES = [*NWP_FEATURES, *TIME_FEATURES, *PREV_FEATURES, *ENSEMBLE_FEATURES, *SCADA_FEATURES, *CATEGORICAL]
KEYS = ["issue_time_utc", "valid_utc", "run_init_utc", "horizon_h", "turbine"]

# Which raw inputs each feature is derived from; tests check every source is fetchable live.
FEATURE_SOURCES = {
    "ws100": ["wind_speed_100m"], "ws80": ["wind_speed_80m"], "ws10": ["wind_speed_10m"],
    "ws100_cubed": ["wind_speed_100m"],
    "dir100_sin": ["wind_direction_100m"], "dir100_cos": ["wind_direction_100m"],
    "temperature_2m": ["temperature_2m"], "surface_pressure": ["surface_pressure"],
    "rho": ["surface_pressure", "temperature_2m"],
    "ws100_rho": ["wind_speed_100m", "surface_pressure", "temperature_2m"],
    "shear_ln": ["wind_speed_100m", "wind_speed_10m"],
    **{f: [] for f in TIME_FEATURES},  # run init and valid time
    **{f"pr_{m}_ws100_d{d}": [f"{PREV_VARIABLE}_previous_day{d}"] for m in PREV_MODELS for d in PREV_DAYS},
    **{f: ["wind_speed_100m", *(f"{PREV_VARIABLE}_previous_day{d}" for d in PREV_DAYS)]
       for f in ENSEMBLE_FEATURES},
    "scada_age_h": ["p"], "p_lag": ["p"], "ws_lag": ["ws"],
    "turbine_id": [],
}

TURBINE_CODES = {"T1": 0, "T2": 1}
RHO_0 = 1.225
R_DRY = 287.05


def turbine_key(turbine_id) -> str:
    """'T1' | 'turbine_1' | 1 | 0-based code -> 'T1'."""
    text = str(turbine_id).strip().lower().replace("turbine_", "").lstrip("t")
    key = f"T{text}"
    if key not in TURBINE_CODES:
        raise ValueError(f"INVALID_INPUT: unknown turbine_id={turbine_id!r}")
    return key


def _utc_hour(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if ts != ts.floor("h"):
        raise ValueError(f"INVALID_INPUT: {ts} is not on the hourly grid")
    return ts


def _cyc(values: np.ndarray, period: float) -> tuple[np.ndarray, np.ndarray]:
    angle = 2 * np.pi * np.asarray(values, dtype=float) / period
    return np.sin(angle), np.cos(angle)


def _nwp_window(nwp: pd.DataFrame, issue: pd.Timestamp, horizon_h: int) -> tuple[pd.DataFrame, pd.Timestamp]:
    missing = [c for c in ("run_init_utc", "valid_utc", *RAW_NWP) if c not in nwp.columns]
    if missing:
        raise ValueError(f"INVALID_INPUT: NWP frame lacks {missing}")
    runs = pd.to_datetime(nwp["run_init_utc"], utc=True).unique()
    if len(runs) != 1:
        raise ValueError(f"INVALID_INPUT: expected one NWP run, got {len(runs)}")
    run_init = pd.Timestamp(runs[0])
    clock.assert_as_of(issue.to_pydatetime(), run_init.to_pydatetime(), [issue.to_pydatetime()])
    frame = nwp.assign(valid_utc=pd.to_datetime(nwp["valid_utc"], utc=True)).set_index("valid_utc")
    targets = pd.date_range(issue, periods=horizon_h, freq="h")
    window = frame.reindex(targets)[list(RAW_NWP)]
    if window.isna().any(axis=None):
        bad = window.index[window.isna().any(axis=1)]
        raise ValueError(f"INCOMPLETE_HORIZON: run {run_init} lacks values at {len(bad)} hours from {bad[0]}")
    return window, run_init


def scada_state(scada_hist: pd.DataFrame | None, issue: pd.Timestamp) -> tuple[float, float, float]:
    """(scada_age_h, p_lag, ws_lag) from hours complete by issue; lags NaN when age > LAG_MAX_AGE_H."""
    if scada_hist is None or len(scada_hist) == 0:
        return np.nan, np.nan, np.nan
    hist = scada_hist.set_index("ts") if "ts" in scada_hist.columns else scada_hist
    starts = pd.DatetimeIndex(hist.index)
    starts = starts.tz_localize("UTC") if starts.tz is None else starts.tz_convert("UTC")
    ends = starts + pd.Timedelta(hours=1) if HOURLY_LABEL == "left" else starts
    ok = (ends <= issue) & hist["p"].notna().to_numpy()
    if not ok.any():
        return np.nan, np.nan, np.nan
    last = np.flatnonzero(ok)[np.argmax(ends[ok])]
    age = (issue - ends[last]) / pd.Timedelta(hours=1)
    if age > LAG_MAX_AGE_H:
        return float(age), np.nan, np.nan
    return float(age), float(hist["p"].iloc[last]), float(hist["ws"].iloc[last])


def prev_runs_features(prev_runs: pd.DataFrame | None, issue: pd.Timestamp,
                       targets: pd.DatetimeIndex) -> pd.DataFrame:
    """pr_<model>_ws100_d<N> on targets, NaN where the run behind previous_dayN was not yet published."""
    out = pd.DataFrame(np.nan, index=targets, columns=PREV_FEATURES)
    if prev_runs is None or len(prev_runs) == 0:
        return out
    frame = prev_runs.assign(valid_utc=pd.to_datetime(prev_runs["valid_utc"], utc=True))
    for model, group in frame[frame["model"].isin(PREV_MODELS)].groupby("model"):
        g = group.drop_duplicates("valid_utc").set_index("valid_utc").reindex(targets)
        for day in PREV_DAYS:
            column = f"{PREV_VARIABLE}_previous_day{day}"
            if column not in g:
                continue
            published = targets - pd.Timedelta(hours=24 * day - PREV_AVAIL_LAG_H) <= issue
            out[f"pr_{model}_ws100_d{day}"] = np.where(published, g[column].to_numpy(dtype=float), np.nan)
    return out


def build_features(nwp: pd.DataFrame, issue_time, turbine_id, scada_hist: pd.DataFrame | None = None,
                   prev_runs: pd.DataFrame | None = None, horizon_h: int = HORIZON_H) -> pd.DataFrame:
    """KEYS + FEATURES for the horizon_h hours starting at issue_time, one turbine, one NWP run."""
    issue = _utc_hour(issue_time)
    turbine = turbine_key(turbine_id)
    raw, run_init = _nwp_window(nwp, issue, horizon_h)
    targets = raw.index

    ws100, ws10 = raw["wind_speed_100m"].to_numpy(), raw["wind_speed_10m"].to_numpy()
    temp_k = raw["temperature_2m"].to_numpy() + 273.15
    rho = raw["surface_pressure"].to_numpy() * 100.0 / (R_DRY * temp_k)
    dir_sin, dir_cos = _cyc(raw["wind_direction_100m"].to_numpy(), 360.0)
    hour_sin, hour_cos = _cyc(targets.hour, 24.0)
    doy_sin, doy_cos = _cyc(targets.dayofyear - 1, 365.25)

    out = pd.DataFrame({
        "issue_time_utc": issue,
        "valid_utc": targets,
        "run_init_utc": run_init,
        "horizon_h": np.arange(horizon_h),
        "turbine": turbine,
        "ws100": ws100,
        "ws80": raw["wind_speed_80m"].to_numpy(),
        "ws10": ws10,
        "ws100_cubed": ws100 ** 3,
        "dir100_sin": dir_sin,
        "dir100_cos": dir_cos,
        "temperature_2m": raw["temperature_2m"].to_numpy(),
        "surface_pressure": raw["surface_pressure"].to_numpy(),
        "rho": rho,
        "ws100_rho": ws100 * np.cbrt(rho / RHO_0),
        "shear_ln": np.log(np.maximum(ws100, 0.1) / np.maximum(ws10, 0.1)),
        "lead_h": ((targets - run_init) / pd.Timedelta(hours=1)).astype(int),
        "run_cycle": run_init.hour,
        "hour_sin": hour_sin, "hour_cos": hour_cos, "doy_sin": doy_sin, "doy_cos": doy_cos,
    }, index=pd.RangeIndex(horizon_h))

    prev = prev_runs_features(prev_runs, issue, targets).reset_index(drop=True)
    out[PREV_FEATURES] = prev
    freshest = pd.DataFrame({
        m: prev[f"pr_{m}_ws100_d1"].fillna(prev[f"pr_{m}_ws100_d2"]) for m in PREV_MODELS
    })
    members = pd.concat([out["ws100"].rename("single"), freshest], axis=1)
    out["ws100_models_mean"] = members.mean(axis=1)
    out["ws100_models_std"] = members.std(axis=1, ddof=0).where(members.count(axis=1) > 1)
    out["n_models"] = members.count(axis=1)

    out["scada_age_h"], out["p_lag"], out["ws_lag"] = scada_state(scada_hist, issue)
    out["turbine_id"] = TURBINE_CODES[turbine]
    return out[[*KEYS, *FEATURES]]


def mask_lags(features: pd.DataFrame, frac: float = 0.3, seed: int = 0) -> pd.DataFrame:
    """Training-only: drop SCADA lags for a random frac of issues (test-window SCADA age reaches 28 days)."""
    out = features.copy()
    issues = out["issue_time_utc"].unique()
    rng = np.random.default_rng(seed)
    drop = set(rng.choice(issues, size=int(round(frac * len(issues))), replace=False))
    out.loc[out["issue_time_utc"].isin(drop), LAG_FEATURES] = np.nan
    return out


def build_training_frame(runs: pd.DataFrame, scada: pd.DataFrame | None = None,
                         prev_runs: pd.DataFrame | None = None, turbines=("T1", "T2")) -> pd.DataFrame:
    """LOC-18 dump (one run per issue_day, issue 18:00 UTC) -> features for every issue and turbine.

    scada: processed long SCADA (ts, turbine_id, p, ws, ...); target `p` is attached when present.
    """
    rows = []
    by_turbine = {}
    if scada is not None:
        for turbine, g in scada.groupby("turbine_id"):
            by_turbine[str(turbine)] = g.set_index("ts").sort_index()
    for issue_day, run in runs.groupby("issue_day"):
        issue = pd.Timestamp(issue_day).tz_localize("UTC") if pd.Timestamp(issue_day).tzinfo is None \
            else pd.Timestamp(issue_day).tz_convert("UTC")
        issue = issue.normalize() + pd.Timedelta(hours=clock.ISSUE_HOUR_UTC)
        for turbine in turbines:
            hist = by_turbine.get(turbine)
            rows.append(build_features(run, issue, turbine, hist, prev_runs))
    frame = pd.concat(rows, ignore_index=True)
    if scada is None:
        return frame
    target = scada[["ts", "turbine_id", "p"]].rename(columns={"ts": "valid_utc", "turbine_id": "turbine"})
    target = target.astype({"valid_utc": frame["valid_utc"].dtype, "turbine": object})
    return frame.merge(target, on=["valid_utc", "turbine"], how="left", validate="many_to_one")


def schema_of(features: pd.DataFrame) -> dict[str, str]:
    """Column -> dtype kind; used to compare train and serve frames."""
    return {c: features[c].dtype.kind for c in [*KEYS, *FEATURES]}
