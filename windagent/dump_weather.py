"""Reproducible LOC-14 dataset: python -m windagent.dump_weather."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from windagent.tools.weather import (
    ROOT,
    T2,
    VARIABLES,
    WeatherClient,
    atomic_write,
    run_datetime,
)


def runs() -> list[str]:
    start = datetime(2026, 1, 31, tzinfo=UTC)
    return [
        (start + timedelta(hours=6 * n)).strftime("%Y-%m-%dT%H:%M") for n in range(116)
    ]


def to_frame(run: str, data: dict) -> pd.DataFrame:
    if data["utc_offset_seconds"] != 0:
        raise ValueError("Expected UTC response")
    for name in VARIABLES:
        expected = (
            "m/s" if name.startswith("wind_speed") or name == "wind_gusts_10m" else None
        )
        if expected and data["hourly_units"][name] != expected:
            raise ValueError(f"Unexpected unit for {name}")
    frame = pd.DataFrame(data["hourly"])
    frame = frame.rename(columns={"time": "valid_utc"})
    # Keep the committed Parquet schema stable across pandas 2/3, whose timestamp
    # parser defaults differ (ns versus us precision).
    frame["valid_utc"] = pd.to_datetime(frame["valid_utc"], utc=True).astype(
        "datetime64[us, UTC]"
    )
    frame["run_init_utc"] = pd.Timestamp(run_datetime(run))
    lead = (frame.valid_utc - frame.run_init_utc).dt.total_seconds() / 3600
    if not (lead == lead.round()).all() or frame.valid_utc.duplicated().any():
        raise ValueError(f"Invalid hourly time axis: {run}")
    frame["lead_h"] = lead.astype("int64")
    # Gusts describe the preceding interval and are absent at initialisation.
    horizon = frame[frame.lead_h.between(1, 72)]
    if sorted(horizon.lead_h) != list(range(1, 73)):
        raise ValueError(f"Incomplete lead 1..72 horizon: {run}")
    if horizon[list(VARIABLES)].isna().any().any():
        raise ValueError(f"Missing weather values at lead 1..72: {run}")
    return frame[["run_init_utc", "valid_utc", "lead_h", *VARIABLES]]


def check_previous(client: WeatherClient) -> dict:
    previous = client.previous_day()["hourly"]
    reference = dict(
        zip(previous["time"], previous["wind_speed_100m_previous_day1"], strict=True)
    )
    results = {}
    for hour in (0, 6, 12, 18):
        run = f"2026-01-31T{hour:02}:00"
        frame = to_frame(run, client.single_run(run)).set_index("lead_h")
        differences = []
        for lead in range(24, 30):
            row = frame.loc[lead]
            key = row.valid_utc.strftime("%Y-%m-%dT%H:%M")
            value = reference[key]
            if value is None:
                raise ValueError(f"Missing previous_day1 at {key}")
            differences.append(abs(float(row.wind_speed_100m) - value))
        results[f"{hour:02}Z"] = {
            "max_abs_diff_ms": max(differences),
            "passed": max(differences) <= 1e-6,
        }
    return results


def dump(root: Path = ROOT) -> dict:
    with WeatherClient(root) as client:
        frames = []
        grid = None
        for index, run in enumerate(runs(), 1):
            data = client.single_run(run)
            current_grid = (data["latitude"], data["longitude"])
            grid = grid or current_grid
            if current_grid != grid:
                raise ValueError(f"Grid changed for {run}")
            frames.append(to_frame(run, data))
            if index % 20 == 0:
                print(f"Validated {index}/116 runs", flush=True)
        second = client.single_run(runs()[0], latitude=T2[0], longitude=T2[1])
        if (second["latitude"], second["longitude"]) != grid:
            raise ValueError("Turbines resolve to different grid cells")
        semantics = check_previous(client)
        frame = pd.concat(frames, ignore_index=True)
        output = root / "data/nwp/single_runs_ecmwf_ifs_feb2026.parquet"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp.parquet")
        frame.to_parquet(temporary, index=False)
        temporary.replace(output)
        summary = {
            "runs": len(frames),
            "rows": len(frame),
            "grid": grid,
            "complete_horizon_lead_h": [1, 72],
            "nulls_lead_0": frame[frame.lead_h == 0][list(VARIABLES)]
            .isna()
            .sum()
            .to_dict(),
            "nulls_lead_1_to_72": frame[frame.lead_h.between(1, 72)][list(VARIABLES)]
            .isna()
            .sum()
            .to_dict(),
            "previous_day1": semantics,
            "parquet_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "requests": sorted(
                client.records.values(), key=lambda record: record["path"]
            ),
            "weighted_calls_per_uncached_request": 1,
            "weighted_calls_source": "https://open-meteo.com/en/pricing",
            "source": "Open-Meteo / ECMWF IFS; CC BY 4.0",
        }
        atomic_write(
            root / "data/nwp_cache/manifest.json",
            (json.dumps(summary, indent=2) + "\n").encode(),
        )
        result = {k: v for k, v in summary.items() if k != "requests"}
        result["network_attempts_this_execution"] = client.network_attempts
        print(json.dumps(result, indent=2))
        if not all(block["passed"] for block in semantics.values()):
            raise ValueError("Previous Runs semantics differ; see manifest.json")
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Cache and output root")
    args = parser.parse_args()
    dump(args.root)


if __name__ == "__main__":
    main()
