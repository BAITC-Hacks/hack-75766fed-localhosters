"""Leak-safe deterministic and probabilistic metrics for normalized wind power.

The public entry point, :func:`evaluate_forecast`, accepts the flat frame emitted by
the backtest (one row per issue, turbine and lead).  It returns overall, 24-hour
block and per-lead metrics.  Targets and predictions are paired before quality
filtering, so every metric in one row uses the same finite observations.

Power is normalized by nameplate in this project.  The default capacity is therefore
1.0; callers evaluating MW may pass the turbine/plant nameplate explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

QUALITY_FLAGS = (
    "range",
    "frozen",
    "outage",
    "curve_resid",
    "curtail",
    "icing",
    "t1_outage",
)
VALID_MODES = ("all", "weather_explainable")
VALID_LABELS = ("left", "right")
DEFAULT_QUANTILES = {0.1: "p10", 0.5: "p50", 0.9: "p90"}


def _paired(actual: Sequence[float], predicted: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(actual, dtype=float)
    yhat = np.asarray(predicted, dtype=float)
    if y.shape != yhat.shape:
        raise ValueError("actual and predicted must have the same shape")
    valid = np.isfinite(y) & np.isfinite(yhat)
    return y[valid], yhat[valid]


def _capacity(value: float) -> float:
    value = float(value)
    if not np.isfinite(value) or value <= 0:
        raise ValueError("capacity must be a positive finite number")
    return value


def mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Mean absolute error over finite pairs."""
    y, yhat = _paired(actual, predicted)
    return float(np.mean(np.abs(yhat - y))) if len(y) else float("nan")


