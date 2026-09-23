"""LOC-10: leak-safe LightGBM spike on lead-aligned archived NWP features.

The primary input is the one-run-per-issue-day ECMWF IFS archive produced by
``windagent.dump_single_runs_train``.  ``Previous Runs`` values are secondary
features and are selected with the same publication-lag rule for every row: use
``previous_day1`` only when its underlying run was public at issue time, otherwise
fall back to ``previous_day2``.

This module intentionally implements the point-estimate spike only.  Quantile
models and the stable serving contract belong to LOC-11 and LOC-12.

Run the complete offline spike with::

    python -m windagent.model.v1
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lightgbm as lgb
import numpy as np
import pandas as pd

from windagent.eval.metrics import evaluate_forecast
from windagent.model import v0

ROOT: Final = Path(__file__).resolve().parents[2]
SINGLE_RUNS_PATH: Final = ROOT / "data/nwp/single_runs_ecmwf_ifs_train.parquet"
PREVIOUS_RUNS_PATH: Final = ROOT / "data/baselines/previous_runs_ws100.parquet"
SCADA_PATH: Final = ROOT / "data/processed/scada_hourly.parquet"
MODEL_PATH: Final = ROOT / "models/lightgbm_v1.txt"
METADATA_PATH: Final = ROOT / "models/lightgbm_v1.metadata.json"
REPORT_PATH: Final = ROOT / "reports/lightgbm_v1.csv"
DOC_PATH: Final = ROOT / "docs/research/lightgbm-v1.md"

MODEL_VERSION: Final = "lightgbm-v1"
ISSUE_HOUR_UTC: Final = 18
R_D: Final = 287.05
# v0 is a strong, low-variance physical anchor.  The fixed blend was chosen as a
# conservative spike default rather than replacing the already-good model wholesale.
LIGHTGBM_WEIGHT: Final = 0.4


@dataclass(frozen=True)
class Holdout:
    """Issue-day bounds for one local-calendar evaluation window."""

    name: str
    issue_start: str
    issue_end: str


HOLDOUTS: Final = (
    # A forecast for local 2025-02-01 is issued at 2025-01-31 18:00 UTC.
    Holdout("feb2025", "2025-01-31", "2025-02-28"),
    Holdout("jan2026", "2025-12-31", "2026-01-31"),
)

PREVIOUS_MODELS: Final = {
    "icon_global": 4,
    "ecmwf_ifs025": 8,
}

FEATURES: Final = (
    "ws100",
    "ws80",
    "ws10",
    "gust10",
    "temperature_2m",
    "surface_pressure",
    "ws100_sq",
    "ws100_cube",
    "ws100_lag1",
    "ws100_lead1",
    "ws100_tendency2",
    "wind_u100",
    "wind_v100",
    "wind_dir_sin",
    "wind_dir_cos",
    "air_density",
    "density_normalized_ws100",
    "shear_100_10",
    "nwp_lead_h",
    "hours_since_issue",
    "run_cycle_sin",
    "run_cycle_cos",
    "target_hour_sin",
    "target_hour_cos",
    "target_doy_sin",
    "target_doy_cos",
    "turbine_code",
    "prev_icon_global_ws100",
    "prev_icon_global_age_days",
    "prev_ecmwf_ifs025_ws100",
    "prev_ecmwf_ifs025_age_days",
    "ensemble_ws100_mean",
    "ensemble_ws100_spread",
)

DEFAULT_PARAMS: Final = {
    "objective": "regression_l1",
    "metric": "l1",
    "num_iterations": 500,
    "learning_rate": 0.035,
    "num_leaves": 31,
    "max_depth": -1,
    "min_data_in_leaf": 80,
    "bagging_fraction": 0.9,
    "bagging_freq": 1,
    "feature_fraction": 0.9,
    "lambda_l1": 0.05,
    "lambda_l2": 0.5,
    "seed": 75766,
    "num_threads": 1,
    "deterministic": True,
    "force_col_wise": True,
    "verbosity": -1,
}


def _require_columns(frame: pd.DataFrame, required: set[str], source: str) -> None:
    missing = required - set(frame)
    if missing:
        raise ValueError(f"{source} misses columns: {sorted(missing)}")


def _issue_time(rows: pd.DataFrame) -> pd.Series:
    """Issue time per row: the dayahead 18:00 UTC, or an explicit issue_time_utc (LOC-12 serving, reissues)."""
    if "issue_time_utc" in rows:
        return pd.to_datetime(rows["issue_time_utc"], utc=True)
    return pd.to_datetime(rows["issue_day"], utc=True) + pd.Timedelta(hours=ISSUE_HOUR_UTC)


def _holdout_mask(issue_day: pd.Series, holdout: Holdout) -> pd.Series:
    days = pd.to_datetime(issue_day).dt.tz_localize(None)
    return days.ge(holdout.issue_start) & days.lt(holdout.issue_end)


def _all_holdout_mask(issue_day: pd.Series) -> pd.Series:
    mask = pd.Series(False, index=issue_day.index)
    for holdout in HOLDOUTS:
        mask |= _holdout_mask(issue_day, holdout)
    return mask


def _load_single_runs(path: Path = SINGLE_RUNS_PATH) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    required = {
        "run_init_utc",
        "valid_utc",
        "lead_h",
        "wind_speed_100m",
        "wind_speed_80m",
        "wind_speed_10m",
        "wind_direction_100m",
        "wind_gusts_10m",
        "temperature_2m",
        "surface_pressure",
        "run_cycle",
        "issue_day",
        "in_dayahead_window",
    }
    _require_columns(frame, required, path.name)
    frame = frame.loc[frame["in_dayahead_window"]].copy()
    frame["run_init_utc"] = pd.to_datetime(frame["run_init_utc"], utc=True)
    frame["valid_utc"] = pd.to_datetime(frame["valid_utc"], utc=True)
    frame["issue_day"] = pd.to_datetime(frame["issue_day"])
    frame = frame.sort_values(["issue_day", "valid_utc"], ignore_index=True)
    if frame.duplicated(["issue_day", "valid_utc"]).any():
        raise ValueError("Single Runs contains duplicate issue-day/valid-time rows")
    counts = frame.groupby("issue_day", observed=True).size()
    if not counts.eq(48).all():
        raise ValueError("every retained Single Run issue day must contain 48 hours")
    return frame


def _load_previous_runs(path: Path = PREVIOUS_RUNS_PATH) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    required = {
        "model",
        "valid_utc",
        "ws100_previous_day1",
        "ws100_previous_day2",
    }
    _require_columns(frame, required, path.name)
    frame["valid_utc"] = pd.to_datetime(frame["valid_utc"], utc=True)
    return frame.sort_values(["model", "valid_utc"], ignore_index=True)


def _select_previous_run(
    rows: pd.DataFrame,
    previous: pd.DataFrame,
    *,
    model: str,
    availability_lag_h: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return leak-safe ws100 and source age (1 or 2 days) for each row."""
    model_frame = previous.loc[previous["model"] == model].set_index("valid_utc")
    if model_frame.index.has_duplicates:
        raise ValueError(f"Previous Runs contains duplicate timestamps for {model}")
    valid = pd.DatetimeIndex(rows["valid_utc"])
    day1 = model_frame["ws100_previous_day1"].reindex(valid).to_numpy(float)
    day2 = model_frame["ws100_previous_day2"].reindex(valid).to_numpy(float)

    issue_time = _issue_time(rows)
    previous_day1_run = rows["valid_utc"].dt.floor("6h") - pd.Timedelta(days=1)
    day1_available = previous_day1_run + pd.Timedelta(
        hours=availability_lag_h
    ) <= issue_time
    selected = np.where(day1_available, day1, day2)
    age_days = np.where(day1_available, 1.0, 2.0)
    return selected, age_days


