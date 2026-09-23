"""Canonical SCADA loader: fixed UTC+6 source clock to quality-flagged hourly UTC data.

The source timestamps are wall-clock readings from a controller that stayed on UTC+6
after Kazakhstan's civil-time change in March 2024.  They must therefore be localized
with ``Etc/GMT-6`` (POSIX's inverted sign), never ``Asia/Almaty``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from windagent.config import HOURLY_LABEL, MIN_SAMPLES_PER_HOUR, SCADA_TZ


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
RAW_DIR: Final = REPO_ROOT / "task context"
PROCESSED_PATH: Final = REPO_ROOT / "data" / "processed" / "scada_hourly.parquet"
RAW_FILES: Final = {
    "T1": RAW_DIR / "Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine 1.csv",
    "T2": RAW_DIR / "Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine 2.csv",
}
SOURCE_COLUMNS: Final = {
    "Статистическое время": "ts",
    "Средняя скорость ветра(m/s)": "ws",
    "Нормализованная активная мощность": "p",
    "Средняя температура окружающей среды(°C)": "temp",
}
FLAG_COLUMNS: Final = (
    "range",
    "frozen",
    "outage",
    "curve_resid",
    "curtail",
    "icing",
    "t1_outage",
)

BIN_WIDTH: Final = 0.5
KNOWN_FREEZE_START: Final = pd.Timestamp("2025-05-14 12:10:00")
KNOWN_FREEZE_END: Final = pd.Timestamp("2025-05-14 15:30:00")  # exclusive: 15:30 changes again
T1_OUTAGE_START: Final = pd.Timestamp("2024-05-18 00:00:00")
T1_OUTAGE_END: Final = pd.Timestamp("2024-07-18 00:00:00")  # exclusive, includes July 17


def _turbine_key(turbine_id: str | int) -> str:
    key = str(turbine_id).upper()
    key = key if key.startswith("T") else f"T{key}"
    if key not in RAW_FILES:
        raise ValueError(f"unknown turbine_id={turbine_id!r}; expected one of {tuple(RAW_FILES)}")
    return key


def power_curve(ws: pd.Series | np.ndarray) -> np.ndarray:
    """Verified site logistic curve used for the residual quality check."""
    values = np.asarray(ws, dtype=float)
    return 1.0 / (1.0 + np.exp(-0.705 * (values - 7.89)))


def _full_true_runs(mask: pd.Series, min_steps: int) -> pd.Series:
    """Mark every member of True runs at least ``min_steps`` long."""
    mask = mask.fillna(False).astype(bool)
    groups = mask.ne(mask.shift(fill_value=False)).cumsum()
    lengths = mask.groupby(groups).transform("size")
    return mask & lengths.ge(min_steps)


def _add_raw_flags(df: pd.DataFrame, turbine_id: str) -> pd.DataFrame:
    """Add 10-minute flags before aggregation; no observation is removed or clipped."""
    out = df.copy()
    in_range = out["ws"].between(0, 30, inclusive="both") & out["p"].between(0, 1, inclusive="both")
    out["range"] = ~in_range

    unchanged = out[["ws", "p", "temp"]].diff().eq(0).all(axis=1)
    out["frozen"] = _full_true_runs(unchanged, min_steps=3)
    if turbine_id == "T1":
        known = (out.index >= KNOWN_FREEZE_START) & (out.index < KNOWN_FREEZE_END)
        out["frozen"] |= known

    out["outage"] = out["p"].le(0.01) & out["ws"].gt(5)
    out["curve_resid"] = (out["p"] - power_curve(out["ws"])).lt(-0.3)

    bin_id = np.floor(out["ws"] / BIN_WIDTH)
    valid_for_curve = in_range & out[["ws", "p"]].notna().all(axis=1)
    reference = out.loc[valid_for_curve].groupby(bin_id[valid_for_curve], observed=True)["p"]
    bin_median = bin_id.map(reference.median())
    bin_p10 = bin_id.map(reference.quantile(0.10))
    out["curtail"] = out["ws"].gt(12) & out["p"].lt(0.6 * bin_median)

    icing_candidate = out["temp"].lt(2) & out["p"].lt(bin_p10)
    out["icing"] = _full_true_runs(icing_candidate, min_steps=3)
    out["t1_outage"] = False  # filled on the complete hourly grid, including missing source rows
    return out


def load_raw(turbine_id: str | int = "T1", *, utc: bool = True) -> pd.DataFrame:
    """Load sorted 10-minute observations with canonical names and quality flags.

    ``utc=False`` keeps naive fixed-UTC+6 wall-clock timestamps and exists for the
    timezone proof.  Production callers should use the default tz-aware UTC index.
    """
    turbine = _turbine_key(turbine_id)
    path = RAW_FILES[turbine]
    missing = set(SOURCE_COLUMNS) - set(pd.read_csv(path, nrows=0).columns)
    if missing:
        raise ValueError(f"{path.name}: missing source columns {sorted(missing)}")

    df = pd.read_csv(path, usecols=list(SOURCE_COLUMNS), encoding="utf-8").rename(columns=SOURCE_COLUMNS)
    df["ts"] = pd.to_datetime(df["ts"], format="%Y-%m-%d %H:%M:%S", errors="raise")
    df = df.sort_values("ts", kind="stable")
    duplicates = int(df["ts"].duplicated(keep="last").sum())
    if duplicates:
        df = df.loc[~df["ts"].duplicated(keep="last")]
    df = df.set_index("ts")
    df = _add_raw_flags(df, turbine)
    if utc:
        df.index = df.index.tz_localize(SCADA_TZ).tz_convert("UTC")
    df.index.name = "ts"
    df.attrs.update(turbine_id=turbine, duplicates_dropped=duplicates, source_timezone=SCADA_TZ)
    return df


def _hour_index(df: pd.DataFrame, label: str) -> pd.DatetimeIndex:
    first = df.index.min().floor("h")
    last = df.index.max().floor("h")
    if label == "right":
        first += pd.Timedelta(hours=1)
        last += pd.Timedelta(hours=1)
    return pd.date_range(first, last, freq="1h", tz=df.index.tz, name="ts")


def to_hourly(
    df: pd.DataFrame,
    *,
    turbine_id: str | None = None,
    min_samples: int = MIN_SAMPLES_PER_HOUR,
    label: str = HOURLY_LABEL,
) -> pd.DataFrame:
    """Aggregate raw readings onto a complete hourly grid without target interpolation.

    Hours are half-open intervals ``[HH:00, HH+1:00)``.  ``label='left'`` labels them
    with the interval start; ``label='right'`` labels the same observations with its end.
    Sensor-integrity flags use ``any``.  Operational-state flags require at least half
    of the observed ten-minute samples in that hour, avoiding one-sample regime labels.
    """
    if label not in {"left", "right"}:
        raise ValueError("label must be 'left' or 'right'")
    if not 1 <= min_samples <= 6:
        raise ValueError("min_samples must be between 1 and 6")
    turbine = _turbine_key(turbine_id or df.attrs.get("turbine_id", ""))

    grouped = df.resample("1h", closed="left", label=label)
    hourly = grouped[["ws", "p", "temp"]].mean()
    hourly["n"] = grouped["p"].count()
    hourly["range"] = grouped["range"].max()
    hourly["frozen"] = grouped["frozen"].max()
    for flag in ("outage", "curve_resid", "curtail", "icing"):
        hourly[flag] = grouped[flag].mean().ge(0.5)

    hourly = hourly.reindex(_hour_index(df, label))
    hourly["n"] = hourly["n"].fillna(0).astype("int8")
    for flag in FLAG_COLUMNS[:-1]:
        hourly[flag] = hourly[flag].fillna(False).astype(bool)

    local_hour = hourly.index.tz_convert(SCADA_TZ).tz_localize(None)
    hourly["t1_outage"] = (
        (turbine == "T1") & (local_hour >= T1_OUTAGE_START) & (local_hour < T1_OUTAGE_END)
    )
    insufficient = hourly["n"].lt(min_samples)
    hourly.loc[insufficient, ["ws", "p", "temp"]] = np.nan
    hourly["is_clean"] = ~hourly[list(FLAG_COLUMNS)].any(axis=1) & ~insufficient
    hourly.attrs.update(df.attrs, hourly_label=label, min_samples_per_hour=min_samples)
    return hourly


def load_hourly(
    turbine_id: str | int = "T1",
    *,
    min_samples: int = MIN_SAMPLES_PER_HOUR,
    label: str = HOURLY_LABEL,
) -> pd.DataFrame:
    """Load one turbine on the canonical complete UTC hourly grid."""
    turbine = _turbine_key(turbine_id)
    return to_hourly(load_raw(turbine), turbine_id=turbine, min_samples=min_samples, label=label)


def load_hourly_dataset(
    *, min_samples: int = MIN_SAMPLES_PER_HOUR, label: str = HOURLY_LABEL
) -> pd.DataFrame:
    """Return both turbines in long format with exactly one row per ``(ts, turbine_id)``."""
    parts = []
    for turbine in RAW_FILES:
        part = load_hourly(turbine, min_samples=min_samples, label=label).reset_index()
        part.insert(1, "turbine_id", turbine)
        parts.append(part)
    out = pd.concat(parts, ignore_index=True)
    out["turbine_id"] = out["turbine_id"].astype("string")
    if out.duplicated(["ts", "turbine_id"]).any():
        raise AssertionError("duplicate (ts, turbine_id) rows in canonical SCADA dataset")
    return out.sort_values(["ts", "turbine_id"], ignore_index=True)


def write_hourly_dataset(path: str | Path = PROCESSED_PATH) -> Path:
    """Build and atomically replace the canonical Parquet artifact."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    load_hourly_dataset().to_parquet(temporary, index=False, engine="pyarrow")
    temporary.replace(destination)
    return destination


def clean_training_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Select the documented training view; evaluation should use the unfiltered frame."""
    if "is_clean" not in df:
        raise ValueError("expected canonical SCADA data with an is_clean column")
    return df.loc[df["is_clean"]].copy()


def main() -> None:
    path = write_hourly_dataset()
    df = pd.read_parquet(path)
    summary = df.groupby("turbine_id", observed=True).agg(
        hours=("ts", "size"),
        empty_hours=("n", lambda values: int(values.eq(0).sum())),
        invalid_hours=("p", lambda values: int(values.isna().sum())),
        clean_hours=("is_clean", "sum"),
    )
    print(f"wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size:,} bytes)")
    print(summary.to_string())


if __name__ == "__main__":
    main()