def rmse(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Root mean squared error over finite pairs."""
    y, yhat = _paired(actual, predicted)
    return float(np.sqrt(np.mean((yhat - y) ** 2))) if len(y) else float("nan")


def bias(predicted: Sequence[float], actual: Sequence[float]) -> float:
    """Signed forecast bias, kept prediction-first for backtest compatibility."""
    y, yhat = _paired(actual, predicted)
    return float(np.mean(yhat - y)) if len(y) else float("nan")


def skill(mae_model: float, mae_reference: float) -> float:
    """MAE skill from precomputed scalar errors, in percent."""
    model = float(mae_model)
    reference = float(mae_reference)
    if not np.isfinite(model) or not np.isfinite(reference) or reference == 0:
        return float("nan")
    return 100.0 * (reference - model) / reference


def nmae(actual: Sequence[float], predicted: Sequence[float], *, capacity: float = 1.0) -> float:
    """Normalized mean absolute error (normalization is nameplate capacity)."""
    y, yhat = _paired(actual, predicted)
    return float(np.mean(np.abs(yhat - y)) / _capacity(capacity)) if len(y) else float("nan")


def nrmse(actual: Sequence[float], predicted: Sequence[float], *, capacity: float = 1.0) -> float:
    """Normalized root mean squared error."""
    y, yhat = _paired(actual, predicted)
    return float(np.sqrt(np.mean((yhat - y) ** 2)) / _capacity(capacity)) if len(y) else float("nan")


def nbias(actual: Sequence[float], predicted: Sequence[float], *, capacity: float = 1.0) -> float:
    """Normalized signed bias, defined as forecast minus observation."""
    y, yhat = _paired(actual, predicted)
    return float(np.mean(yhat - y) / _capacity(capacity)) if len(y) else float("nan")


def skill_score(
    actual: Sequence[float],
    predicted: Sequence[float],
    reference: Sequence[float],
) -> float:
    """MAE skill in percent: ``100 * (MAE_ref - MAE) / MAE_ref``."""
    y = np.asarray(actual, dtype=float)
    yhat = np.asarray(predicted, dtype=float)
    ref = np.asarray(reference, dtype=float)
    if not (y.shape == yhat.shape == ref.shape):
        raise ValueError("actual, predicted and reference must have the same shape")
    valid = np.isfinite(y) & np.isfinite(yhat) & np.isfinite(ref)
    if not valid.any():
        return float("nan")
    mae = float(np.mean(np.abs(yhat[valid] - y[valid])))
    mae_ref = float(np.mean(np.abs(ref[valid] - y[valid])))
    if mae_ref == 0:
        return 0.0 if mae == 0 else float("-inf")
    return 100.0 * (mae_ref - mae) / mae_ref


def pinball_loss(
    actual: Sequence[float], predicted_quantile: Sequence[float], quantile: float
) -> float:
    """Mean pinball loss for one quantile in the open interval (0, 1)."""
    if not 0 < quantile < 1:
        raise ValueError("quantile must be between 0 and 1")
    y, qhat = _paired(actual, predicted_quantile)
    if not len(y):
        return float("nan")
    error = y - qhat
    return float(np.mean(np.maximum(quantile * error, (quantile - 1.0) * error)))


def interval_coverage(
    actual: Sequence[float], lower: Sequence[float], upper: Sequence[float]
) -> float:
    """Fraction of observations inside the inclusive prediction interval."""
    y = np.asarray(actual, dtype=float)
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    if not (y.shape == lo.shape == hi.shape):
        raise ValueError("actual, lower and upper must have the same shape")
    valid = np.isfinite(y) & np.isfinite(lo) & np.isfinite(hi)
    if np.any(lo[valid] > hi[valid]):
        raise ValueError("lower prediction interval exceeds upper interval")
    return float(np.mean((y[valid] >= lo[valid]) & (y[valid] <= hi[valid]))) if valid.any() else float("nan")


def weather_explainable_mask(frame: pd.DataFrame) -> pd.Series:
    """Return rows whose target is not marked as an operational/data-quality event."""
    mask = pd.Series(True, index=frame.index)
    present = [column for column in QUALITY_FLAGS if column in frame]
    if present:
        mask &= ~frame[present].fillna(False).astype(bool).any(axis=1)
    if "is_clean" in frame:
        mask &= frame["is_clean"].fillna(False).astype(bool)
    return mask


def interval_start(values: Sequence[object], *, label: str) -> pd.DatetimeIndex:
    """Convert left- or right-labelled hourly timestamps to interval starts."""
    if label not in VALID_LABELS:
        raise ValueError(f"label must be one of {VALID_LABELS}")
    timestamps = pd.to_datetime(values, utc=True)
    return timestamps - pd.Timedelta(hours=1) if label == "right" else timestamps


def _scope_rows(include_per_lead: bool) -> list[tuple[str, int, int]]:
    scopes = [("all", 1, 48), ("h1-24", 1, 24), ("h25-48", 25, 48)]
    if include_per_lead:
        scopes.extend((f"h{lead}", lead, lead) for lead in range(1, 49))
    return scopes


def by_lead_block(
    frame: pd.DataFrame,
    pred_col: str,
    actual_col: str = "actual",
    group_cols: Sequence[str] = ("turbine",),
) -> pd.DataFrame:
    """Return backtest metrics by 24-hour block for 0- or 1-based leads."""
    required = {"lead_h", pred_col, actual_col, *group_cols}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"missing metric columns: {sorted(missing)}")
    data = frame.dropna(subset=[actual_col, pred_col])
    if data.empty:
        return pd.DataFrame(
            columns=[*group_cols, "block", "n", "mae", "rmse", "bias"]
        )
    leads = pd.to_numeric(data["lead_h"], errors="raise")
    zero_based = bool(leads.min() == 0)
    bounds = {
        "h1_24": (0, 23) if zero_based else (1, 24),
        "h25_48": (24, 47) if zero_based else (25, 48),
        "all": (0, 47) if zero_based else (1, 48),
    }
    if not leads.between(*bounds["all"]).all():
        raise ValueError("lead_h must consistently use 0..47 or 1..48")
    groups = [((), data)] if not group_cols else data.groupby(list(group_cols))
    rows = []
    for key, group in groups:
        key = key if isinstance(key, tuple) else (key,)
        for block, (start, end) in bounds.items():
            selected = group.loc[group["lead_h"].between(start, end)]
            if selected.empty:
                continue
            rows.append(
                {
                    **dict(zip(group_cols, key, strict=True)),
                    "block": block,
                    "n": int(len(selected)),
                    "mae": mae(selected[actual_col], selected[pred_col]),
                    "rmse": rmse(selected[actual_col], selected[pred_col]),
                    "bias": bias(selected[pred_col], selected[actual_col]),
                }
            )
    return pd.DataFrame(rows)


def evaluate_forecast(
    frame: pd.DataFrame,
    *,
    actual_col: str = "actual",
    prediction_col: str = "p50",
    lead_col: str = "lead_h",
    reference_col: str | None = None,
    quantile_cols: Mapping[float, str] | None = None,
    mode: str = "all",
    label: str = "left",
    capacity: float = 1.0,
    include_per_lead: bool = True,
) -> pd.DataFrame:
    """Evaluate a flat 1..48-hour forecast frame.

    ``label`` records the interval convention and is validated here so the same call
    can be used by the future backtest for either convention.  If frames with unlike
    conventions need joining, convert their timestamp columns with
    :func:`interval_start` first.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}")
    if label not in VALID_LABELS:
        raise ValueError(f"label must be one of {VALID_LABELS}")
    capacity = _capacity(capacity)
    required = {actual_col, prediction_col, lead_col}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"missing metric columns: {sorted(missing)}")
    leads = pd.to_numeric(frame[lead_col], errors="raise")
    if not leads.dropna().between(1, 48).all():
        raise ValueError("lead_h must be in 1..48")

    selected = frame.copy()
    selected[lead_col] = leads
    if mode == "weather_explainable":
        selected = selected.loc[weather_explainable_mask(selected)]

    quantiles = dict(DEFAULT_QUANTILES if quantile_cols is None else quantile_cols)
    quantiles = {float(q): column for q, column in quantiles.items() if column in selected}
    rows: list[dict[str, float | int | str]] = []
    for scope, lead_start, lead_end in _scope_rows(include_per_lead):
        group = selected.loc[selected[lead_col].between(lead_start, lead_end)]
        actual = pd.to_numeric(group[actual_col], errors="coerce").to_numpy(float)
        predicted = pd.to_numeric(group[prediction_col], errors="coerce").to_numpy(float)
        finite = np.isfinite(actual) & np.isfinite(predicted)
        y, yhat = actual[finite], predicted[finite]
        error = yhat - y
        row: dict[str, float | int | str] = {
            "scope": scope,
            "lead_start": lead_start,
            "lead_end": lead_end,
            "mode": mode,
            "label": label,
            "n": int(len(y)),
            "nbias": float(np.mean(error) / capacity) if len(y) else float("nan"),
            "nmae": float(np.mean(np.abs(error)) / capacity) if len(y) else float("nan"),
            "nrmse": float(np.sqrt(np.mean(error**2)) / capacity) if len(y) else float("nan"),
            "sde": float(np.std(error, ddof=0) / capacity) if len(y) else float("nan"),
        }
        if reference_col is not None:
            if reference_col not in group:
                raise ValueError(f"missing reference column: {reference_col}")
            row["skill_pct"] = skill_score(actual, predicted, group[reference_col])
        pinballs = []
        for quantile, column in sorted(quantiles.items()):
            quantile_prediction = pd.to_numeric(
                group[column], errors="coerce"
            ).to_numpy(float)[finite]
            value = pinball_loss(y, quantile_prediction, quantile)
            row[f"pinball_p{round(quantile * 100):02d}"] = value
            pinballs.append(value)
        row["pinball_mean"] = float(np.nanmean(pinballs)) if pinballs else float("nan")
        if 0.1 in quantiles and 0.9 in quantiles:
            row["coverage_p10_p90"] = interval_coverage(
                y,
                pd.to_numeric(group[quantiles[0.1]], errors="coerce")
                .to_numpy(float)[finite],
                pd.to_numeric(group[quantiles[0.9]], errors="coerce")
                .to_numpy(float)[finite],
            )
        else:
            row["coverage_p10_p90"] = float("nan")
        rows.append(row)
    return pd.DataFrame(rows)
