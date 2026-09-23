"""Reproduce LOC-9 honest baselines and hindsight ceilings without network access."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from windagent.config import HOURLY_LABEL, SCADA_TZ
from windagent.eval.metrics import evaluate_forecast

ROOT = Path(__file__).resolve().parents[2]
SCADA_PATH = ROOT / "data/processed/scada_hourly.parquet"
PREVIOUS_RUNS_PATH = ROOT / "data/baselines/previous_runs_ws100.parquet"
ERA5_ARCHIVE_PATH = ROOT / "data/baselines/era5_ws100.parquet"
REPORT_PATH = ROOT / "reports/baselines.csv"
DOC_PATH = ROOT / "docs/research/baselines.md"


@dataclass(frozen=True)
class Window:
    name: str
    start: str
    end: str


WINDOWS = (
    Window("Feb 2024", "2024-02-01", "2024-03-01"),
    Window("Feb 2025", "2025-02-01", "2025-03-01"),
    Window("Jan 2026", "2026-01-01", "2026-02-01"),
)
POWER_CURVES = {"T1": (0.705, 7.89), "T2": (0.700, 7.98)}
NWP_MODELS = {"icon_global": 4, "ecmwf_ifs025": 8}


def _power_curve(values: pd.Series | np.ndarray, turbine_id: str) -> np.ndarray:
    a, b = POWER_CURVES[turbine_id]
    ws = np.asarray(values, dtype=float)
    return np.clip(1.0 / (1.0 + np.exp(-a * (ws - b))), 0.01, 0.99)


def _fit_logistic(ws: pd.Series | np.ndarray, power: pd.Series | np.ndarray) -> tuple[float, float]:
    """Fit ``sigmoid(a * (ws - b))`` by deterministic coarse-to-fine MSE search."""
    x = np.asarray(ws, dtype=float)
    y = np.asarray(power, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x) < 100:
        raise ValueError(f"at least 100 finite rows are required for refit, got {len(x)}")
    a, b = 0.65, 6.0
    steps = ((0.2, 1.0), (0.1, 0.5), (0.05, 0.25), (0.02, 0.1), (0.01, 0.05), (0.005, 0.02), (0.002, 0.01), (0.001, 0.005))
    for step_a, step_b in steps:
        best = (float("inf"), a, b)
        for candidate_a in a + step_a * np.arange(-4, 5):
            if candidate_a <= 0:
                continue
            for candidate_b in b + step_b * np.arange(-4, 5):
                prediction = 1.0 / (1.0 + np.exp(-candidate_a * (x - candidate_b)))
                loss = float(np.mean((y - prediction) ** 2))
                if loss < best[0]:
                    best = (loss, float(candidate_a), float(candidate_b))
        _, a, b = best
    return a, b


def _load_scada(label: str) -> pd.DataFrame:
    if label not in {"left", "right"}:
        raise ValueError("label must be 'left' or 'right'")
    frame = pd.read_parquet(SCADA_PATH)
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    if label == "right":
        frame["ts"] += pd.Timedelta(hours=1)
    return frame.sort_values(["turbine_id", "ts"], ignore_index=True)


def _utc_local_midnight(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz=SCADA_TZ).tz_convert("UTC")


def _evaluation_rows(scada: pd.DataFrame, window: Window, turbine_id: str, label: str) -> pd.DataFrame:
    turbine = scada.loc[scada["turbine_id"] == turbine_id].set_index("ts")
    start = _utc_local_midnight(window.start)
    end = _utc_local_midnight(window.end)
    issues = pd.date_range(start, end - pd.Timedelta(days=1), freq="1D")
    offset = 1 if label == "right" else 0
    issues = issues[issues + pd.Timedelta(hours=47 + offset) <= turbine.index.max()]
    rows = pd.DataFrame(
        (
            (
                issue,
                lead,
                issue + pd.Timedelta(hours=lead - 1),
                issue + pd.Timedelta(hours=lead - 1 + offset),
            )
            for issue in issues
            for lead in range(1, 49)
        ),
        columns=(
            "issue_time_utc",
            "lead_h",
            "target_start_utc",
            "target_time_utc",
        ),
    )
    facts = turbine.drop(columns="turbine_id", errors="ignore")
    rows = rows.join(facts, on="target_time_utc")
    rows.insert(0, "turbine_id", turbine_id)
    rows.insert(0, "window", window.name)
    return rows


def _local_keys(index: pd.DatetimeIndex) -> pd.DataFrame:
    local = index.tz_convert(SCADA_TZ)
    return pd.DataFrame({"month": local.month, "hour": local.hour}, index=index)


def _climatology(history: pd.Series) -> tuple[dict[tuple[int, int], float], dict[int, float], float]:
    keys = _local_keys(history.index)
    train = pd.DataFrame({"p": history, "month": keys.month, "hour": keys.hour}).dropna()
    by_month_hour = train.groupby(["month", "hour"])["p"].mean().to_dict()
    by_hour = train.groupby("hour")["p"].mean().to_dict()
    return by_month_hour, by_hour, float(train["p"].median())


def _lookup_climatology(
    timestamps: pd.Series | pd.DatetimeIndex,
    by_month_hour: dict[tuple[int, int], float],
    by_hour: dict[int, float],
    fallback: float,
) -> np.ndarray:
    index = pd.DatetimeIndex(timestamps)
    local = index.tz_convert(SCADA_TZ)
    return np.asarray(
        [by_month_hour.get((ts.month, ts.hour), by_hour.get(ts.hour, fallback)) for ts in local],
        dtype=float,
    )


def _madsen_alpha(
    history: pd.Series,
    by_month_hour: dict[tuple[int, int], float],
    by_hour: dict[int, float],
    fallback: float,
) -> dict[int, float]:
    climate = _lookup_climatology(history.index, by_month_hour, by_hour, fallback)
    residual = history - climate
    return {
        lead: float(np.clip(residual.autocorr(lag=lead), 0.0, 1.0))
        for lead in range(1, 49)
    }


def _honest_predictions(rows: pd.DataFrame, turbine: pd.DataFrame, window: Window) -> dict[str, np.ndarray]:
    label_shift = rows["target_time_utc"].iloc[0] - rows["target_start_utc"].iloc[0]
    series = turbine.set_index("ts")["p"].sort_index()
    series.index -= label_shift
    window_start = rows["target_start_utc"].min()
    training = series.loc[series.index < window_start]
    by_month_hour, by_hour, fallback = _climatology(training)
    climate = _lookup_climatology(rows["target_start_utc"], by_month_hour, by_hour, fallback)
    alpha = _madsen_alpha(training, by_month_hour, by_hour, fallback)

    medians: dict[pd.Timestamp, float] = {}
    anchors: dict[pd.Timestamp, float] = {}
    for issue, group in rows.groupby("issue_time_utc", sort=True):
        cutoff = group["target_start_utc"].min()
        available = series.loc[series.index < cutoff].dropna()
        medians[issue] = float(available.median())
        anchors[issue] = float(available.iloc[-1])
    median_prediction = rows["issue_time_utc"].map(medians).to_numpy(float)
    anchor = rows["issue_time_utc"].map(anchors).to_numpy(float)
    alpha_values = rows["lead_h"].map(alpha).to_numpy(float)
    same_hour = series.reindex(
        pd.DatetimeIndex(rows["target_start_utc"]) - pd.Timedelta(days=1)
    ).to_numpy(float)
    return {
        "constant_median": median_prediction,
        "zero": np.zeros(len(rows), dtype=float),
        "same_hour_yesterday": same_hour,
        "month_hour_climatology": climate,
        "madsen_new_reference": np.clip(alpha_values * anchor + (1.0 - alpha_values) * climate, 0.0, 1.0),
    }


def _load_previous_runs() -> pd.DataFrame:
    frame = pd.read_parquet(PREVIOUS_RUNS_PATH)
    frame["valid_utc"] = pd.to_datetime(frame["valid_utc"], utc=True)
    expected = {"model", "valid_utc", "ws100_previous_day1", "ws100_previous_day2"}
    missing = expected - set(frame)
    if missing:
        raise ValueError(f"Previous Runs cache misses columns: {sorted(missing)}")
    return frame


def _nwp_prediction(
    rows: pd.DataFrame,
    scada_turbine: pd.DataFrame,
    nwp: pd.DataFrame,
    model: str,
) -> tuple[np.ndarray, float, float]:
    model_frame = nwp.loc[nwp["model"] == model].set_index("valid_utc").sort_index()
    eval_start = rows["target_start_utc"].min()
    label_shift = rows["target_time_utc"].iloc[0] - rows["target_start_utc"].iloc[0]
    training = scada_turbine[["ts", "p"]].copy()
    training["ts"] -= label_shift
    training = training.set_index("ts").join(model_frame, how="inner")
    training = training.loc[training.index < eval_start]
    ws_train = np.concatenate(
        [training["ws100_previous_day1"], training["ws100_previous_day2"]]
    )
    p_train = np.concatenate([training["p"], training["p"]])
    a, b = _fit_logistic(ws_train, p_train)

    selected = []
    availability_lag = pd.Timedelta(hours=NWP_MODELS[model])
    for issue, target in rows[["issue_time_utc", "target_start_utc"]].itertuples(index=False):
        cycle = target.floor("6h")
        day = 1 if cycle - pd.Timedelta(days=1) + availability_lag <= issue else 2
        column = f"ws100_previous_day{day}"
        selected.append(model_frame[column].get(target, float("nan")))
    ws = np.asarray(selected, dtype=float)
    prediction = np.clip(1.0 / (1.0 + np.exp(-a * (ws - b))), 0.01, 0.99)
    return prediction, a, b


def _load_era5() -> tuple[pd.Series, pd.DataFrame]:
    archive_frame = pd.read_parquet(ERA5_ARCHIVE_PATH)
    archive_frame["valid_utc"] = pd.to_datetime(
        archive_frame["valid_utc"], utc=True
    )
    archive = archive_frame.set_index("valid_utc")["era5_ws100"].sort_index()
    selected = []
    for path in sorted((ROOT / "data/era5").glob("era5_*.csv")):
        part = pd.read_csv(path, usecols=["time", "wind_speed_100m"])
        part["ts"] = pd.to_datetime(part.pop("time"), utc=True)
        part["source_month"] = path.stem.removeprefix("era5_")
        selected.append(part)
    return archive, pd.concat(selected, ignore_index=True).drop_duplicates("ts")


def _ceiling_predictions(
    rows: pd.DataFrame,
    scada_turbine: pd.DataFrame,
    window: Window,
    turbine_id: str,
    era5_archive: pd.Series,
    era5_selected: pd.DataFrame,
) -> tuple[dict[str, np.ndarray], dict[str, tuple[float, float]]]:
    label_shift = rows["target_time_utc"].iloc[0] - rows["target_start_utc"].iloc[0]
    facts = scada_turbine[["ts", "p", "ws"]].copy()
    facts["ts"] -= label_shift
    facts = facts.set_index("ts")
    fit = era5_selected.merge(
        facts[["p", "ws"]], left_on="ts", right_index=True, how="inner"
    )
    fit = fit.loc[fit["source_month"] != window.start[:7]].dropna()
    a, b = _fit_logistic(fit["wind_speed_100m"], fit["p"])
    mos_a, mos_b = np.polyfit(fit["wind_speed_100m"], fit["ws"], 1)

    timestamps = pd.DatetimeIndex(rows["target_start_utc"])
    ws_era5 = era5_archive.reindex(timestamps).to_numpy(float)
    ws_scada = rows["ws"].to_numpy(float)
    fixed = _power_curve(ws_era5, turbine_id)
    refit = np.clip(1.0 / (1.0 + np.exp(-a * (ws_era5 - b))), 0.01, 0.99)
    mos = _power_curve(mos_a * ws_era5 + mos_b, turbine_id)
    perfect = _power_curve(ws_scada, turbine_id)
    predictions = {
        "era5_fixed_scada_curve": fixed,
        "era5_refit_lomo": refit,
        "era5_linear_mos_lomo": mos,
        "perfect_wind": perfect,
    }
    parameters = {
        "era5_refit_lomo": (a, b),
        "era5_linear_mos_lomo": (float(mos_a), float(mos_b)),
    }
    return predictions, parameters


def _score_prediction(
    rows: pd.DataFrame,
    prediction: np.ndarray,
    *,
    section: str,
    baseline: str,
    model: str = "",
    fit_a: float = float("nan"),
    fit_b: float = float("nan"),
    label: str,
) -> pd.DataFrame:
    metric_frame = rows.copy()
    metric_frame["actual"] = metric_frame["p"]
    metric_frame["prediction"] = prediction
    scored = []
    for mode in ("all", "weather_explainable"):
        metrics = evaluate_forecast(
            metric_frame,
            actual_col="actual",
            prediction_col="prediction",
            quantile_cols={},
            mode=mode,
            label=label,
            include_per_lead=False,
        )
        metrics.insert(0, "fit_b", fit_b)
        metrics.insert(0, "fit_a", fit_a)
        metrics.insert(0, "model", model)
        metrics.insert(0, "baseline", baseline)
        metrics.insert(0, "section", section)
        metrics.insert(0, "turbine_id", rows["turbine_id"].iloc[0])
        metrics.insert(0, "window", rows["window"].iloc[0])
        metrics["mae"] = metrics["nmae"]
        metrics["rmse"] = metrics["nrmse"]
        metrics["bias"] = metrics["nbias"]
        scored.append(metrics)
    return pd.concat(scored, ignore_index=True)


def build_report(*, label: str = HOURLY_LABEL) -> pd.DataFrame:
    """Compute every LOC-9 baseline and ceiling from committed local artifacts."""
    scada = _load_scada(label)
    previous_runs = _load_previous_runs()
    era5_archive, era5_selected = _load_era5()
    results = []
    for window in WINDOWS:
        for turbine_id in ("T1", "T2"):
            turbine = scada.loc[scada["turbine_id"] == turbine_id]
            rows = _evaluation_rows(scada, window, turbine_id, label)
            for name, prediction in _honest_predictions(rows, turbine, window).items():
                results.append(
                    _score_prediction(rows, prediction, section="honest", baseline=name, label=label)
                )

            for model in NWP_MODELS:
                model_start = previous_runs.loc[
                    previous_runs["model"] == model, "valid_utc"
                ].min()
                if rows["target_time_utc"].min() < model_start:
                    continue
                prediction, a, b = _nwp_prediction(rows, turbine, previous_runs, model)
                results.append(
                    _score_prediction(
                        rows,
                        prediction,
                        section="honest",
                        baseline="previous_runs_refit_curve",
                        model=model,
                        fit_a=a,
                        fit_b=b,
                        label=label,
                    )
                )

            ceilings, parameters = _ceiling_predictions(
                rows,
                turbine,
                window,
                turbine_id,
                era5_archive,
                era5_selected,
            )
            for name, prediction in ceilings.items():
                fit_a, fit_b = parameters.get(name, (float("nan"), float("nan")))
                results.append(
                    _score_prediction(
                        rows,
                        prediction,
                        section="ceiling",
                        baseline=name,
                        fit_a=fit_a,
                        fit_b=fit_b,
                        label=label,
                    )
                )
    report = pd.concat(results, ignore_index=True)
    order = [
        "window",
        "turbine_id",
        "section",
        "baseline",
        "model",
        "mode",
        "scope",
        "lead_start",
        "lead_end",
        "label",
        "n",
        "mae",
        "rmse",
        "bias",
        "nmae",
        "nrmse",
        "nbias",
        "sde",
        "fit_a",
        "fit_b",
        "skill_pct",
        "pinball_mean",
        "coverage_p10_p90",
    ]
    return report.reindex(columns=order).sort_values(
        ["turbine_id", "window", "section", "baseline", "model", "mode", "lead_start"],
        ignore_index=True,
    )


def _display_name(row: pd.Series) -> str:
    names = {
        "constant_median": "Constant median (history before issue)",
        "zero": "Zero",
        "same_hour_yesterday": "Same hour yesterday",
        "month_hour_climatology": "Month × hour climatology",
        "madsen_new_reference": "Madsen new reference",
        "previous_runs_refit_curve": "Previous Runs → refit curve",
        "era5_fixed_scada_curve": "ERA5 → fixed SCADA curve",
        "era5_refit_lomo": "ERA5 → refit logistic (LOMO)",
        "era5_linear_mos_lomo": "ERA5 → linear MOS (LOMO)",
        "perfect_wind": "Perfect wind (SCADA ws → curve)",
    }
    model = f" ({row['model']})" if row["model"] else ""
    return names[row["baseline"]] + model


def _markdown_table(frame: pd.DataFrame) -> list[str]:
    pivot = frame.pivot_table(index=["baseline", "model"], columns="window", values="mae")
    lines = [
        "| Метод | Feb 2024 | Feb 2025 | Jan 2026 |",
        "|---|---:|---:|---:|",
    ]
    for (baseline, model), row in pivot.iterrows():
        descriptor = pd.Series({"baseline": baseline, "model": model})
        values = ["—" if pd.isna(row.get(window.name)) else f"{row[window.name]:.3f}" for window in WINDOWS]
        lines.append(f"| {_display_name(descriptor)} | {' | '.join(values)} |")
    return lines


def _markdown_nwp_blocks(frame: pd.DataFrame) -> list[str]:
    nwp = frame.loc[
        (frame["baseline"] == "previous_runs_refit_curve")
        & frame["scope"].isin(["h1-24", "h25-48"])
    ]
    pivot = nwp.pivot_table(
        index=["window", "model"], columns="scope", values="mae"
    )
    lines = [
        "| Окно / модель | h1–24 | h25–48 |",
        "|---|---:|---:|",
    ]
    for (window, model), row in pivot.iterrows():
        lines.append(
            f"| {window} / `{model}` | {row['h1-24']:.3f} | "
            f"{row['h25-48']:.3f} |"
        )
    return lines


def write_outputs(report: pd.DataFrame) -> tuple[Path, Path]:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT_PATH.with_suffix(".tmp.csv")
    report.to_csv(temporary, index=False, float_format="%.6f")
    temporary.replace(REPORT_PATH)

    t1 = report.loc[
        (report["turbine_id"] == "T1")
        & (report["mode"] == "all")
        & (report["scope"] == "all")
    ]
    honest = t1.loc[t1["section"] == "honest"]
    ceilings = t1.loc[t1["section"] == "ceiling"]
    lines = [
        "# LOC-9 — честные бейзлайны и потолки",
        "",
        "MAE нормализованной почасовой мощности T1. Выпуск — 00:00 фиксированного SCADA UTC+6, "
        "горизонт h1–48; Jan 2026 ограничен 30 полными выпусками. `all` сохраняет реальные простои, "
        "а полный CSV также содержит режим `weather_explainable` без отмеченных эксплуатационных/качественных событий.",
        "",
        "## Честные бейзлайны",
        "",
        *_markdown_table(honest),
        "",
        "Previous Runs выбирает day1/day2 только если соответствующий цикл уже опубликован к issue-time "
        "(ICON +4 ч, IFS 0.25° +8 ч). Кривая переобучается только на данных до начала проверяемого окна. "
        "В Feb 2024 полного архива этих моделей ещё нет, поэтому NWP-строки не публикуются.",
        "",
        "### Case-compliant NWP по блокам",
        "",
        *_markdown_nwp_blocks(
            report.loc[
                (report["turbine_id"] == "T1")
                & (report["mode"] == "all")
            ]
        ),
        "",
        "## Потолки — недоступны на момент выпуска",
        "",
        *_markdown_table(ceilings),
        "",
        "ERA5 — реанализ, а SCADA-ветер будущего часа — perfect foresight. Они показывают достижимый "
        "потолок и не могут называться forecast-бейзлайнами. Для Feb 2024 фиксированная SCADA-кривая "
        "действительно хуже обычного коридора (≈0.28): это воспроизводимый зимний bias ERA5, а не причина "
        "подменять фиксированную кривую refit-результатом.",
        "",
        "## Число, которое надо бить",
        "",
        "**MAE 0.20–0.22**: case-compliant Previous Runs `ws100` → refit-кривая. Цель v1 — ≤0.19 "
        "(skill ≥10%); приемлемый результат — ≤0.22.",
        "",
        "## Воспроизведение",
        "",
        "```sh",
        "OPEN_METEO_CACHE_ONLY=1 uv run scripts/baselines.py",
        "```",
        "",
        "Скрипт не обращается к сети. Полные значения по T1/T2, h1–24/h25–48, обоим quality-режимам, "
        "параметры refit/MOS и nMAE/nRMSE/nBIAS/SDE находятся в `reports/baselines.csv`.",
        "",
    ]
    temporary_doc = DOC_PATH.with_suffix(".tmp.md")
    temporary_doc.write_text("\n".join(lines), encoding="utf-8")
    temporary_doc.replace(DOC_PATH)
    return REPORT_PATH, DOC_PATH


def main() -> None:
    report = build_report()
    csv_path, doc_path = write_outputs(report)
    summary = report.loc[
        (report["turbine_id"] == "T1")
        & (report["mode"] == "all")
        & (report["scope"] == "all")
    ]
    print(f"wrote {csv_path.relative_to(ROOT)} ({len(report)} rows)")
    print(f"wrote {doc_path.relative_to(ROOT)}")
    print(summary[["window", "section", "baseline", "model", "n", "mae"]].to_string(index=False))


if __name__ == "__main__":
    main()
