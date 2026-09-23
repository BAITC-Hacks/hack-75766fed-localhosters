"""Build the two-panel timezone proof for canonical SCADA timestamps.

Panel 1 pools 10-minute SCADA nacelle wind against two independent UTC references
(IFS 9 km historical forecast and ERA5) across the periods before and after the
Kazakhstan civil-time change.  Panel 2 checks the local-clock time of each day's
temperature maximum and records continuity at the 2024-03-01 boundary.

Run from the repository root::

    python scripts/tz_check.py             # cached/offline when references exist
    python scripts/tz_check.py --fetch     # refresh Open-Meteo reference data
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from research.openmeteo_client import archive_era5, historical_forecast  # noqa: E402
from windagent.data.scada import RAW_FILES, load_raw  # noqa: E402


REFERENCE_DIR = REPO_ROOT / "data" / "tz_reference"
FIGURE_PATH = REPO_ROOT / "docs" / "figures" / "tz_xcorr.png"
RESULTS_PATH = REFERENCE_DIR / "tz_xcorr_results.csv"
FETCH_START = "2023-03-10"
FETCH_END = "2026-01-31"
LAGS_MINUTES = tuple(range(3 * 60, 9 * 60 + 1, 10))
WINDOWS = {
    "2023-03..2024-02": (pd.Timestamp("2023-03-11"), pd.Timestamp("2024-03-01")),
    "2024-03..2026-01": (pd.Timestamp("2024-03-01"), pd.Timestamp("2026-02-01")),
}
REFERENCES = {
    "IFS 9 km": REFERENCE_DIR / "ifs_9km_ws100.parquet",
    "ERA5": REFERENCE_DIR / "era5_ws100.parquet",
}


def _download_references(force: bool = False) -> None:
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    if force or not REFERENCES["IFS 9 km"].exists():
        frame = historical_forecast(
            FETCH_START,
            FETCH_END,
            model="ecmwf_ifs",
            hourly="wind_speed_100m",
            allow_test_window=True,
        )
        frame[["wind_speed_100m"]].to_parquet(REFERENCES["IFS 9 km"])
    if force or not REFERENCES["ERA5"].exists():
        frame = archive_era5(
            FETCH_START,
            FETCH_END,
            hourly="wind_speed_100m",
            model="era5",
            allow_test_window=True,
        )
        frame[["wind_speed_100m"]].to_parquet(REFERENCES["ERA5"])

    manifest = {
        "purpose": "LOC-8 timezone proof only; these analysis references are not as-issued test features",
        "start_date": FETCH_START,
        "end_date": FETCH_END,
        "timezone": "UTC",
        "wind_speed_unit": "m/s",
        "references": {
            "IFS 9 km": {
                "endpoint": "historical-forecast-api.open-meteo.com/v1/forecast",
                "model": "ecmwf_ifs",
                "file": REFERENCES["IFS 9 km"].name,
            },
            "ERA5": {
                "endpoint": "archive-api.open-meteo.com/v1/archive",
                "model": "era5",
                "file": REFERENCES["ERA5"].name,
            },
        },
    }
    (REFERENCE_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _reference_10min(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    series = frame["wind_speed_100m"].copy()
    index = pd.to_datetime(series.index, utc=True).tz_localize(None)
    series.index = index
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series.resample("10min").interpolate("time")


def _correlation(x: np.ndarray, y: np.ndarray) -> float:
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 500:
        return float("nan")
    return float(np.corrcoef(x[valid], y[valid])[0, 1])


def xcorr_results() -> pd.DataFrame:
    """Return every lag/correlation point used by panel 1."""
    scada = {turbine: load_raw(turbine, utc=False)["ws"] for turbine in RAW_FILES}
    rows: list[dict] = []
    for source, path in REFERENCES.items():
        reference = _reference_10min(path)
        for turbine, wind in scada.items():
            for window, (start, end) in WINDOWS.items():
                observed = wind.loc[(wind.index >= start) & (wind.index < end)]
                for lag_minutes in LAGS_MINUTES:
                    shifted = reference.copy(deep=False)
                    shifted.index = reference.index + pd.Timedelta(minutes=lag_minutes)
                    paired = pd.concat([observed.rename("scada"), shifted.rename("reference")], axis=1, join="inner")
                    rows.append(
                        {
                            "source": source,
                            "turbine_id": turbine,
                            "window": window,
                            "lag_h": lag_minutes / 60,
                            "r": _correlation(
                                paired["scada"].to_numpy(float), paired["reference"].to_numpy(float)
                            ),
                            "n": int(paired.dropna().shape[0]),
                        }
                    )
    return pd.DataFrame(rows)


def pooled_summary(results: pd.DataFrame) -> pd.DataFrame:
    records = []
    keys = ["source", "turbine_id", "window"]
    for key, group in results.groupby(keys, sort=False):
        peak = group.loc[group["r"].idxmax()]
        at5 = group.loc[np.isclose(group["lag_h"], 5), "r"].iloc[0]
        at6 = group.loc[np.isclose(group["lag_h"], 6), "r"].iloc[0]
        records.append(
            dict(
                zip(keys, key),
                peak_lag_h=float(peak["lag_h"]),
                r_peak=float(peak["r"]),
                r_at_5h=float(at5),
                r_at_6h=float(at6),
                n=int(peak["n"]),
            )
        )
    return pd.DataFrame(records)


def continuity_summary() -> dict[str, dict[str, int]]:
    output = {}
    for turbine, path in RAW_FILES.items():
        timestamps = pd.to_datetime(
            pd.read_csv(path, usecols=["Статистическое время"])["Статистическое время"],
            format="%Y-%m-%d %H:%M:%S",
        )
        window = timestamps.between("2024-02-29 22:00", "2024-03-01 02:00", inclusive="both")
        selected = timestamps.loc[window]
        output[turbine] = {
            "boundary_rows": int(len(selected)),
            "duplicates": int(timestamps.duplicated().sum()),
            "bad_10min_steps": int(selected.diff().dropna().ne(pd.Timedelta(minutes=10)).sum()),
        }
    return output


def _daily_temperature_maxima() -> pd.DataFrame:
    rows = []
    for turbine in RAW_FILES:
        raw = load_raw(turbine, utc=False)[["temp"]]
        raw["date"] = raw.index.normalize()
        for window, (start, end) in WINDOWS.items():
            period = raw.loc[(raw.index >= start) & (raw.index < end)]
            enough = period.groupby("date")["temp"].count().ge(120)
            period = period.loc[period["date"].isin(enough[enough].index)]
            maximum_index = period.groupby("date")["temp"].idxmax()
            for timestamp in maximum_index:
                rows.append(
                    {
                        "turbine_id": turbine,
                        "window": window,
                        "hour": timestamp.hour + timestamp.minute / 60,
                    }
                )
    return pd.DataFrame(rows)


def make_figure(results: pd.DataFrame, continuity: dict[str, dict[str, int]]) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    figure, (ax_corr, ax_temp) = plt.subplots(1, 2, figsize=(15, 5.8), constrained_layout=True)

    colors = {
        ("IFS 9 km", "2023-03..2024-02"): "#2f6f9f",
        ("IFS 9 km", "2024-03..2026-01"): "#72a9cf",
        ("ERA5", "2023-03..2024-02"): "#a84f3d",
        ("ERA5", "2024-03..2026-01"): "#dc8b72",
    }
    for (source, turbine, window), group in results.groupby(["source", "turbine_id", "window"], sort=False):
        label = f"{source} · {window} · {turbine}"
        ax_corr.plot(
            group["lag_h"],
            group["r"],
            color=colors[(source, window)],
            linestyle="-" if turbine == "T1" else "--",
            linewidth=1.8,
            label=label,
        )
        peak = group.loc[group["r"].idxmax()]
        ax_corr.scatter(peak["lag_h"], peak["r"], color=colors[(source, window)], s=22, zorder=3)
    ax_corr.axvline(6, color="#333333", linewidth=1.3, linestyle=":")
    ax_corr.set(title="Pooled cross-correlation: file clock − UTC", xlabel="Lag, hours", ylabel="Pearson r")
    ax_corr.set_xlim(3, 9)
    ax_corr.legend(fontsize=7.2, ncol=2, loc="lower center")

    maxima = _daily_temperature_maxima()
    bins = np.arange(0, 24.5, 0.5)
    temp_colors = {"2023-03..2024-02": "#5b7f3b", "2024-03..2026-01": "#c28b2c"}
    for window, group in maxima.groupby("window", sort=False):
        hist, edges = np.histogram(group["hour"], bins=bins, density=True)
        centers = (edges[:-1] + edges[1:]) / 2
        ax_temp.plot(centers, hist, linewidth=2.2, color=temp_colors[window], label=window)
    ax_temp.axvspan(15, 15.5, color="#777777", alpha=0.17, label="expected 15:00–15:30")
    note = "Boundary 2024-03-01\n" + "\n".join(
        f"{t}: {v['boundary_rows']} rows, {v['duplicates']} duplicates" for t, v in continuity.items()
    )
    ax_temp.text(
        0.03,
        0.97,
        note,
        transform=ax_temp.transAxes,
        va="top",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "alpha": 0.9, "edgecolor": "#bbbbbb"},
    )
    ax_temp.set(
        title="Local-clock time of daily SCADA temperature maximum",
        xlabel="Fixed UTC+6 hour",
        ylabel="Density",
        xlim=(0, 24),
    )
    ax_temp.set_xticks(range(0, 25, 3))
    ax_temp.legend(fontsize=8, loc="upper right")

    figure.suptitle("SCADA timezone proof: fixed UTC+6 before and after 2024-03-01", fontsize=14)
    FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURE_PATH, dpi=180, bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch", action="store_true", help="refresh IFS and ERA5 reference caches")
    args = parser.parse_args()

    if args.fetch or not all(path.exists() for path in REFERENCES.values()):
        _download_references(force=args.fetch)

    results = xcorr_results()
    summary = pooled_summary(results)
    continuity = continuity_summary()
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(RESULTS_PATH, index=False)
    make_figure(results, continuity)

    pd.set_option("display.width", 180)
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("continuity:", json.dumps(continuity, ensure_ascii=False))
    peaks_ok = summary["peak_lag_h"].between(5.8, 6.2).all()
    ordering_ok = summary["r_at_6h"].gt(summary["r_at_5h"]).all()
    continuity_ok = all(
        item["boundary_rows"] == 25 and item["duplicates"] == 0 and item["bad_10min_steps"] == 0
        for item in continuity.values()
    )
    print(f"checks: pooled_peak={peaks_ok}, r@6>r@5={ordering_ok}, continuity={continuity_ok}")
    print(f"figure: {FIGURE_PATH.relative_to(REPO_ROOT)}")
    return 0 if peaks_ok and ordering_ok and continuity_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
