"""LOC-17 v0: offline as-of day-ahead replay over the committed ECMWF archive."""
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from windagent.clock import assert_as_of, latest_available_run
from windagent.config import Settings

ROOT = Path(__file__).resolve().parents[1]
NWP = ROOT / "data/nwp/single_runs_ecmwf_ifs_feb2026.parquet"
PREVIOUS = ROOT / "data/nwp_cache/previous_runs_nov2025_jan2026/ecmwf_ifs.json"


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def fit_mos():
    """Fit on Nov–Dec 2025 Previous Runs against observed SCADA wind; Jan is held out."""
    from research.scada_load import load_hourly

    forecast = json.loads(PREVIOUS.read_text())
    if forecast["hourly_units"]["wind_speed_100m_previous_day1"] != "m/s":
        raise ValueError("MOS training wind has wrong units")
    hourly = forecast["hourly"]
    table = pd.DataFrame({
        "ts": pd.to_datetime(hourly["time"], utc=True),
        "nwp": hourly["wind_speed_100m_previous_day1"],
    }).set_index("ts")
    scada = load_hourly("T1")[["ws"]]
    joined = table.join(scada, how="inner")
    joined = joined.loc[(joined.index >= "2025-11-01") & (joined.index < "2026-01-01")].dropna()
    if len(joined) < 1000:
        raise ValueError("Insufficient MOS training rows")
    coefficient, intercept = np.polyfit(joined["nwp"].to_numpy(), joined["ws"].to_numpy(), 1)
    return {"a": float(coefficient), "b": float(intercept), "train_rows": int(len(joined)),
            "train_start": "2025-11-01", "train_end_exclusive": "2026-01-01",
            "source": "Previous Runs day1 + SCADA T1", "target": "site wind speed m/s"}


def power(ws100, mos):
    site_wind = mos["a"] * float(ws100) + mos["b"]
    return round(float(np.clip(1 / (1 + math.exp(-0.705 * (site_wind - 7.89))), 0.01, 0.99)), 6)


def replay_test(output=ROOT / "submission"):
    settings = Settings.from_env()
    if settings.issue_hour_utc != 18 or settings.horizon_hours != 48:
        raise ValueError("v0 day-ahead replay requires ISSUE_HOUR_UTC=18 and HORIZON_HOURS=48")
    mos = fit_mos()
    archive = pd.read_parquet(NWP)
    archive["run_init_utc"] = pd.to_datetime(archive["run_init_utc"], utc=True)
    archive["valid_utc"] = pd.to_datetime(archive["valid_utc"], utc=True)
    runs = {run.to_pydatetime(): group.set_index("valid_utc") for run, group in archive.groupby("run_init_utc")}
    output.mkdir(parents=True, exist_ok=True)
    zone = timezone(timedelta(hours=settings.scada_tz_offset_hours))
    rows = []
    for day in range(29):
        issue = datetime(2026, 1, 31, 18, tzinfo=timezone.utc) + timedelta(days=day)
        run = latest_available_run(issue, runs)
        targets = [issue + timedelta(hours=h) for h in range(48)]
        assert_as_of(issue, run, targets)
        block = runs[run]
        if not set(targets).issubset(block.index):
            raise ValueError(f"INCOMPLETE_HORIZON: {iso(issue)} run {iso(run)}")
        for turbine in ("T1", "T2"):
            for h, target in enumerate(targets):
                weather = block.loc[pd.Timestamp(target)]
                if pd.isna(weather["wind_speed_100m"]):
                    raise ValueError(f"Missing ws100 {iso(run)} {iso(target)}")
                rows.append({
                    "issue_time_utc": iso(issue), "issue_time_scada": issue.astimezone(zone).isoformat(),
                    "target_time_scada": target.astimezone(zone).isoformat(), "target_time_utc": iso(target),
                    "turbine": turbine, "lead_h": h, "nwp_run_init_utc": iso(run),
                    "nwp_lead_h": int((target - run).total_seconds() / 3600), "run_cycle": run.hour,
                    "issue_kind": "dayahead", "p10": "", "p50": power(weather["wind_speed_100m"], mos),
                    "p90": "", "outside_test_period": target < datetime(2026, 1, 31, 18, tzinfo=timezone.utc)
                    or target >= datetime(2026, 2, 28, 18, tzinfo=timezone.utc),
                    "model_version": "mos-logistic-v0", "interval_label": "start",
                })
    path = output / "forecast_feb2026_dayahead_v0.csv"
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    flat = []
    by_target = {}
    for row in rows:
        if row["outside_test_period"]:
            continue
        by_target.setdefault((row["target_time_utc"], row["turbine"]), {})["first" if row["lead_h"] < 24 else "second"] = row
    for (target, turbine), versions in sorted(by_target.items()):
        first = versions.get("first")
        second = versions.get("second")
        used = first or second
        flat.append({"target_time_utc": target, "target_time_scada": used["target_time_scada"], "turbine": turbine,
                     "p50_h1_24": first["p50"] if first else "", "p50_h25_48": second["p50"] if second else "",
                     "p10": "", "p90": "", "issue_time_utc_used": used["issue_time_utc"],
                     "nwp_run_init_utc": used["nwp_run_init_utc"], "lead_h": used["lead_h"],
                     "model_version": used["model_version"]})
    flat_path = output / "forecast_feb2026_hourly_v0.csv"
    with flat_path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(flat[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(flat)
    metadata = {"model": mos, "issue_rows": len(rows), "hourly_rows": len(flat),
                "source": str(NWP.relative_to(ROOT)), "interval_label": "start",
                "availability_lag_hours_by_cycle": {str(k): v for k, v in __import__("windagent.clock", fromlist=["AVAIL_LAG"]).AVAIL_LAG["ecmwf_ifs"].items()},
                "quality_metrics": "pending independent SCADA evaluation; February 2026 actuals hidden",
                "quantiles": "not calibrated in v0; p10 and p90 intentionally blank"}
    (output / "forecast_feb2026_v0_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return path, flat_path, metadata