def _base_features(
    single_runs: pd.DataFrame, previous_runs: pd.DataFrame
) -> pd.DataFrame:
    rows = single_runs.copy()
    issue_time = _issue_time(rows)
    hours_since_issue = (
        (rows["valid_utc"] - issue_time).dt.total_seconds() / 3600
    )
    if not hours_since_issue.between(0, 47).all():
        raise ValueError("Single Runs rows are not aligned to the 48-hour issue window")

    radians = np.deg2rad(rows["wind_direction_100m"].to_numpy(float))
    ws100 = rows["wind_speed_100m"].to_numpy(float)
    temperature_k = rows["temperature_2m"].to_numpy(float) + 273.15
    density = rows["surface_pressure"].to_numpy(float) * 100 / (
        R_D * temperature_k
    )
    cycle_radians = 2 * np.pi * rows["run_cycle"].to_numpy(float) / 24
    target_local = rows["valid_utc"] + pd.Timedelta(hours=6)
    hour_radians = 2 * np.pi * target_local.dt.hour.to_numpy(float) / 24
    doy_radians = 2 * np.pi * (
        target_local.dt.dayofyear.to_numpy(float) - 1
    ) / 365.25

    features = pd.DataFrame(index=rows.index)
    features["ws100"] = ws100
    features["ws80"] = rows["wind_speed_80m"].to_numpy(float)
    features["ws10"] = rows["wind_speed_10m"].to_numpy(float)
    features["gust10"] = rows["wind_gusts_10m"].to_numpy(float)
    features["temperature_2m"] = rows["temperature_2m"].to_numpy(float)
    features["surface_pressure"] = rows["surface_pressure"].to_numpy(float)
    features["ws100_sq"] = ws100**2
    features["ws100_cube"] = ws100**3
    grouped_ws = rows.groupby("issue_day", sort=False)["wind_speed_100m"]
    features["ws100_lag1"] = grouped_ws.shift(1)
    features["ws100_lead1"] = grouped_ws.shift(-1)
    features["ws100_tendency2"] = (
        features["ws100_lead1"] - features["ws100_lag1"]
    )
    features["wind_u100"] = -ws100 * np.sin(radians)
    features["wind_v100"] = -ws100 * np.cos(radians)
    features["wind_dir_sin"] = np.sin(radians)
    features["wind_dir_cos"] = np.cos(radians)
    features["air_density"] = density
    features["density_normalized_ws100"] = ws100 * (density / 1.225) ** (1 / 3)
    with np.errstate(divide="ignore", invalid="ignore"):
        features["shear_100_10"] = np.log(
            rows["wind_speed_100m"].to_numpy(float)
            / rows["wind_speed_10m"].to_numpy(float)
        ) / np.log(10)
    features["shear_100_10"] = features["shear_100_10"].replace(
        [np.inf, -np.inf], np.nan
    )
    features["nwp_lead_h"] = rows["lead_h"].to_numpy(float)
    features["hours_since_issue"] = hours_since_issue.to_numpy(float)
    features["run_cycle_sin"] = np.sin(cycle_radians)
    features["run_cycle_cos"] = np.cos(cycle_radians)
    features["target_hour_sin"] = np.sin(hour_radians)
    features["target_hour_cos"] = np.cos(hour_radians)
    features["target_doy_sin"] = np.sin(doy_radians)
    features["target_doy_cos"] = np.cos(doy_radians)

    ensemble = [features["ws100"].to_numpy(float)]
    for model, lag in PREVIOUS_MODELS.items():
        values, ages = _select_previous_run(
            rows,
            previous_runs,
            model=model,
            availability_lag_h=lag,
        )
        features[f"prev_{model}_ws100"] = values
        features[f"prev_{model}_age_days"] = ages
        ensemble.append(values)
    ensemble_values = np.column_stack(ensemble)
    features["ensemble_ws100_mean"] = np.nanmean(ensemble_values, axis=1)
    features["ensemble_ws100_spread"] = np.nanmax(
        ensemble_values, axis=1
    ) - np.nanmin(ensemble_values, axis=1)
    return features


