"""Дамп 116 ранов ECMWF IFS 9 km (Single Runs API) за окно бэктеста -> data/nwp_cache/single_runs_ecmwf_ifs_feb2026.csv.

Провенанс: probe9.py ресёрч-агента (2026-09-23) — им и был собран закоммиченный CSV; переписано через
research.openmeteo_client.single_run() (retry + JSON-кеш ответов в data/nwp_cache/single_runs/).

Что в CSV: 29 дней 2026-01-31..2026-02-28 x 00/06/12/18Z = 116 ранов x 72 ч (forecast_days=3) = 8352 строк.
Колонки: run_init_utc, valid_time_utc, lead_h, ws100, wd100, ws10, gust10, t2m, sp (ветер m/s, UTC).
Грид ecmwf_ifs для обеих турбин один: 43.620384/78.47891. Известный null: gust10 при lead_h=0 (116 ячеек),
остальное 0 null. Каждое значение несёт run_init_utc и lead_h — это главный as-issued источник для Feb 2026.

Запуск: python3 research/dump_single_runs.py            # выходит сразу, если CSV уже есть
        python3 research/dump_single_runs.py --force    # перекачать (116 вызовов, ~1-2 мин, сеть)
Схему менять здесь: VARS / FORECAST_DAYS (LOC-14 хочет + wind_speed_80m и forecast_days=4 — тогда файл
пересобирается с --force и меняется число строк).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from research.openmeteo_client import CACHE_DIR, CACHE_ONLY, single_run  # noqa: E402

OUT = CACHE_DIR / "single_runs_ecmwf_ifs_feb2026.csv"
MODEL = "ecmwf_ifs"
FORECAST_DAYS = 3
VARS = {  # порядок = порядок колонок
    "wind_speed_100m": "ws100",
    "wind_direction_100m": "wd100",
    "wind_speed_10m": "ws10",
    "wind_gusts_10m": "gust10",
    "temperature_2m": "t2m",
    "surface_pressure": "sp",
}
DAYS = pd.date_range("2026-01-31", "2026-02-28", freq="D")
CYCLES = (0, 6, 12, 18)


def runs() -> list[str]:
    return [f"{d:%Y-%m-%d}T{hh:02d}:00" for d in DAYS for hh in CYCLES]


def build() -> pd.DataFrame:
    frames, problems = [], []
    for i, run in enumerate(runs(), 1):
        try:
            df = single_run(run, model=MODEL, forecast_days=FORECAST_DAYS, hourly=",".join(VARS))
        except Exception as e:  # 400 / исчерпаны retry / cache miss
            problems.append((run, repr(e)[:160]))
            continue
        df = df.rename(columns=VARS)
        df["valid_time_utc"] = df.index.strftime("%Y-%m-%dT%H:%M")
        frames.append(df[["run_init_utc", "valid_time_utc", "lead_h", *VARS.values()]].reset_index(drop=True))
        if i % 20 == 0:
            print(f"  {i}/{len(runs())} ранов")
        if not CACHE_ONLY:
            time.sleep(0.15)
    if problems:
        print("ПРОБЛЕМНЫЕ РАНЫ:", *problems, sep="\n  ")
    if not frames:
        raise SystemExit(f"ни один ран не скачан ({len(problems)} проблем; OPEN_METEO_CACHE_ONLY={CACHE_ONLY}) — нужна сеть или снять OPEN_METEO_CACHE_ONLY")
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="перекачать, даже если CSV есть")
    a = ap.parse_args()
    if OUT.exists() and not a.force:
        df = pd.read_csv(OUT)
        print(f"уже есть {OUT.relative_to(REPO)}: {len(df)} строк, {df['run_init_utc'].nunique()} ранов "
              f"{df['run_init_utc'].min()} .. {df['run_init_utc'].max()}; --force для пересборки")
        return 0
    print(f"качаю {len(runs())} ранов {MODEL}, forecast_days={FORECAST_DAYS}, vars={list(VARS)}")
    df = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"сохранён {OUT.relative_to(REPO)}: {df.shape}, ранов={df['run_init_utc'].nunique()}, "
          f"null по колонкам={df.isna().sum().to_dict()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
