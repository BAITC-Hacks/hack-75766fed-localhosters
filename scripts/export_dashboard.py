"""Export real January SCADA / as-issued forecast data and LOC-14 revision traces."""
import csv
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from research.scada_load import load_hourly
from windagent.agent.runtime import run_issue
from windagent.model.v0 import PREV_RUNS_JSON, predict_series


def main():
    root = Path("dashboard/public/data")
    root.mkdir(parents=True, exist_ok=True)
    scada = load_hourly("T1")
    source = json.loads(PREV_RUNS_JSON.read_text())
    hourly = source["hourly"]
    sample = []
    for i, value in enumerate(hourly["time"]):
        stamp = pd.Timestamp(value, tz="UTC")
        if not pd.Timestamp("2026-01-15", tz="UTC") <= stamp < pd.Timestamp("2026-01-20", tz="UTC"):
            continue
        wind = hourly["wind_speed_100m_previous_day1"][i]
        actual = scada.loc[stamp, "p"] if stamp in scada.index else None
        if wind is not None:
            sample.append({"time": stamp.isoformat(), "forecast": round(float(predict_series([wind]).p50.iloc[0]), 6),
                           "actual": round(float(actual), 6) if pd.notna(actual) else None})
    valid = [abs(row["forecast"] - row["actual"]) for row in sample if row["actual"] is not None]
    with tempfile.TemporaryDirectory(prefix="windagent-dashboard-") as temporary:
        cache = Path("data/nwp_cache/single_runs/ecmwf_ifs")
        first = run_issue(datetime(2026, 1, 31, 18, tzinfo=timezone.utc), cache, Path(temporary),
                          model_adapter="windagent.model.v0:predict_power")
        second = run_issue(datetime(2026, 1, 31, 20, tzinfo=timezone.utc), cache, Path(temporary),
                           model_adapter="windagent.model.v0:predict_power")
        def read(path):
            with (path / "forecast.csv").open() as file:
                forecast = [row for row in csv.DictReader(file) if row["turbine"] == "turbine_1"]
            return {"forecast": forecast, "inputs": json.loads((path / "inputs.json").read_text()),
                    "trace": [json.loads(line) for line in (path / "trace.jsonl").read_text().splitlines()],
                    "decision": json.loads((path / "decision.json").read_text())}
        payload = {"dev": {"rows": sample, "mae": round(sum(valid) / len(valid), 4), "coverage": len(valid),
                            "period": "15–19 Jan 2026", "source": "Open-Meteo Previous Runs day1 + SCADA T1"},
                   "revision": {"first": read(first), "second": read(second)}}
    (root / "dashboard.json").write_text(json.dumps(payload, ensure_ascii=False))
    print(f"Exported {len(sample)} dev hours and two revision traces")


if __name__ == "__main__":
    main()
