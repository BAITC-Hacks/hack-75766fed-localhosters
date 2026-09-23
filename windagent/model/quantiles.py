"""LOC-11: calibrated LightGBM distribution for normalized wind power.

The training rows, feature order and holdout windows are exactly the LOC-10 v1
ones.  Three quantile boosters estimate P10/P50/P90 and one L2 booster provides
the conditional mean used when ``POINT_ESTIMATE=mean``.

Run the complete offline experiment with::

    python -m windagent.model.quantiles
"""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path
from typing import Final

import lightgbm as lgb
import numpy as np
import pandas as pd

from windagent.eval.metrics import evaluate_forecast
from windagent.model import v1

ROOT: Final = v1.ROOT
MODEL_DIR: Final = ROOT / "models/lgbm_q_v1"
MODEL_PATHS: Final = {
    "p10": MODEL_DIR / "p10.txt",
    "p50": MODEL_DIR / "p50.txt",
    "p90": MODEL_DIR / "p90.txt",
    "mean": MODEL_DIR / "mean.txt",
}
METADATA_PATH: Final = MODEL_DIR / "metadata.json"
REPORT_PATH: Final = ROOT / "reports/lightgbm_q_v1.csv"
RELIABILITY_REPORT_PATH: Final = ROOT / "reports/lightgbm_q_v1_reliability.csv"
DOC_PATH: Final = ROOT / "docs/research/lightgbm-q-v1.md"
RELIABILITY_PATH: Final = ROOT / "docs/figures/reliability.png"

MODEL_VERSION: Final = "lightgbm-q-v1"
QUANTILES: Final = {"p10": 0.1, "p50": 0.5, "p90": 0.9}
CALIBRATION: Final = v1.Holdout("calibration", "2025-10-01", "2025-12-31")


def _params(kind: str, overrides: dict[str, object]) -> dict[str, object]:
    params = dict(v1.DEFAULT_PARAMS)
    if kind in QUANTILES:
        params.update(objective="quantile", metric="quantile", alpha=QUANTILES[kind])
    elif kind == "mean":
        params.update(objective="regression_l2", metric="l2")
    else:
        raise ValueError(f"unknown distribution model: {kind}")
    params.update(overrides)
    return params


def fit_models(
    frame: pd.DataFrame,
    *,
    exclude_holdouts: bool = True,
    exclude_calibration: bool = False,
    **overrides: object,
) -> dict[str, lgb.Booster]:
    """Fit P10/P50/P90 plus the conditional mean on the canonical v1 rows."""
    mask = v1.training_rows(frame, exclude_holdouts=exclude_holdouts)
    if exclude_calibration:
        mask &= ~v1._holdout_mask(frame["issue_day"], CALIBRATION)
    if mask.sum() < 1_000:
        raise ValueError(f"not enough clean training rows: {int(mask.sum())}")
    models = {}
    for kind in (*QUANTILES, "mean"):
        params = _params(kind, overrides)
        num_iterations = int(params.pop("num_iterations"))
        data = lgb.Dataset(
            frame.loc[mask, v1.FEATURES],
            label=frame.loc[mask, "p"],
            feature_name=list(v1.FEATURES),
            free_raw_data=False,
        )
        models[kind] = lgb.train(params, data, num_boost_round=num_iterations)
    return models


