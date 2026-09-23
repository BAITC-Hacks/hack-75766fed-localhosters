"""Дамп Single Runs ecmwf_ifs для dev-окна (январь 2026): по одному 06Z-рану на день выпуска.

Выпуски dayahead для целевых дней 2026-01-01..2026-01-31 идут в 18:00 UTC дня D−1,
под правилом доступности (+7 ч для 06Z) последний доступный ран — 06Z того же дня D−1.
Итого 31 ран: 2025-12-31T06 .. 2026-01-30T06, forecast_days=4 (96 ч).

Использует windagent.tools.weather.WeatherClient (LOC-14): кеш data/nwp_cache/single_runs/ecmwf_ifs/<run>.json.
Выход: data/nwp/single_runs_ecmwf_ifs_jan2026.parquet (те же колонки, что feb2026).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from windagent.dump_weather import to_frame
from windagent.tools.weather import ROOT, WeatherClient

OUT = ROOT / "data/nwp/single_runs_ecmwf_ifs_jan2026.parquet"


def dev_runs() -> list[str]:
    start = datetime(2025, 12, 31, 6, tzinfo=UTC)
    return [(start + timedelta(days=n)).strftime("%Y-%m-%dT%H:%M") for n in range(31)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    frames = []
    with WeatherClient(ROOT, request_budget=60) as client:
        for i, run in enumerate(dev_runs(), 1):
            frames.append(to_frame(run, client.single_run(run)))
            if i % 10 == 0:
                print(f"{i}/31 runs", flush=True)
        print(f"network attempts: {client.network_attempts}")
    df = pd.concat(frames, ignore_index=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, index=False)
    print(f"{args.out}: {df.run_init_utc.nunique()} runs, {len(df)} rows")


if __name__ == "__main__":
    main()