def build_dataset(
    *,
    single_runs_path: Path = SINGLE_RUNS_PATH,
    previous_runs_path: Path = PREVIOUS_RUNS_PATH,
    scada_path: Path = SCADA_PATH,
) -> pd.DataFrame:
    """Build the pooled T1/T2 modelling frame with one schema for all windows."""
    single_runs = _load_single_runs(single_runs_path)
    previous_runs = _load_previous_runs(previous_runs_path)
    base = _base_features(single_runs, previous_runs)
    metadata = single_runs[
        ["issue_day", "run_init_utc", "valid_utc", "lead_h"]
    ].copy()
    metadata["forecast_lead_h"] = (
        (metadata["valid_utc"] - (
            pd.to_datetime(metadata["issue_day"], utc=True)
            + pd.Timedelta(hours=ISSUE_HOUR_UTC)
        )).dt.total_seconds()
        / 3600
        + 1
    ).astype("int8")

    scada = pd.read_parquet(scada_path)
    required_scada = {
        "ts",
        "turbine_id",
        "p",
        "is_clean",
        "range",
        "frozen",
        "outage",
        "curve_resid",
        "curtail",
        "icing",
        "t1_outage",
    }
    _require_columns(scada, required_scada, scada_path.name)
    scada["ts"] = pd.to_datetime(scada["ts"], utc=True)

    parts = []
    for code, turbine_id in enumerate(("T1", "T2")):
        part = pd.concat(
            [metadata.reset_index(drop=True), base.reset_index(drop=True)], axis=1
        )
        part["turbine_id"] = turbine_id
        part["turbine_code"] = float(code)
        facts = scada.loc[scada["turbine_id"] == turbine_id].drop(
            columns="turbine_id"
        )
        part = part.merge(
            facts,
            how="left",
            left_on="valid_utc",
            right_on="ts",
            validate="many_to_one",
        ).drop(columns="ts")
        parts.append(part)
    frame = pd.concat(parts, ignore_index=True)
    _require_columns(frame, set(FEATURES), "feature builder")
    return frame.sort_values(
        ["issue_day", "turbine_id", "forecast_lead_h"], ignore_index=True
    )