def predict(
    models: dict[str, lgb.Booster],
    frame: pd.DataFrame,
    calibration: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Return bounded, non-crossing quantiles and the conditional mean."""
    missing = set((*QUANTILES, "mean")) - set(models)
    if missing:
        raise ValueError(f"distribution models missing: {sorted(missing)}")
    features = frame.loc[:, v1.FEATURES]
    raw_quantiles = np.column_stack(
        [np.asarray(models[name].predict(features), dtype=float) for name in QUANTILES]
    )
    raw_quantiles[:, 1] += float((calibration or {}).get("median_offset", 0.0))
    ordered = np.sort(np.clip(raw_quantiles, 0.0, 1.0), axis=1)
    expansion = float((calibration or {}).get("interval_expansion", 0.0))
    ordered[:, 0] = np.clip(ordered[:, 0] - expansion, 0.0, 1.0)
    ordered[:, 2] = np.clip(ordered[:, 2] + expansion, 0.0, 1.0)
    mean = np.clip(np.asarray(models["mean"].predict(features), dtype=float), 0.0, 1.0)
    return pd.DataFrame(
        {"p10": ordered[:, 0], "p50": ordered[:, 1], "p90": ordered[:, 2], "mean": mean},
        index=frame.index,
    )


def calibrate(models: dict[str, lgb.Booster], frame: pd.DataFrame) -> dict[str, float]:
    """Split-conformal expansion robust to the noisier all-row evaluation."""
    rows = frame.loc[v1._holdout_mask(frame["issue_day"], CALIBRATION)].copy()
    raw = predict(models, rows)
    actual = rows["p"].to_numpy(float)
    lower = raw["p10"].to_numpy(float)
    upper = raw["p90"].to_numpy(float)
    finite = np.isfinite(actual) & np.isfinite(lower) & np.isfinite(upper)
    scores = np.maximum(lower[finite] - actual[finite], actual[finite] - upper[finite])
    if not len(scores):
        raise ValueError("calibration window has no finite targets")
    target_coverage = 0.9
    level = min(1.0, np.ceil((len(scores) + 1) * target_coverage) / len(scores))
    expansion = max(0.0, float(np.quantile(scores, level, method="higher")))
    median_offset = float(np.quantile(actual[finite] - raw["p50"].to_numpy(float)[finite], 0.5))
    return {
        "interval_expansion": expansion,
        "median_offset": median_offset,
        "target_coverage": target_coverage,
        "n": int(len(scores)),
    }


def evaluate(
    models: dict[str, lgb.Booster],
    frame: pd.DataFrame,
    calibration: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Evaluate median/mean points and probabilistic quality on both holdouts."""
    results = []
    for holdout in v1.HOLDOUTS:
        window = frame.loc[v1._holdout_mask(frame["issue_day"], holdout)].copy()
        for turbine_id in ("T1", "T2"):
            rows = window.loc[window["turbine_id"] == turbine_id].copy()
            distribution = predict(models, rows, calibration)
            scored = rows.assign(actual=rows["p"], **distribution.to_dict("series"))
            for point_estimate, column in (("median", "p50"), ("mean", "mean")):
                report = evaluate_forecast(
                    scored,
                    actual_col="actual",
                    prediction_col=column,
                    lead_col="forecast_lead_h",
                    quantile_cols={0.1: "p10", 0.5: "p50", 0.9: "p90"},
                    mode="all",
                    include_per_lead=False,
                )
                report.insert(0, "point_estimate", point_estimate)
                report.insert(0, "turbine_id", turbine_id)
                report.insert(0, "window", holdout.name)
                results.append(report)
    return pd.concat(results, ignore_index=True)


def reliability(
    models: dict[str, lgb.Booster],
    frame: pd.DataFrame,
    calibration: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Observed ``P(actual <= forecast quantile)`` by holdout."""
    result = []
    for holdout in v1.HOLDOUTS:
        rows = frame.loc[v1._holdout_mask(frame["issue_day"], holdout)].copy()
        distribution = predict(models, rows, calibration)
        actual = rows["p"].to_numpy(float)
        for column, nominal in QUANTILES.items():
            forecast = distribution[column].to_numpy(float)
            finite = np.isfinite(actual) & np.isfinite(forecast)
            result.append(
                {
                    "window": holdout.name,
                    "quantile": column,
                    "nominal": nominal,
                    "observed": float(np.mean(actual[finite] <= forecast[finite])),
                    "n": int(finite.sum()),
                }
            )
    return pd.DataFrame(result)


def _write_png(rows: pd.DataFrame, path: Path) -> None:
    """Write a dependency-free reliability diagram as an RGB PNG."""
    width, height = 800, 600
    pixels = bytearray([255] * width * height * 3)

    def point(x: int, y: int, color: tuple[int, int, int], radius: int = 1) -> None:
        for yy in range(max(0, y - radius), min(height, y + radius + 1)):
            for xx in range(max(0, x - radius), min(width, x + radius + 1)):
                offset = (yy * width + xx) * 3
                pixels[offset : offset + 3] = bytes(color)

    def line(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int], size: int = 1) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        error = dx + dy
        while True:
            point(x0, y0, color, size)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * error
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy

    left, top, right, bottom = 90, 50, 750, 530

    def xy(nominal: float, observed: float) -> tuple[int, int]:
        return (
            round(left + nominal * (right - left)),
            round(bottom - observed * (bottom - top)),
        )

    for value in np.linspace(0, 1, 11):
        x, y = xy(float(value), float(value))
        line(x, top, x, bottom, (230, 230, 230))
        line(left, y, right, y, (230, 230, 230))
    line(left, bottom, right, bottom, (30, 30, 30), 1)
    line(left, bottom, left, top, (30, 30, 30), 1)
    line(*xy(0, 0), *xy(1, 1), (130, 130, 130), 1)

    colors = {"feb2025": (35, 99, 200), "jan2026": (230, 120, 20)}
    for window, group in rows.groupby("window", sort=False):
        coordinates = [xy(row.nominal, row.observed) for row in group.sort_values("nominal").itertuples()]
        for first, second in zip(coordinates, coordinates[1:]):
            line(*first, *second, colors[window], 2)
        for x, y in coordinates:
            point(x, y, colors[window], 6)

    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _write_document(report: pd.DataFrame, calibration: pd.DataFrame, path: Path = DOC_PATH) -> None:
    summary = report.loc[(report["mode"] == "all") & (report["scope"] == "all")]
    lines = [
        "# LOC-11 — LightGBM P10/P50/P90",
        "",
        "Three LightGBM quantile models use the exact LOC-10 feature schema and holdout split. "
        "A fourth L2 model provides the conditional mean for RMSE-oriented submissions. "
        "Quantiles are clipped to [0, 1] and sorted row-wise to prevent crossing.",
        "",
        "| Window | Turbine | Point | n | MAE | RMSE | P10–P90 coverage | Mean pinball |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary.sort_values(["window", "turbine_id", "point_estimate"]).itertuples():
        lines.append(
            f"| {row.window} | {row.turbine_id} | {row.point_estimate} | {row.n:,} | "
            f"{row.nmae:.3f} | {row.nrmse:.3f} | {row.coverage_p10_p90:.1%} | {row.pinball_mean:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Reliability",
            "",
            "![Reliability diagram](../figures/reliability.png)",
            "",
            "Gray is perfect calibration, blue is February 2025 and orange is January 2026. "
            "The x-axis is the nominal quantile and the y-axis is the observed fraction below it.",
            "",
            "| Window | Quantile | Nominal | Observed | n |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in calibration.itertuples():
        lines.append(f"| {row.window} | {row.quantile.upper()} | {row.nominal:.0%} | {row.observed:.1%} | {row.n:,} |")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "Use `POINT_ESTIMATE=median` for MAE and `POINT_ESTIMATE=mean` for RMSE. "
            "Serving always returns P10/P50/P90; `cost` is accepted as a configuration mode "
            "and currently falls back to P50 until LOC-31 supplies imbalance coefficients.",
            "",
            "## Reproduce",
            "",
            "```bash",
            "uv run --frozen python -m windagent.model.quantiles",
            "```",
            "",
            "The command is offline and reads only committed Parquet inputs.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def run() -> tuple[pd.DataFrame, dict[str, object]]:
    frame = v1.build_dataset()
    calibration_models = fit_models(
        frame, exclude_holdouts=True, exclude_calibration=True
    )
    calibration_params = calibrate(calibration_models, frame)
    evaluation_models = fit_models(frame, exclude_holdouts=True)
    report = evaluate(evaluation_models, frame, calibration_params)
    calibration = reliability(evaluation_models, frame, calibration_params)

    final_models = fit_models(frame, exclude_holdouts=False)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, model in final_models.items():
        model.save_model(MODEL_PATHS[name])
    metadata = {
        "model_version": MODEL_VERSION,
        "features": list(v1.FEATURES),
        "models": {name: str(path.relative_to(ROOT)) for name, path in MODEL_PATHS.items()},
        "quantiles": QUANTILES,
        "params": {name: _params(name, {}) for name in MODEL_PATHS},
        "holdouts": [holdout.__dict__ for holdout in v1.HOLDOUTS],
        "calibration_window": CALIBRATION.__dict__,
        "calibration": calibration_params,
        "n_rows": int(len(frame)),
        "n_training_rows_evaluation": int(v1.training_rows(frame).sum()),
        "n_training_rows_final": int(v1.training_rows(frame, exclude_holdouts=False).sum()),
        "artifact_note": "Metrics use models excluding both holdouts; served artifacts are refit on all clean rows.",
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(REPORT_PATH, index=False)
    calibration.to_csv(RELIABILITY_REPORT_PATH, index=False)
    _write_png(calibration, RELIABILITY_PATH)
    _write_document(report, calibration)
    return report, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    frame = v1.build_dataset()
    if args.no_write:
        calibration_models = fit_models(frame, exclude_calibration=True)
        calibration_params = calibrate(calibration_models, frame)
        models = fit_models(frame)
        report = evaluate(models, frame, calibration_params)
    else:
        report, _ = run()
    print(
        report.loc[(report["mode"] == "all") & (report["scope"] == "all"), [
            "window", "turbine_id", "point_estimate", "n", "nmae", "nrmse",
            "coverage_p10_p90", "pinball_mean",
        ]].to_string(index=False)
    )


if __name__ == "__main__":
    main()
