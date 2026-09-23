"""Per-issue CSV (29 выпусков × 48 ч × 2 турбины) -> плоский почасовой CSV, который жюри сопоставит с актуалами.

Каждый час февраля покрыт двумя выпусками: h1_24 (lead 0..23, выпуск накануне) и h25_48
(lead 24..47, выпуск за двое суток). Основной столбец p50 = h1_24; p50_h25_48 рядом.

    python scripts/flatten_submission.py submission/forecast_test_dayahead_v0.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

RATED_MW = 2.5


def flatten(per_issue: pd.DataFrame, first_target_scada: str | None = None,
            last_target_scada: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = per_issue.copy()
    d["target_time_scada"] = pd.to_datetime(d["target_time_scada"])
    if first_target_scada:
        d = d[d.target_time_scada >= pd.Timestamp(first_target_scada, tz="+06:00")]
    if last_target_scada:
        d = d[d.target_time_scada <= pd.Timestamp(last_target_scada, tz="+06:00")]
    near = d[d.lead_h <= 23].rename(columns={"p50": "p50", "issue_time_utc": "issue_time_utc_used"})
    far = d[d.lead_h >= 24][["target_time_scada", "turbine", "p50"]].rename(columns={"p50": "p50_h25_48"})
    cols = ["target_time_scada", "target_time_utc", "turbine", "p50", "p10", "p90",
            "issue_time_utc_used", "nwp_run_init_utc", "lead_h"]
    hourly = near[cols].merge(far, on=["target_time_scada", "turbine"], how="left")
    hourly["power_mw"] = (RATED_MW * hourly["p50"]).round(4)
    hourly = hourly.sort_values(["target_time_scada", "turbine"]).reset_index(drop=True)
    plant = (hourly.groupby("target_time_scada", as_index=False)
             .agg(target_time_utc=("target_time_utc", "first"), plant_mw=("power_mw", "sum"),
                  n_turbines=("turbine", "nunique")))
    plant["energy_mwh"] = plant["plant_mw"].round(4)  # часовой интервал: МВт·ч == МВт
    hourly["target_time_scada"] = hourly["target_time_scada"].dt.strftime("%Y-%m-%dT%H:%M:%S+06:00")
    plant["target_time_scada"] = plant["target_time_scada"].dt.strftime("%Y-%m-%dT%H:%M:%S+06:00")
    return hourly, plant


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("per_issue_csv", type=Path)
    ap.add_argument("--first", default=None, help="первый целевой час SCADA, напр. 2026-02-01T00:00")
    ap.add_argument("--last", default=None, help="последний целевой час SCADA, напр. 2026-02-28T23:00")
    args = ap.parse_args()
    hourly, plant = flatten(pd.read_csv(args.per_issue_csv), args.first, args.last)
    base = args.per_issue_csv.with_name(args.per_issue_csv.name.replace("_dayahead", "_hourly"))
    hourly.to_csv(base, index=False)
    plant.to_csv(base.with_name(base.name.replace("_hourly", "_hourly_plant")), index=False)
    print(f"{base}: {len(hourly)} rows ({hourly.turbine.nunique()} turbines, {len(plant)} hours)")


if __name__ == "__main__":
    main()
