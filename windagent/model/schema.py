"""LOC-12 feature contract for the LOC-10 model: one build_features() for training and serving.

    build_features(nwp, issue_time, turbine_id, prev_runs=None) -> DataFrame[KEYS + FEATURES]

FEATURES and the arithmetic are windagent.model.v1's (_base_features), so a served frame is the
training frame of the same run; this module only turns one Single Run into the rows v1 expects
and adds the as-of checks that the batch training path gets from the LOC-18 dump.

Inputs
- nwp: one ecmwf_ifs Single Run, columns run_init_utc, valid_utc and RAW_NWP (Open-Meteo names,
  m/s, deg, degC, hPa): a group of data/nwp/single_runs_ecmwf_ifs_*.parquet or a live response.
- prev_runs: Previous Runs ws100 in the long form of data/baselines/previous_runs_ws100.parquet
  (model, valid_utc, ws100_previous_day1, ws100_previous_day2). v1 picks day1 or day2 by
  publication lag; absent -> NaN.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from windagent import clock
from windagent.model import v1

SCHEMA_VERSION = "1.0"
FEATURES = list(v1.FEATURES)
KEYS = ["issue_time_utc", "valid_utc", "run_init_utc", "forecast_lead_h", "turbine_id"]
RAW_NWP = (
    "wind_speed_100m",
    "wind_speed_80m",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_100m",
    "temperature_2m",
    "surface_pressure",
)
PREV_COLUMNS = ("model", "valid_utc", "ws100_previous_day1", "ws100_previous_day2")
TURBINE_CODES = {"T1": 0.0, "T2": 1.0}  # v1.build_dataset: enumerate(("T1", "T2"))

# Where every raw input comes from in live mode; tests check each feature traces to one of these.
LIVE_SOURCES = {
    "single_runs": {"url": "https://api.open-meteo.com/v1/forecast", "models": ("ecmwf_ifs",),
                    "variables": RAW_NWP},
    "previous_runs": {"url": "https://previous-runs-api.open-meteo.com/v1/forecast",
                      "models": tuple(v1.PREVIOUS_MODELS),
                      "variables": ("wind_speed_100m_previous_day1", "wind_speed_100m_previous_day2")},
}
_PREV = ["wind_speed_100m_previous_day1", "wind_speed_100m_previous_day2"]
FEATURE_SOURCES = {
    "ws100": ["wind_speed_100m"], "ws80": ["wind_speed_80m"], "ws10": ["wind_speed_10m"],
    "gust10": ["wind_gusts_10m"], "temperature_2m": ["temperature_2m"],
    "surface_pressure": ["surface_pressure"],
    **{f: ["wind_speed_100m"] for f in ("ws100_sq", "ws100_cube", "ws100_lag1", "ws100_lead1",
                                        "ws100_tendency2")},
    **{f: ["wind_speed_100m", "wind_direction_100m"] for f in ("wind_u100", "wind_v100")},
    "wind_dir_sin": ["wind_direction_100m"], "wind_dir_cos": ["wind_direction_100m"],
    "air_density": ["surface_pressure", "temperature_2m"],
    "density_normalized_ws100": ["wind_speed_100m", "surface_pressure", "temperature_2m"],
    "shear_100_10": ["wind_speed_100m", "wind_speed_10m"],
    **{f: [] for f in ("nwp_lead_h", "hours_since_issue", "run_cycle_sin", "run_cycle_cos",
                       "target_hour_sin", "target_hour_cos", "target_doy_sin", "target_doy_cos",
                       "turbine_code")},
    **{f"prev_{m}_{s}": _PREV for m in v1.PREVIOUS_MODELS for s in ("ws100", "age_days")},
    "ensemble_ws100_mean": ["wind_speed_100m", *_PREV],
    "ensemble_ws100_spread": ["wind_speed_100m", *_PREV],
}


def turbine_key(turbine_id) -> str:
    """'T1' | 'turbine_1' | 1 -> 'T1'."""
    key = "T" + str(turbine_id).strip().lower().replace("turbine_", "").lstrip("t")
    if key not in TURBINE_CODES:
        raise ValueError(f"INVALID_INPUT: unknown turbine_id={turbine_id!r}")
    return key


def _utc_hour(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if ts != ts.floor("h"):
        raise ValueError(f"INVALID_INPUT: issue {ts} is not on the hourly grid")
    return ts


def _rows(nwp: pd.DataFrame, issue: pd.Timestamp, horizon_h: int) -> pd.DataFrame:
    """One run -> the rows v1._base_features expects (like v1._load_single_runs for one issue day)."""
    missing = [c for c in ("run_init_utc", "valid_utc", *RAW_NWP) if c not in nwp.columns]
    if missing:
        raise ValueError(f"INVALID_INPUT: NWP frame lacks {missing}")
    runs = pd.to_datetime(nwp["run_init_utc"], utc=True).unique()
    if len(runs) != 1:
        raise ValueError(f"INVALID_INPUT: expected one NWP run, got {len(runs)}")
    run_init = pd.Timestamp(runs[0])
    clock.assert_as_of(issue.to_pydatetime(), run_init.to_pydatetime(), [issue.to_pydatetime()])
    frame = nwp.assign(valid_utc=pd.to_datetime(nwp["valid_utc"], utc=True)).set_index("valid_utc")
    targets = pd.date_range(issue, periods=horizon_h, freq="h", name="valid_utc")
    window = frame.reindex(targets)[list(RAW_NWP)].astype(float)
    if window.isna().any(axis=None):
        bad = window.index[window.isna().any(axis=1)]
        raise ValueError(f"INCOMPLETE_HORIZON: run {run_init} lacks values at {len(bad)} hours from {bad[0]}")
    rows = window.reset_index()
    rows["run_init_utc"] = run_init
    rows["lead_h"] = ((rows["valid_utc"] - run_init) / pd.Timedelta(hours=1)).astype("int64")
    rows["run_cycle"] = run_init.hour
    rows["issue_day"] = issue.tz_localize(None).normalize()
    rows["issue_time_utc"] = issue  # v1._issue_time: dayahead 18:00 or a 20:00 reissue alike
    return rows


def build_features(nwp: pd.DataFrame, issue_time, turbine_id, prev_runs: pd.DataFrame | None = None,
                   horizon_h: int = clock.HORIZON_H) -> pd.DataFrame:
    """KEYS + FEATURES for horizon_h hours from issue_time, one turbine, one NWP run."""
    if not 1 <= horizon_h <= clock.HORIZON_H:
        raise ValueError(f"INVALID_INPUT: horizon_h must be 1..{clock.HORIZON_H}")
    issue = _utc_hour(issue_time)
    turbine = turbine_key(turbine_id)
    # v1 computes ws100_lag1/lead1 inside the 48-hour issue window, so build all 48 and cut after.
    rows = _rows(nwp, issue, clock.HORIZON_H)
    prev = pd.DataFrame(columns=PREV_COLUMNS) if prev_runs is None else prev_runs[list(PREV_COLUMNS)]
    prev = prev.astype({"ws100_previous_day1": float, "ws100_previous_day2": float})
    prev = prev.assign(valid_utc=pd.to_datetime(prev["valid_utc"], utc=True))
    with warnings.catch_warnings():  # all-NaN ensemble members when Previous Runs are absent
        warnings.simplefilter("ignore", RuntimeWarning)
        base = v1._base_features(rows, prev)
    base["turbine_code"] = TURBINE_CODES[turbine]
    keys = pd.DataFrame({
        "issue_time_utc": issue,
        "valid_utc": rows["valid_utc"],
        "run_init_utc": rows["run_init_utc"],
        "forecast_lead_h": np.arange(1, clock.HORIZON_H + 1, dtype="int8"),  # v1: 1..48
        "turbine_id": turbine,
    })
    return pd.concat([keys, base[FEATURES]], axis=1).iloc[:horizon_h].reset_index(drop=True)


def schema_of(features: pd.DataFrame) -> dict[str, str]:
    """Column -> dtype kind; used to compare train and serve frames."""
    return {c: features[c].dtype.kind for c in [*KEYS, *FEATURES]}