def training_rows(frame: pd.DataFrame, *, exclude_holdouts: bool = True) -> pd.Series:
    """Rows eligible for fitting: finite clean targets and optional holdout removal."""
    mask = frame["p"].notna() & frame["is_clean"].fillna(False).astype(bool)
    if exclude_holdouts:
        mask &= ~_all_holdout_mask(frame["issue_day"])
    return mask


def fit_model(
    frame: pd.DataFrame,
    *,
    exclude_holdouts: bool = True,
    **overrides: object,
) -> lgb.Booster:
    mask = training_rows(frame, exclude_holdouts=exclude_holdouts)
    if mask.sum() < 1_000:
        raise ValueError(f"not enough clean training rows: {int(mask.sum())}")
    params = {**DEFAULT_PARAMS, **overrides}
    num_iterations = int(params.pop("num_iterations"))
    data = lgb.Dataset(
        frame.loc[mask, FEATURES],
        label=frame.loc[mask, "p"],
        feature_name=list(FEATURES),
        free_raw_data=False,
    )
    return lgb.train(params, data, num_boost_round=num_iterations)


def predict(model: lgb.Booster, frame: pd.DataFrame) -> np.ndarray:
    tree_prediction = np.asarray(model.predict(frame.loc[:, FEATURES]), dtype=float)
    anchor = v0.predict_series(frame["ws100"].to_numpy(float))["p50"].to_numpy()
    prediction = LIGHTGBM_WEIGHT * tree_prediction + (1 - LIGHTGBM_WEIGHT) * anchor
    return np.clip(prediction, 0.0, 1.0)


def _score(
    frame: pd.DataFrame,
    prediction: np.ndarray,
    *,
    window: str,
    turbine_id: str,
    model_name: str,
) -> pd.DataFrame:
    evaluation = frame.copy()
    evaluation["actual"] = evaluation["p"]
    evaluation["prediction"] = prediction
    rows = []
    for mode in ("all", "weather_explainable"):
        result = evaluate_forecast(
            evaluation,
            actual_col="actual",
            prediction_col="prediction",
            lead_col="forecast_lead_h",
            quantile_cols={},
            mode=mode,
            include_per_lead=False,
        )
        result.insert(0, "model", model_name)
        result.insert(0, "turbine_id", turbine_id)
        result.insert(0, "window", window)
        rows.append(result)
    return pd.concat(rows, ignore_index=True)


def evaluate(model: lgb.Booster, frame: pd.DataFrame) -> pd.DataFrame:
    """Score v1 and the committed v0 on identical holdout rows."""
    results = []
    for holdout in HOLDOUTS:
        window_rows = frame.loc[_holdout_mask(frame["issue_day"], holdout)].copy()
        for turbine_id in ("T1", "T2"):
            rows = window_rows.loc[window_rows["turbine_id"] == turbine_id].copy()
            v1_prediction = predict(model, rows)
            v0_prediction = v0.predict_series(rows["ws100"].to_numpy(float))["p50"]
            results.append(
                _score(
                    rows,
                    v1_prediction,
                    window=holdout.name,
                    turbine_id=turbine_id,
                    model_name=MODEL_VERSION,
                )
            )
            results.append(
                _score(
                    rows,
                    v0_prediction.to_numpy(float),
                    window=holdout.name,
                    turbine_id=turbine_id,
                    model_name=v0.MODEL_VERSION,
                )
            )
    report = pd.concat(results, ignore_index=True)
    reference = report.loc[report["model"] == v0.MODEL_VERSION].set_index(
        ["window", "turbine_id", "mode", "scope"]
    )["nmae"]
    report["skill_vs_v0_pct"] = [
        100 * (reference.loc[(row.window, row.turbine_id, row.mode, row.scope)] - row.nmae)
        / reference.loc[(row.window, row.turbine_id, row.mode, row.scope)]
        for row in report.itertuples()
    ]
    return report


def _feature_importance(model: lgb.Booster) -> list[dict[str, object]]:
    values = model.feature_importance(importance_type="gain")
    pairs = sorted(zip(FEATURES, values, strict=True), key=lambda item: -item[1])
    total = float(np.sum(values))
    return [
        {
            "feature": feature,
            "gain": float(gain),
            "gain_share": float(gain / total) if total else 0.0,
        }
        for feature, gain in pairs
    ]


