"""As-of бэктест: dayahead-выпуски на реальных архивных ранах ECMWF IFS (Open-Meteo Single Runs).

    python -m windagent.backtest --window test   # 29 выпусков 31.01..28.02.2026 -> submission/
    python -m windagent.backtest --window dev    # 31 выпуск за январь 2026, есть факты -> reports/ (MAE)

Правило доступности рана — windagent.clock (per-cycle: +8 ч 00Z/12Z, +7 ч 06Z/18Z).
Модель — pluggable: windagent.model.v0.predict_series (MOS + кривая). Обе турбины получают один ветер
(одна NWP-ячейка), различаются только фактами.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from windagent import clock
from windagent.eval.metrics import by_lead_block, mae, skill

ROOT = Path(__file__).resolve().parents[1]
RUNS_PARQUETS = [
    ROOT / "data/nwp/single_runs_ecmwf_ifs_feb2026.parquet",
    ROOT / "data/nwp/single_runs_ecmwf_ifs_jan2026.parquet",
]
WINDOWS = {
    # первый и последний ЦЕЛЕВОЙ день (по SCADA); выпуск — 18:00 UTC накануне
    "test": (date(2026, 2, 1), date(2026, 3, 1)),   # 29 выпусков: 31.01 .. 28.02 (последний покрывает 1-2 марта)
    "dev": (date(2026, 1, 1), date(2026, 1, 31)),   # 31 выпуск: 31.12 .. 30.01, факты есть
}
TEST_LAST_TARGET_SCADA = pd.Timestamp("2026-02-28T23:00", tz="+06:00")
TURBINES = ("T1", "T2")
SUBMISSION_COLS = ["issue_time_utc", "issue_time_scada", "target_time_scada", "target_time_utc", "turbine",
                   "lead_h", "nwp_run_init_utc", "nwp_lead_h", "issue_kind", "p10", "p50", "p90",
                   "outside_test_period", "model_version"]


def load_runs() -> dict[datetime, pd.DataFrame]:
    frames = [pd.read_parquet(p) for p in RUNS_PARQUETS if p.exists()]
    if not frames:
        raise FileNotFoundError("no Single Runs parquet found; run windagent.dump_weather / scripts/dump_dev_runs.py")
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["run_init_utc", "valid_utc"])
    runs = {}
    for run_init, g in df.groupby("run_init_utc"):
        runs[run_init.to_pydatetime()] = g.set_index("valid_utc").sort_index()
    return runs


def load_model(name: str):
    if name == "v0":
        from windagent.model import v0
        params = v0.load_params()
        return lambda ws: v0.predict_series(ws, params), params["model_version"]
    raise ValueError(f"unknown model {name}")


def run_window(window: str, model: str = "v0") -> pd.DataFrame:
    runs = load_runs()
    predict, model_version = load_model(model)
    first, last = WINDOWS[window]
    rows = []
    for issue in clock.dayahead_issues(first, last):
        run_init = clock.latest_available_run(issue, runs.keys())
        if run_init is None:
            raise RuntimeError(f"no available run for issue {issue}")
        nwp = runs[run_init]
        tgt = clock.targets(issue)
        ws = nwp.reindex(pd.DatetimeIndex(tgt))["wind_speed_100m"]
        if ws.isna().any():
            raise RuntimeError(f"run {run_init} does not cover horizon of issue {issue}")
        pred = predict(ws.values)
        for turbine in TURBINES:
            for i, t in enumerate(tgt):
                rows.append({
                    "issue_time_utc": clock.iso_utc(issue),
                    "issue_time_scada": clock.iso_scada(issue),
                    "target_time_scada": clock.iso_scada(t),
                    "target_time_utc": clock.iso_utc(t),
                    "turbine": turbine,
                    "lead_h": i,
                    "nwp_run_init_utc": clock.iso_utc(run_init),
                    "nwp_lead_h": clock.lead_h(run_init, t),
                    "issue_kind": "dayahead",
                    "p10": round(float(pred.p10[i]), 4),
                    "p50": round(float(pred.p50[i]), 4),
                    "p90": round(float(pred.p90[i]), 4),
                    "outside_test_period": bool(window == "test" and clock.to_scada(t) > TEST_LAST_TARGET_SCADA),
                    "model_version": model_version,
                })
    return pd.DataFrame(rows, columns=SUBMISSION_COLS)


def attach_actuals(df: pd.DataFrame) -> pd.DataFrame:
    """Факты SCADA (почасовое среднее, UTC) для окон с данными; NaN там, где фактов нет."""
    from research.scada_load import load_hourly
    out = []
    for turbine, g in df.groupby("turbine"):
        h = load_hourly(turbine)
        ts = pd.to_datetime(g["target_time_utc"], utc=True)
        g = g.copy()
        g["actual"] = h["p"].reindex(ts).values
        g["actual_ws"] = h["ws"].reindex(ts).values
        # бейзлайны, доступные на момент выпуска: последнее значение и медиана последних 7 суток
        issue = pd.to_datetime(g["issue_time_utc"], utc=True)
        last_val = h["p"].reindex(issue - pd.Timedelta(hours=1)).values
        g["bl_last_value"] = last_val
        med7 = h["p"].rolling("7D", min_periods=24).median()
        g["bl_median_7d"] = med7.reindex(issue - pd.Timedelta(hours=1)).values
        out.append(g)
    return pd.concat(out).sort_values(["issue_time_utc", "turbine", "lead_h"]).reset_index(drop=True)


def evaluate(df: pd.DataFrame) -> pd.DataFrame:
    d = attach_actuals(df)
    tables = []
    for col, name in (("p50", "v0"), ("bl_last_value", "last_value"), ("bl_median_7d", "median_7d")):
        t = by_lead_block(d, col)
        t.insert(0, "model", name)
        tables.append(t)
    res = pd.concat(tables, ignore_index=True)
    ref = res[(res.model == "median_7d")].set_index(["turbine", "block"])["mae"]
    res["skill_vs_median_7d_pct"] = [
        round(skill(r.mae, ref.get((r.turbine, r.block), np.nan)), 1) for r in res.itertuples()
    ]
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", choices=WINDOWS, default="test")
    ap.add_argument("--model", default="v0")
    ap.add_argument("--out", type=Path, default=ROOT / "submission")
    ap.add_argument("--reports", type=Path, default=ROOT / "reports")
    args = ap.parse_args()

    df = run_window(args.window, args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    per_issue = args.out / f"forecast_{args.window}_dayahead_{args.model}.csv"
    df.to_csv(per_issue, index=False)
    n_issues = df.issue_time_utc.nunique()
    print(f"{per_issue}: {len(df)} rows, {n_issues} issues, runs used: {df.nwp_run_init_utc.nunique()}")

    from scripts.flatten_submission import flatten
    if args.window == "test":
        hourly, plant = flatten(df, "2026-02-01T00:00", "2026-02-28T23:00")
    else:
        hourly, plant = flatten(df)
    hourly_path = args.out / f"forecast_{args.window}_hourly_{args.model}.csv"
    hourly.to_csv(hourly_path, index=False)
    plant.to_csv(args.out / f"forecast_{args.window}_hourly_plant_{args.model}.csv", index=False)
    print(f"{hourly_path}: {len(hourly)} rows, {len(plant)} hours")

    if args.window == "dev":
        res = evaluate(df)
        args.reports.mkdir(parents=True, exist_ok=True)
        rep = args.reports / f"backtest_{args.model}_{args.window}.csv"
        res.to_csv(rep, index=False)
        print(res.to_string(index=False))
        print(f"-> {rep}")


if __name__ == "__main__":
    main()
