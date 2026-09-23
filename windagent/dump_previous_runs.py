"""Build the LOC-15 Previous Runs archive from permanent raw JSON responses."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from windagent.tools.weather import (
    DEFAULT_PREVIOUS_VARS,
    PREVIOUS_MODELS,
    PREVIOUS_VARIABLES,
    ROOT,
    WeatherClient,
    atomic_write,
)

END = "2026-02-28"
SITE_ID = "T1"
EXPECTED_DAY1_R = {
    "icon_global": 0.789,
    "gfs_global": 0.699,
    "ecmwf_ifs025": 0.747,
    "ecmwf_aifs025_single": 0.795,
    "ecmwf_ifs": 0.756,
}
COLUMNS = tuple(
    f"{name}_previous_day{day}"
    for name in PREVIOUS_VARIABLES.values()
    for day in (1, 2)
)
GUST_MODELS = {"icon_global", "gfs_global"}
COARSE_MODELS = {"ecmwf_ifs025", "ecmwf_aifs025_single"}


def model_variables(model: str) -> tuple[str, ...]:
    variables = tuple(
        v for v in DEFAULT_PREVIOUS_VARS if not (v == "ws80" and model in COARSE_MODELS)
    )
    return (*variables, "gusts") if model in GUST_MODELS else variables


def normalize(model: str, frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.insert(0, "model", model)
    frame.insert(0, "site_id", SITE_ID)
    for column in COLUMNS:
        if column not in frame:
            frame[column] = pd.Series(float("nan"), index=frame.index, dtype="float64")
    return frame[["site_id", "model", "valid_utc", *COLUMNS]]


def monthly_nulls(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    months = frame.valid_utc.dt.strftime("%Y-%m")
    result = {}
    for month, group in frame.groupby(months, sort=True):
        result[month] = {
            name: round(float(group[name].isna().mean() * 100), 3) for name in COLUMNS
        }
    return result


def parquet_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_docs(root: Path, manifest: dict) -> None:
    lines = [
        "# LOC-15 — Previous Runs Open-Meteo",
        "",
        "Источник: [Open-Meteo Previous Runs](https://open-meteo.com/en/docs/previous-runs-api). "
        "Данные Open-Meteo / ECMWF, DWD ICON, NOAA GFS, CC BY 4.0; преобразованы в Parquet без изменения значений.",
        "",
        "Каждая строка содержит `valid_utc` и признаки с суффиксами `previous_day1`/`previous_day2`: "
        "значения, спрогнозированные за 24/48 часов до валидного часа. Это фиксированное смещение, "
        "а не доказанное время публикации конкретного запуска. Для точных `run_init_utc` и `lead_h` "
        "используйте Single Runs. Модели с нативным шагом 3/6 ч интерполированы до часа; "
        "точный исходный шаг отдельных почасовых значений не восстановлен.",
        "",
        "Всегда используется `timezone=UTC`, `wind_speed_unit=ms`, `site_id=T1`. "
        "SCADA: фиксированное UTC+6 в исходных метках, см. `research/scada_load.py`. "
        "Файлы `data/nwp_cache/previous_runs/<model>.parquet` содержат по одному часу UTC в строке; "
        "все запросы и SHA-256 исходных JSON записаны в `data/nwp_cache/previous_runs/manifest.json`.",
        "",
        "## Модели и покрытие",
        "",
        "| Модель | Старт запроса | Первый ненулевой ws100 day1 | Строк | Нативный шаг | Грид |",
        "|---|---|---|---:|---:|---|",
    ]
    steps = {"ecmwf_ifs025": "3 ч", "ecmwf_aifs025_single": "6 ч"}
    for model, info in manifest["models"].items():
        grid = info["grid"]
        lines.append(
            f"| `{model}` | {info['requested_start']} | {info['first_valid_ws100_day1']} | "
            f"{info['rows']} | {steps.get(model, '1 ч')} | {grid['latitude']}, {grid['longitude']} |"
        )
    lines += [
        "",
        "Нативные шаги приведены по тикету LOC-15. В выходном наборе все модели имеют почасовые метки; "
        "для моделей с шагом 3/6 ч это обработанный Open-Meteo ряд, не новый запуск каждый час.",
        "",
        "`wind_speed_80m` недоступен для `ecmwf_ifs025` и `ecmwf_aifs025_single`; "
        "`wind_gusts_10m` запрашивается только для `icon_global` и `gfs_global`. "
        "В Parquet общая схема, неподдерживаемые колонки остаются null. "
        "Критерий тикета `696 ч` относится к интервалу **31 января — 28 февраля** "
        "(29 дней); календарный февраль содержит 672 часа. Для обоих интервалов "
        "`ws100 previous_day1/day2` без пропусков.",
        "Числа по месяцам ниже показывают пропуски `wind_speed_100m` и максимальную долю "
        "пропусков среди поддерживаемых колонок.",
        "",
        "## Доля пропусков по месяцам",
        "",
        "| Месяц | Модель | ws100 day1, % | ws100 day2, % | Макс. остальных поддерживаемых, % |",
        "|---|---|---:|---:|---:|",
    ]
    for model, info in manifest["models"].items():
        supported = info["supported_columns"]
        others = [c for c in supported if not c.startswith("wind_speed_100m_")]
        for month, columns in info["null_percent_by_month"].items():
            lines.append(
                f"| {month} | `{model}` | {columns['wind_speed_100m_previous_day1']:.3f} | "
                f"{columns['wind_speed_100m_previous_day2']:.3f} | "
                f"{max((columns[c] for c in others), default=0):.3f} |"
            )
    lines += [
        "",
        "Полная матрица null-% для всех колонок находится в `manifest.json`.",
        "",
        "## Skill против SCADA T1, ноябрь 2025 — январь 2026",
        "",
        "`research/skill_benchmark.py` считает Pearson r, RMSE и bias = прогноз − SCADA "
        "для day1/day2. Сравнение делает join по `valid_utc`, после перевода исходных часов "
        "SCADA из фиксированного UTC+6.",
        "",
        "| Модель | day1 r / RMSE / bias (м/с) | day2 r / RMSE / bias (м/с) | n |",
        "|---|---|---|---:|",
    ]
    for model, metrics in manifest["skill"].items():
        day1, day2 = metrics["day1"], metrics["day2"]
        lines.append(
            f"| `{model}` | {day1['r']:.3f} / {day1['rmse']:.2f} / {day1['bias']:+.2f} | "
            f"{day2['r']:.3f} / {day2['rmse']:.2f} / {day2['bias']:+.2f} | {day1['n']} |"
        )
    lines += [
        "",
        "## Источники, запрещённые для бэктеста февраля 2026",
        "",
        "- Historical Forecast: сшивает короткие lead разных запусков и может использовать будущие для issue-time значения.",
        "- Archive / ERA5: реанализ, а не прогноз, выпущенный на момент решения.",
        "- `best_match`: может сменить фактическую модель внутри исторического ряда.",
        "",
        "Для обучения/анализа прошлого эти источники допустимы при явном назначении, "
        "но они не заменяют as-of признаки февральского бэктеста.",
        "",
        "## Запуск и воспроизводимость",
        "",
        "```sh",
        "python -m windagent.dump_previous_runs",
        "OPEN_METEO_CACHE_ONLY=1 python -m windagent.dump_previous_runs",
        "python research/skill_benchmark.py --turbine T1 --start 2025-11-01 --end 2026-01-31",
        "```",
        "",
        f"Уникальных исходных запросов: {manifest['raw_request_count']}; "
        f"расчётный вес запросов по [pricing](https://open-meteo.com/en/pricing): "
        f"{manifest['estimated_weighted_calls']:.1f} (<500). "
        "Это оценка по опубликованной формуле (количество переменных / 10 для интервала до 14 дней), "
        "а не показание биллинга Open-Meteo. Офлайн-повтор — 0 вызовов.",
        "",
    ]
    path = root / "docs/research/nwp-sources.md"
    atomic_write(path, ("\n".join(lines)).encode("utf-8"))


def dump(root: Path = ROOT, *, end: str = END) -> dict:
    from research.scada_load import load_hourly
    from research.skill_benchmark import score

    scada = load_hourly("T1").loc["2025-11-01":"2026-01-31 23:00"]
    with WeatherClient(root, request_budget=350) as client:
        result = {"models": {}, "skill": {}, "estimated_weighted_calls": 0.0}
        for model, start in PREVIOUS_MODELS.items():
            variables = model_variables(model)
            data = client.previous_runs(model, start, end, variables, site_id=SITE_ID)
            frame = normalize(model, data)
            feb = frame[frame.valid_utc.dt.strftime("%Y-%m") == "2026-02"]
            if len(feb) != 672:
                raise ValueError(
                    f"Expected 672 calendar-February hours for {model}: {len(feb)}"
                )
            ticket_window = frame[
                frame.valid_utc.between(
                    pd.Timestamp("2026-01-31", tz="UTC"),
                    pd.Timestamp("2026-02-28 23:00", tz="UTC"),
                )
            ]
            if len(ticket_window) != 696:
                raise ValueError(
                    f"Expected 696 ticket-window hours for {model}: {len(ticket_window)}"
                )
            for day in (1, 2):
                column = f"wind_speed_100m_previous_day{day}"
                if ticket_window[column].isna().any():
                    raise ValueError(
                        f"Missing {column} in 696-hour ticket window for {model}"
                    )
            output = root / f"data/nwp_cache/previous_runs/{model}.parquet"
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(".tmp.parquet")
            frame.to_parquet(temporary, index=False)
            temporary.replace(output)
            records = [
                record
                for record in client.records.values()
                if record["params"]["models"] == model
                and "start_date" in record["params"]
                and record["path"].startswith("data/nwp_cache/previous_runs/")
            ]
            grids = {
                tuple(record["grid"][key] for key in ("latitude", "longitude"))
                for record in records
            }
            if len(grids) != 1:
                raise ValueError(f"Grid changed for {model}: {grids}")
            supported = [
                f"{PREVIOUS_VARIABLES[name]}_previous_day{day}"
                for name in variables
                for day in (1, 2)
            ]
            first_valid = frame.loc[
                frame["wind_speed_100m_previous_day1"].notna(), "valid_utc"
            ]
            if first_valid.empty:
                raise ValueError(f"No valid ws100 data for {model}")
            result["models"][model] = {
                "requested_start": start,
                "end": end,
                "rows": len(frame),
                "first_valid_ws100_day1": first_valid.min().isoformat(),
                "grid": records[0]["grid"],
                "supported_columns": supported,
                "null_percent_by_month": monthly_nulls(frame),
                "parquet_sha256": parquet_checksum(output),
                "raw_requests": sorted(records, key=lambda record: record["path"]),
            }
            forecast = frame.set_index("valid_utc")
            result["skill"][model] = {
                f"day{day}": score(
                    scada, forecast[f"wind_speed_100m_previous_day{day}"]
                )
                for day in (1, 2)
            }
            if abs(result["skill"][model]["day1"]["r"] - EXPECTED_DAY1_R[model]) > 0.02:
                raise ValueError(f"Skill differs from LOC-15 reference for {model}")
            print(
                f"{model}: {len(frame)} hours, {len(records)} source chunks", flush=True
            )
        result["raw_request_count"] = sum(
            len(info["raw_requests"]) for info in result["models"].values()
        )
        result["estimated_weighted_calls"] = round(
            sum(
                max(1, len(info["supported_columns"]) / 10) * len(info["raw_requests"])
                for info in result["models"].values()
            ),
            1,
        )
        if result["estimated_weighted_calls"] >= 500:
            raise ValueError("Weighted call estimate exceeds LOC-15 budget")
        manifest = root / "data/nwp_cache/previous_runs/manifest.json"
        atomic_write(manifest, (json.dumps(result, indent=2) + "\n").encode())
        write_docs(root, result)
        print(
            json.dumps(
                {
                    "network_attempts_this_execution": client.network_attempts,
                    "raw_request_count": result["raw_request_count"],
                    "estimated_weighted_calls": result["estimated_weighted_calls"],
                    "models": {
                        model: {
                            "rows": info["rows"],
                            "first_valid_ws100_day1": info["first_valid_ws100_day1"],
                        }
                        for model, info in result["models"].items()
                    },
                },
                indent=2,
            )
        )
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--end", default=END)
    args = parser.parse_args()
    dump(args.root, end=args.end)


if __name__ == "__main__":
    main()
