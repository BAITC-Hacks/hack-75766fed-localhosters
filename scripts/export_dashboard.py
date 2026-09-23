"""Данные для дашборда: все выпуски dev (январь, есть факты) и test (февраль), метрики, трейсы агента.

    uv run --frozen python -m scripts.export_dashboard

Пишет в dashboard/public/data/ детерминированно (без времени генерации, uuid и замеров ms),
поэтому повторный запуск не даёт diff в git:

    index.json      окна, выпуски, метрики окна (v0 vs бейзлайны), параметры модели
    dev.json        31 выпуск × 48 ч: ветер NWP, P10/P50/P90 T1/T2, факт SCADA, бейзлайны
    test.json       29 выпусков × 48 ч: то же без фактов (февраль скрыт организаторами)
    agent.json      трейсы агента: dayahead 18:00 UTC каждого дня + re-issue 20:00 UTC (12Z) в test
    forecast_test_hourly_v0.csv   сабмит за февраль для скачивания со страницы
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from windagent import clock
from windagent.agent.runtime import run_issue
from windagent.backtest import TEST_LAST_TARGET_SCADA, WINDOWS, attach_actuals, load_runs, run_window
from windagent.model.v0 import load_params

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard/public/data"
RAW_CACHE = ROOT / "data/nwp_cache/single_runs/ecmwf_ifs"
SCADA_PARQUET = ROOT / "data/processed/scada_hourly.parquet"
METRICS_CSV = ROOT / "reports/backtest_v0_dev.csv"
SUBMISSION_HOURLY = ROOT / "submission/forecast_test_hourly_v0.csv"
ADAPTER = "windagent.model.v0:predict_power"
RATED_MW = 2.5
COLUMNS = ["t", "lead", "nlead", "ws", "t1_p10", "t1_p50", "t1_p90", "t2_p10", "t2_p50", "t2_p90",
           "t1_act", "t2_act", "t1_flag", "t2_flag", "t1_med7", "t2_med7", "t1_last", "t2_last"]
FLAGS = ["outage", "curtail", "icing", "frozen", "curve_resid", "t1_outage"]


def r(x, nd=4):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), nd)


def dump(path: Path, obj) -> None:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    # абсолютные пути машины (кеш в args трейса) -> относительные к репо: одинаковый файл на любой машине
    path.write_text(text.replace(str(ROOT) + "/", "") + "\n")


def scada_flags() -> dict:
    """(turbine, utc) -> первый сработавший флаг качества SCADA (для тултипа «простой / ограничение»)."""
    if not SCADA_PARQUET.exists():
        return {}
    d = pd.read_parquet(SCADA_PARQUET)
    out = {}
    for flag in FLAGS:
        if flag not in d:
            continue
        for row in d.loc[d[flag], ["turbine_id", "ts"]].itertuples(index=False):
            out.setdefault((row.turbine_id, row.ts), flag)
    return out


def mae(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = ~(np.isnan(a) | np.isnan(b))
    return r(np.mean(np.abs(a[m] - b[m]))) if m.any() else None


def build_window(window: str, runs: dict, flags: dict) -> dict:
    df = run_window(window)
    if window == "dev":
        df = attach_actuals(df)
    wide = {}
    for turbine, g in df.groupby("turbine"):
        wide[turbine] = g.set_index(["issue_time_utc", "lead_h"])
    issues = []
    for issue_utc, g in df[df.turbine == "T1"].groupby("issue_time_utc", sort=True):
        g = g.sort_values("lead_h")
        run_init = pd.Timestamp(g.nwp_run_init_utc.iloc[0]).to_pydatetime()
        nwp = runs[run_init]
        rows = []
        for rec in g.itertuples():
            t = pd.Timestamp(rec.target_time_utc)
            ws = nwp["wind_speed_100m"].get(t)
            row = {"t": rec.target_time_utc, "lead": int(rec.lead_h), "nlead": int(rec.nwp_lead_h), "ws": r(ws, 2)}
            for tb, key in (("T1", "t1"), ("T2", "t2")):
                w = wide[tb].loc[(issue_utc, rec.lead_h)]
                row[f"{key}_p10"], row[f"{key}_p50"], row[f"{key}_p90"] = r(w.p10), r(w.p50), r(w.p90)
                row[f"{key}_act"] = r(w.actual) if "actual" in w else None
                row[f"{key}_flag"] = flags.get((tb, t)) if window == "dev" else None
                row[f"{key}_med7"] = r(w.bl_median_7d) if "bl_median_7d" in w else None
                row[f"{key}_last"] = r(w.bl_last_value) if "bl_last_value" in w else None
            rows.append([row[c] for c in COLUMNS])
        issue = {
            "issue_utc": issue_utc,
            "issue_scada": g.issue_time_scada.iloc[0],
            "target_day_scada": clock.to_scada(pd.Timestamp(issue_utc).to_pydatetime()).strftime("%Y-%m-%d"),
            "run_init_utc": g.nwp_run_init_utc.iloc[0],
            "outside_test_from_lead": (int(g.loc[g.outside_test_period, "lead_h"].min())
                                       if window == "test" and g.outside_test_period.any() else None),
            "rows": rows,
        }
        if window == "dev":
            ix = {c: i for i, c in enumerate(COLUMNS)}
            num = [c for c in COLUMNS if c != "t" and not c.endswith("_flag")]
            arr = {c: np.array([np.nan if row[ix[c]] is None else row[ix[c]] for row in rows], float) for c in num}
            lead = arr["lead"]
            issue["mae"] = {
                tb: {blk: mae(arr[f"{tb}_p50"][sel], arr[f"{tb}_act"][sel])
                     for blk, sel in (("h1_24", lead <= 23), ("h25_48", lead >= 24), ("all", lead >= 0))}
                for tb in ("t1", "t2")
            }
        else:
            p = np.array([[row[COLUMNS.index("t1_p50")], row[COLUMNS.index("t2_p50")]] for row in rows], float)
            issue["energy_mwh_48h"] = r(RATED_MW * p.sum(), 2)
        issues.append(issue)
    return {"window": window, "columns": COLUMNS, "issues": issues}


def strip_run_ids(obj):
    """'2026-01-31T18-00Z-49e2255e' -> '2026-01-31T18-00Z' во всех строках."""
    if isinstance(obj, dict):
        return {k: strip_run_ids(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_run_ids(v) for v in obj]
    if isinstance(obj, str) and len(obj) == 26 and obj[10] == "T" and obj[16] == "Z" and obj[17] == "-":
        return obj[:17]
    return obj


def read_run(path: Path) -> dict:
    trace = [json.loads(line) for line in (path / "trace.jsonl").read_text().splitlines()]
    decision = json.loads((path / "decision.json").read_text())
    comparison = json.loads((path / "comparison.json").read_text()) if (path / "comparison.json").exists() else None
    inputs = json.loads((path / "inputs.json").read_text())
    points = {}
    if (path / "forecast.csv").exists():
        f = pd.read_csv(path / "forecast.csv")
        for tb, g in f.groupby("turbine"):
            points["t1" if tb == "turbine_1" else "t2"] = [r(v) for v in g.sort_values("lead_h").point]
    for row in trace:
        row.pop("ms", None)
        row.pop("tokens", None)
    if comparison:
        for k in ("mean_abs_delta", "divergence_ms"):
            comparison[k] = r(comparison.get(k))
    return strip_run_ids({
        "issue_utc": inputs["issue_time_utc"],
        "run_init_utc": inputs["nwp_run_init_utc"],
        "run_available_utc": inputs["nwp_available_at_utc"],
        "planner": inputs["planner"],
        "decision": decision,
        "comparison": comparison,
        "points": points,
        "trace": trace,
    })


def build_agent(test: dict, dev: dict) -> dict:
    """Прогон агента: dayahead 18:00 UTC для каждого выпуска, в test ещё re-issue 20:00 UTC на 12Z."""
    plan = [(pd.Timestamp(i["issue_utc"]).to_pydatetime(), "dayahead", "dev") for i in dev["issues"]]
    for i in test["issues"]:
        at = pd.Timestamp(i["issue_utc"]).to_pydatetime()
        plan += [(at, "dayahead", "test"), (at + timedelta(hours=2), "reissue", "test")]
    plan.sort(key=lambda x: x[0])
    runs = {"dev": {}, "test": {}}
    with tempfile.TemporaryDirectory(prefix="windagent-dashboard-") as tmp:
        root = Path(tmp)
        for at, kind, window in plan:
            path = run_issue(at, RAW_CACHE, root, model_adapter=ADAPTER)
            day = clock.to_scada(at if kind == "dayahead" else at - timedelta(hours=2)).strftime("%Y-%m-%d")
            runs[window].setdefault(day, {})[kind] = read_run(path)
    return runs


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    runs = load_runs()
    flags = scada_flags()
    dev = build_window("dev", runs, flags)
    test = build_window("test", runs, flags)
    dump(OUT / "dev.json", dev)
    dump(OUT / "test.json", test)

    agent = build_agent(test, dev)
    dump(OUT / "agent.json", agent)

    metrics = pd.read_csv(METRICS_CSV) if METRICS_CSV.exists() else pd.DataFrame()
    params = load_params()
    index = {
        "site": {"name": "ВЭС «Нурлы»", "turbines": ["T1", "T2"], "rated_mw": RATED_MW, "scada_tz": "UTC+6"},
        "model": {"version": params["model_version"], "mos_a": r(params["mos_a"]), "mos_b": r(params["mos_b"]),
                  "fit_window_utc": params["fit_window_utc"], "curve": {"k": params["curve_k"], "x0": params["curve_x0"]}},
        "availability_lag_h": clock.AVAIL_LAG_H,
        "windows": {
            "dev": {"label": "Январь 2026", "caption": "проверка на фактах SCADA", "issues": len(dev["issues"]),
                    "first_target_day": WINDOWS["dev"][0].isoformat(), "last_target_day": WINDOWS["dev"][1].isoformat()},
            "test": {"label": "Февраль 2026", "caption": "тестовый прогноз, факты скрыты", "issues": len(test["issues"]),
                     "first_target_day": WINDOWS["test"][0].isoformat(), "last_target_scada": str(TEST_LAST_TARGET_SCADA)},
        },
        "metrics": [
            {k: (r(v) if isinstance(v, float) else v) for k, v in row.items()}
            for row in metrics.to_dict("records")
        ],
        "downloads": {"test_hourly_csv": "forecast_test_hourly_v0.csv"},
    }
    dump(OUT / "index.json", index)
    if SUBMISSION_HOURLY.exists():
        shutil.copyfile(SUBMISSION_HOURLY, OUT / "forecast_test_hourly_v0.csv")
    old = OUT / "dashboard.json"
    if old.exists():
        old.unlink()
    size = sum(p.stat().st_size for p in OUT.iterdir() if p.is_file())
    n_runs = sum(len(v) for w in agent.values() for v in w.values())
    print(f"Exported {len(dev['issues'])} dev + {len(test['issues'])} test issues, {n_runs} agent runs, "
          f"{size / 1024:.0f} KB -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