def _write_document(
    report: pd.DataFrame,
    metadata: dict[str, object],
    path: Path = DOC_PATH,
) -> None:
    all_rows = report.loc[
        (report["mode"] == "all") & (report["scope"] == "all")
    ]
    lines = [
        "# LOC-10 — LightGBM v1",
        "",
        "Leak-safe point-model spike on pooled T1/T2 rows. The primary features "
        "come from one explicit ECMWF IFS Single Run per issue; Previous Runs "
        "features use day1 only after that underlying cycle is public, otherwise "
        "day2. February 2025 and January 2026 are excluded from fitting.",
        "",
        "The published point estimate is a conservative 40% LightGBM / 60% v0 "
        "blend. This keeps the physical MOS + power-curve anchor while the tree "
        "adds multi-model, direction, density, calendar and lead corrections.",
        "",
        "| Window | Turbine | Model | n | MAE | RMSE | Bias | Skill vs v0 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in all_rows.sort_values(["window", "turbine_id", "model"]).itertuples():
        lines.append(
            f"| {row.window} | {row.turbine_id} | `{row.model}` | {row.n:,} | "
            f"{row.nmae:.3f} | {row.nrmse:.3f} | {row.nbias:+.3f} | "
            f"{row.skill_vs_v0_pct:+.1f}% |"
        )
    lines.extend(
        [
            "",
            "The report also contains h1–24 / h25–48 and "
            "weather-explainable slices. All values are normalized by turbine "
            "nameplate capacity.",
            "",
            "## Top feature importance",
            "",
            "| Feature | Gain share |",
            "|---|---:|",
        ]
    )
    for item in metadata["feature_importance"][:12]:
        lines.append(f"| `{item['feature']}` | {item['gain_share']:.1%} |")
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "```bash",
            "uv run --frozen python -m windagent.model.v1",
            "```",
            "",
            "This command is offline; it reads only committed Parquet artifacts.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def run(
    *,
    model_path: Path = MODEL_PATH,
    metadata_path: Path = METADATA_PATH,
    report_path: Path = REPORT_PATH,
    doc_path: Path = DOC_PATH,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Train/evaluate the honest spike, then fit and persist the final model."""
    frame = build_dataset()
    evaluation_model = fit_model(frame, exclude_holdouts=True)
    report = evaluate(evaluation_model, frame)

    final_model = fit_model(frame, exclude_holdouts=False)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    final_model.save_model(model_path)
    metadata = {
        "model_version": MODEL_VERSION,
        "objective": DEFAULT_PARAMS["objective"],
        "prediction_blend": {
            "lightgbm_weight": LIGHTGBM_WEIGHT,
            "v0_weight": 1 - LIGHTGBM_WEIGHT,
            "v0_model_version": v0.MODEL_VERSION,
        },
        "features": list(FEATURES),
        "params": DEFAULT_PARAMS,
        "n_rows": int(len(frame)),
        "n_training_rows_evaluation": int(training_rows(frame).sum()),
        "n_training_rows_final": int(
            training_rows(frame, exclude_holdouts=False).sum()
        ),
        "holdouts": [holdout.__dict__ for holdout in HOLDOUTS],
        "feature_importance": _feature_importance(evaluation_model),
        "inputs": {
            "single_runs": str(SINGLE_RUNS_PATH.relative_to(ROOT)),
            "previous_runs": str(PREVIOUS_RUNS_PATH.relative_to(ROOT)),
            "scada": str(SCADA_PATH.relative_to(ROOT)),
        },
        "artifact_note": "The saved model is refit on every clean row after honest "
        "holdout scoring; the report is produced by a separate model that excludes "
        "both holdouts.",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(report_path, index=False)
    _write_document(report, metadata, doc_path)
    return report, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="evaluate without replacing model and report artifacts",
    )
    args = parser.parse_args()
    if args.no_write:
        frame = build_dataset()
        report = evaluate(fit_model(frame), frame)
    else:
        report, _ = run()
    summary = report.loc[
        (report["mode"] == "all") & (report["scope"] == "all")
    ]
    print(
        summary[
            [
                "window",
                "turbine_id",
                "model",
                "n",
                "nmae",
                "nrmse",
                "nbias",
                "skill_vs_v0_pct",
            ]
        ].to_string(index=False)
    )


def predict_power(request: dict) -> dict:
    """LOC-12 agent adapter: `--model-adapter windagent.model.v1:predict_power` (see windagent.model.serve)."""
    from windagent.model.serve import predict_power as serve

    return serve(request)


if __name__ == "__main__":
    main()
