"""As-of бэктест: dayahead-выпуски на реальных архивных ранах ECMWF IFS (Open-Meteo Single Runs).

    python -m windagent backtest --window test   # 29 выпусков 31.01..28.02.2026 через агента -> submission/, runs/backtest/test/
    python -m windagent backtest --window dev    # 31 выпуск за январь 2026, есть факты -> reports/ (MAE), runs/backtest/dev/
    python -m windagent backtest --window feb2025  # 29 выпусков 31.01..28.02.2025 — репетиция того же сезона, факты есть

Каждый выпуск проходит полный цикл агента (run_issue: погода → проверка → модель → решение → трейс);
сабмит собирается из его прогнозов. run_window() — прямой расчёт той же модели, эталон для регрессии.

Правило доступности рана — windagent.clock (per-cycle: +8 ч 00Z/12Z, +7 ч 06Z/18Z).
Модель — pluggable: windagent.model.v0.predict_series (MOS + кривая). Обе турбины получают один ветер
(одна NWP-ячейка), различаются только фактами.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from windagent import clock
from windagent.eval.metrics import by_lead_block, evaluate_forecast, mae, skill

ROOT = Path(__file__).resolve().parents[1]
RUNS_PARQUETS = [
    ROOT / "data/nwp/single_runs_ecmwf_ifs_feb2026.parquet",
    ROOT / "data/nwp/single_runs_ecmwf_ifs_jan2026.parquet",
    ROOT / "data/nwp/single_runs_ecmwf_ifs_train.parquet",  # 2024-03..2026-01, нужен окну feb2025
]
WINDOWS = {
    # первый и последний ЦЕЛЕВОЙ день (по SCADA); выпуск — 18:00 UTC накануне
    "test": (date(2026, 2, 1), date(2026, 3, 1)),   # 29 выпусков: 31.01 .. 28.02 (последний покрывает 1-2 марта)
    "dev": (date(2026, 1, 1), date(2026, 1, 31)),   # 31 выпуск: 31.12 .. 30.01, факты есть
    # те же выпуски, что holdout feb2025 в windagent.model.v1 (31.01..28.02.2025); в кеше только 06Z -> без reissue
    "feb2025": (date(2025, 2, 1), date(2025, 3, 1)),
}
EVAL_WINDOWS = ("dev", "feb2025")  # окна с фактами SCADA
SCADA_HOURLY = ROOT / "data/processed/scada_hourly.parquet"
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
    """-> (predict(nwp_run_frame, issue, turbine) -> DataFrame[p50, p10, p90] per target hour, model_version)."""
    if name == "v0":
        from windagent.model import v0
        params = v0.load_params()

        def predict_v0(nwp, issue, turbine):
            ws = nwp.reindex(pd.DatetimeIndex(clock.targets(issue)))["wind_speed_100m"]
            if ws.isna().any():
                raise RuntimeError(f"run does not cover horizon of issue {issue}")
            return v0.predict_series(ws.values, params)
        return predict_v0, params["model_version"]
    if name == "v1":
        from windagent.model.schema import build_features
        from windagent.model.serve import load_model as load_v1
        from windagent.model.serve import predict, previous_runs_archive
        from windagent.model.v1 import model_path_for
        _, meta = load_v1()
        prev = previous_runs_archive()

        def predict_v1(nwp, issue, turbine):
            # holdout windows (Jan 2026 dev) use the holdout-free model, so dev MAE stays out-of-sample
            booster, _ = load_v1(model_path_for(issue))
            f = build_features(nwp.reset_index(), issue, turbine, prev)
            return predict(f, booster)
        return predict_v1, meta["model_version"]
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
        for turbine in TURBINES:
            pred = predict(nwp, issue, turbine)
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


AGENT_CACHE = ROOT / "data/nwp_cache/single_runs/ecmwf_ifs"
AGENT_RUNS = ROOT / "runs/backtest"
# Модель сабмита: v1 (LightGBM + v0) точнее v0 на обоих проверочных окнах; v0 остаётся эталоном и страховкой.
PRIMARY_MODEL = os.getenv("WINDAGENT_MODEL", "v1")
ADAPTERS = {"v0": "windagent.model.v0:predict_power", "v1": "windagent.model.v1:predict_power"}
TURBINE_IDS = {"turbine_1": "T1", "turbine_2": "T2"}


def _repo_relative(path: Path) -> Path:
    """Relative path in traces when run from the repo root, so committed runs match on any machine."""
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def run_window_agent(window: str, model: str = "v0", planner=None, reissue: bool | None = None,
                     out_root: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    """Каждый выпуск окна проходит полный цикл агента (windagent.agent.runtime.run_issue).

    Dayahead в 18:00 UTC на каждый целевой день; если к 20:00 UTC опубликован более свежий ран (12Z),
    агент делает повторный выпуск (issue_kind=reissue). Возвращает сабмит dayahead, сабмит reissue
    и папку с прогонами runs/backtest/<window>/<время выпуска>-<вид>/.
    """
    from windagent.agent.runtime import run_issue
    from windagent.config import Settings

    settings = Settings.from_env()
    reissue = settings.reissue_on_new_run if reissue is None else reissue
    adapter = ADAPTERS[model]
    root = (out_root or AGENT_RUNS / model) / window
    if root.exists():
        shutil.rmtree(root)  # чистый replay: память агента строится только из прогонов этого окна
    cache = _repo_relative(AGENT_CACHE)
    available_runs = [datetime.strptime(p.stem, "%Y-%m-%dT%H%MZ").replace(tzinfo=timezone.utc)
                      for p in AGENT_CACHE.glob("????-??-??T????Z.json")]
    first, last = WINDOWS[window]
    frames = {"dayahead": [], "reissue": []}
    for issue in clock.dayahead_issues(first, last):
        plan = [(issue, "dayahead")]
        later = issue + timedelta(hours=2)
        if reissue and clock.latest_available_run(later, available_runs) != clock.latest_available_run(issue, available_runs):
            plan.append((later, "reissue"))
        for at, kind in plan:
            run_dir = run_issue(at, cache, root, planner=planner, settings=settings, model_adapter=adapter,
                                run_id=f"{at.strftime('%Y-%m-%dT%H%MZ')}-{kind}", stable=True)
            status = json.loads((run_dir / "status.json").read_text())["status"]
            if status != "published":
                continue
            f = pd.read_csv(run_dir / "forecast.csv")
            f["turbine"] = f["turbine"].map(TURBINE_IDS)
            f["issue_kind"] = kind
            f["issue_time_scada"] = clock.iso_scada(at)
            f["target_time_scada"] = [clock.iso_scada(pd.Timestamp(t).to_pydatetime()) for t in f.target_time_utc]
            f["outside_test_period"] = [bool(window == "test" and clock.to_scada(pd.Timestamp(t).to_pydatetime()) > TEST_LAST_TARGET_SCADA)
                                        for t in f.target_time_utc]
            for col in ("p10", "p50", "p90"):
                f[col] = f[col].astype(float).round(4)
            frames[kind].append(f[SUBMISSION_COLS])
    dayahead = pd.concat(frames["dayahead"], ignore_index=True)
    reissues = pd.concat(frames["reissue"], ignore_index=True) if frames["reissue"] else pd.DataFrame(columns=SUBMISSION_COLS)
    return dayahead, reissues, root


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


def evaluate_modes(d: pd.DataFrame, model: str) -> pd.DataFrame:
    """metrics.evaluate_forecast в обоих режимах (all / weather_explainable) по флагам SCADA LOC-8:
    MAE/RMSE/bias, skill к median_7d, pinball и покрытие P10–P90, блоки h1–24 / h25–48."""
    flags = pd.read_parquet(SCADA_HOURLY, columns=["ts", "turbine_id", "is_clean", "range", "frozen", "outage",
                                                   "curve_resid", "curtail", "icing", "t1_outage"])
    flags = flags.rename(columns={"turbine_id": "turbine"})
    flags["ts"] = pd.to_datetime(flags["ts"], utc=True)
    e = d.assign(ts=pd.to_datetime(d["target_time_utc"], utc=True), lead_h=d["lead_h"] + 1)
    e = e.merge(flags, on=["ts", "turbine"], how="left")
    tables = []
    for turbine, g in [("both", e), *e.groupby("turbine")]:
        for mode in ("all", "weather_explainable"):
            t = evaluate_forecast(g, reference_col="bl_median_7d", mode=mode, include_per_lead=False)
            t.insert(0, "turbine", turbine)
            t.insert(0, "model", model)
            tables.append(t)
    return pd.concat(tables, ignore_index=True)


def evaluate(df: pd.DataFrame, model: str = "v0") -> pd.DataFrame:
    d = attach_actuals(df)
    tables = []
    for col, name in (("p50", model), ("bl_last_value", "last_value"), ("bl_median_7d", "median_7d")):
        t = by_lead_block(d, col)
        t.insert(0, "model", name)
        tables.append(t)
    res = pd.concat(tables, ignore_index=True)
    ref = res[(res.model == "median_7d")].set_index(["turbine", "block"])["mae"]
    res["skill_vs_median_7d_pct"] = [
        round(skill(r.mae, ref.get((r.turbine, r.block), np.nan)), 1) for r in res.itertuples()
    ]
    return res


def run_and_write(window: str, model: str = PRIMARY_MODEL, out: Path = ROOT / "submission", reports: Path = ROOT / "reports",
                  planner=None, via_agent: bool = True):
    if via_agent:
        df, reissues, runs_root = run_window_agent(window, model, planner=planner)
        n_runs = len(list(runs_root.iterdir()))
        print(f"agent: {n_runs} runs ({df.issue_time_utc.nunique()} dayahead, {reissues.issue_time_utc.nunique()} reissue) -> "
              f"{_repo_relative(runs_root)}")
    else:
        df, reissues = run_window(window, model), None
    out.mkdir(parents=True, exist_ok=True)
    per_issue = out / f"forecast_{window}_dayahead_{model}.csv"
    df.to_csv(per_issue, index=False)
    n_issues = df.issue_time_utc.nunique()
    print(f"{per_issue}: {len(df)} rows, {n_issues} issues, runs used: {df.nwp_run_init_utc.nunique()}")
    if reissues is not None and len(reissues):
        intraday = out / f"forecast_{window}_intraday_{model}.csv"
        reissues.to_csv(intraday, index=False)
        print(f"{intraday}: {len(reissues)} rows, {reissues.issue_time_utc.nunique()} reissues")

    from scripts.flatten_submission import flatten
    if window == "test":
        hourly, plant = flatten(df, "2026-02-01T00:00", "2026-02-28T23:00")
    else:
        hourly, plant = flatten(df)
    hourly_path = out / f"forecast_{window}_hourly_{model}.csv"
    hourly.to_csv(hourly_path, index=False)
    plant.to_csv(out / f"forecast_{window}_hourly_plant_{model}.csv", index=False)
    print(f"{hourly_path}: {len(hourly)} rows, {len(plant)} hours")

    if window in EVAL_WINDOWS:
        res = evaluate(df, model)
        reports.mkdir(parents=True, exist_ok=True)
        rep = reports / f"backtest_{model}_{window}.csv"
        res.to_csv(rep, index=False)
        print(res.to_string(index=False))
        modes = evaluate_modes(attach_actuals(df), model)
        modes_path = reports / f"backtest_{model}_{window}_modes.csv"
        modes.round(4).to_csv(modes_path, index=False)
        print(modes[modes.scope == "all"][["turbine", "mode", "n", "nmae", "nrmse", "skill_pct",
                                           "pinball_mean", "coverage_p10_p90"]].round(4).to_string(index=False))
        print(f"-> {rep}, {modes_path}")
    return per_issue, hourly_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", choices=WINDOWS, default="test")
    ap.add_argument("--model", default=PRIMARY_MODEL, choices=sorted(ADAPTERS))
    ap.add_argument("--out", type=Path, default=ROOT / "submission")
    ap.add_argument("--reports", type=Path, default=ROOT / "reports")
    ap.add_argument("--direct", action="store_true", help="прямой расчёт без агента (эталон для регрессии)")
    args = ap.parse_args()

    run_and_write(args.window, args.model, args.out, args.reports, via_agent=not args.direct)


if __name__ == "__main__":
    main()
