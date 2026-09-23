"""nMAE / nRMSE / bias по блокам горизонта. Единицы — нормализованная мощность 0..1 (доля от 2.5 МВт).

lead_h здесь — часы от момента выпуска (0..47): блок h1_24 = lead 0..23, h25_48 = lead 24..47.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BLOCKS = {"h1_24": (0, 23), "h25_48": (24, 47), "all": (0, 47)}


def mae(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.nanmean(np.abs(a - b)))


def rmse(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.sqrt(np.nanmean((a - b) ** 2)))


def bias(pred, actual) -> float:
    return float(np.nanmean(np.asarray(pred, float) - np.asarray(actual, float)))


def skill(mae_model: float, mae_ref: float) -> float:
    return float(100.0 * (mae_ref - mae_model) / mae_ref) if mae_ref else float("nan")


def by_lead_block(df: pd.DataFrame, pred_col: str, actual_col: str = "actual",
                  group_cols=("turbine",)) -> pd.DataFrame:
    """Таблица метрик по (группа × блок). Строки без actual (NaN) исключаются."""
    d = df.dropna(subset=[actual_col, pred_col])
    rows = []
    groups = [((), d)] if not group_cols else list(d.groupby(list(group_cols)))
    for key, g in groups:
        key = key if isinstance(key, tuple) else (key,)
        for block, (lo, hi) in BLOCKS.items():
            b = g[(g.lead_h >= lo) & (g.lead_h <= hi)]
            if b.empty:
                continue
            rows.append({
                **dict(zip(group_cols, key)),
                "block": block,
                "n": int(len(b)),
                "mae": mae(b[pred_col], b[actual_col]),
                "rmse": rmse(b[pred_col], b[actual_col]),
                "bias": bias(b[pred_col], b[actual_col]),
            })
    return pd.DataFrame(rows)
