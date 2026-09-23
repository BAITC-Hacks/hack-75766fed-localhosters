"""Skill-таблица: прогноз ветра (Previous Runs day1/day2, 5 моделей) vs SCADA ws — r / RMSE / bias / r_vs_power.

Провенанс: skill.py + verify_skill.py + refute/skill_check.py ресёрч-агента (2026-09-23). Эталонные числа
(T1, Nov 2025 - Jan 2026, day1, wind_speed_100m): icon_global r 0.789 / RMSE 2.67 / bias +0.23;
ecmwf_aifs025_single 0.795 / 2.65 / -1.40; ecmwf_ifs 0.756 / 2.72 / -1.22; ecmwf_ifs025 0.747 / 2.91 / +1.07;
gfs_global 0.699 / 3.50 / +1.70. SCADA ws -> p r = 0.949 (практический потолок).

Данные: data/nwp_cache/previous_runs_*/<model>.json — все сохранённые ответы Previous Runs API по модели
склеиваются (Nov 2025 - Jan 2026 + Feb 2026); с SCADA (hourly, UTC, до 2026-01-31) остаётся пересечение.
Если для модели кеша нет и OPEN_METEO_CACHE_ONLY не задан — качается через previous_runs() (сеть).

Метрики по каждой колонке wind_speed_*_previous_dayN: n, r (Пирсон vs SCADA ws), rmse (м/с), bias
(прогноз - SCADA, м/с; SCADA-анемометр стоит за ротором и занижает ветер, поэтому bias у IFS отрицательный),
r_power (r прогноза с мощностью p).

Запуск: python3 research/skill_benchmark.py [--turbine T1|T2|both] [--start 2025-11-01 --end 2026-01-31] [--out csv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from research.openmeteo_client import (  # noqa: E402
    CACHE_DIR,
    CACHE_ONLY,
    PREV_MODELS,
    hourly_df_from_json,
    previous_runs,
)
from research.scada_load import load_hourly  # noqa: E402

DEFAULT_START, DEFAULT_END = "2025-11-01", "2026-01-31"


def cached_previous_runs(model: str) -> pd.DataFrame | None:
    parquet = CACHE_DIR / "previous_runs" / f"{model}.parquet"
    if parquet.exists():
        df = pd.read_parquet(parquet).set_index("valid_utc").drop(columns=["site_id", "model"])
        df.index.name = "ts"
        manifest = CACHE_DIR / "previous_runs" / "manifest.json"
        if manifest.exists():
            import json

            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            grid = metadata["models"][model]["grid"]
            df.attrs["grid"] = (grid["latitude"], grid["longitude"])
        df.attrs["files"] = [str(parquet.relative_to(REPO))]
        return df
    files = sorted(CACHE_DIR.glob(f"previous_runs_*/{model}.json"))
    if not files:
        return None
    parts = [hourly_df_from_json(f) for f in files]
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.attrs["files"] = [str(f.relative_to(REPO)) for f in files]
    df.attrs["grid"] = parts[0].attrs.get("grid")
    return df


def forecasts(model: str, start: str, end: str) -> pd.DataFrame:
    df = cached_previous_runs(model)
    if df is None:
        if CACHE_ONLY:
            raise SystemExit(f"{model}: нет data/nwp_cache/previous_runs_*/{model}.json, а OPEN_METEO_CACHE_ONLY=1")
        print(f"  {model}: кеша нет, качаю previous_runs {start}..{end}")
        df = previous_runs(model, start, end, variables=("wind_speed_100m",), days=(1, 2))
        df.attrs["files"] = ["(сеть)"]
    return df


def score(sc: pd.DataFrame, fc: pd.Series) -> dict:
    j = pd.concat([sc["ws"], sc["p"], fc], axis=1, join="inner").dropna()
    j.columns = ["ws", "p", "f"]
    if len(j) < 200:
        return dict(n=len(j), r=np.nan, rmse=np.nan, bias=np.nan, r_power=np.nan)
    return dict(n=len(j), r=round(float(j.ws.corr(j.f)), 3), rmse=round(float(np.sqrt(((j.f - j.ws) ** 2).mean())), 2),
                bias=round(float((j.f - j.ws).mean()), 2), r_power=round(float(j.p.corr(j.f)), 3))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--turbine", default="T1", choices=["T1", "T2", "both"])
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--models", nargs="*", default=list(PREV_MODELS))
    ap.add_argument("--out", default=None, help="куда сохранить таблицу CSV (по умолчанию только печать)")
    a = ap.parse_args()
    turbines = ["T1", "T2"] if a.turbine == "both" else [a.turbine]

    lo, hi = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC") + pd.Timedelta(hours=23)
    scada = {t: load_hourly(t).loc[lo:hi] for t in turbines}
    rows = []
    for model in a.models:
        fc = forecasts(model, a.start, a.end).loc[lo:hi]
        print(f"{model:22s} grid={fc.attrs.get('grid')} rows={len(fc)} src={fc.attrs.get('files')}")
        for t, sc in scada.items():
            for col in [c for c in fc.columns if c.startswith("wind_speed_") and "_previous_day" in c]:
                var, day = col.split("_previous_")
                rows.append(dict(turbine=t, model=model, var=var, lead=day, **score(sc, fc[col])))
    res = pd.DataFrame(rows).sort_values(["turbine", "var", "lead", "r"], ascending=[True, True, True, False])
    empty = sorted(res.loc[res.n < 200, "var"].unique())
    res = res[res.n >= 200]

    pd.set_option("display.width", 200)
    print(f"\n=== forecast wind vs SCADA ws, hourly UTC, {a.start}..{a.end} (day1 = lead 24-29 ч, day2 = 48-53 ч) ===")
    print(res.to_string(index=False))
    if empty:
        print(f"\nпропущено (нет данных у модели или пересечения с SCADA): {empty}")
    for t, sc in scada.items():
        j = sc.dropna(subset=["ws", "p"])
        print(f"\n{t}: SCADA ws -> p r = {j.ws.corr(j.p):.3f} (n={len(j)}) — практический потолок для r_power")
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        res.to_csv(out, index=False)
        print("сохранено", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
