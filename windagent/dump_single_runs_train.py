"""LOC-18 train dump: python -m windagent.dump_single_runs_train.

One ecmwf_ifs Single Run per issue day R (2024-03-14 .. 2026-01-31) chosen by the
dayahead convention: issue 18:00 UTC R -> run 06Z R, lead 12..59 on the window
18:00 R .. 17:00 R+2. Fallback is decided by fact (HTTP 400 or nulls in the window),
not by date: 06Z R -> 00Z R (lead 18..65) -> 18Z R-1 (lead 24..71). All three are
published before 18:00 UTC R under AVAIL_LAG {00Z: 8, 06Z: 7, 18Z: 7}.

Budget: before 06Z_DENSE_FROM the archive has no 06Z runs (findings §3.1), so there
06Z is probed once every PROBE_EVERY days instead of daily; a successful probe is used.
Before 2025-10 the 9 km archive is the IFS Cycle 49R1 hindcast (Open-Meteo docs);
from 2025-10-01 it is real-time open data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from windagent.tools.weather import ROOT, VARIABLES, WeatherClient, atomic_write

FIRST_DAY = date(2024, 3, 14)
LAST_DAY = date(2026, 1, 31)
DAYAHEAD_LEADS = (12, 59)  # from the 06Z run; the window is 48 valid hours
ISSUE_HOUR_UTC = 18
DENSE_06Z_FROM = date(2024, 8, 12)
PROBE_EVERY = 7
# Gusts are a preceding-hour maximum and are null at lead 0; lead >= 12 here anyway.
CORE = list(VARIABLES)
OUTPUT = Path("data/nwp/single_runs_ecmwf_ifs_train.parquet")
MANIFEST = Path("data/nwp/single_runs_ecmwf_ifs_train.manifest.json")
MARKERS = Path("data/nwp_cache/single_runs/ecmwf_ifs")


def candidates(day: date) -> list[tuple[str, datetime]]:
    base = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return [
        ("06Z", base + timedelta(hours=6)),
        ("00Z", base),
        ("18Z_prev", base - timedelta(hours=6)),
    ]


def window(day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=ISSUE_HOUR_UTC)
    return start, start + pd.Timedelta(hours=47)


def to_frame(run: datetime, data: dict) -> pd.DataFrame:
    if data["utc_offset_seconds"] != 0:
        raise ValueError("Expected UTC response")
    for name in VARIABLES:
        unit = data["hourly_units"].get(name)
        if name.startswith("wind_") and name != "wind_direction_100m" and unit not in (
            "m/s",
            "undefined",
        ):
            raise ValueError(f"Unexpected unit for {name}: {unit}")
    frame = pd.DataFrame(data["hourly"]).rename(columns={"time": "valid_utc"})
    frame["valid_utc"] = pd.to_datetime(frame["valid_utc"], utc=True).astype(
        "datetime64[us, UTC]"
    )
    frame["run_init_utc"] = pd.Timestamp(run)
    lead = (frame.valid_utc - frame.run_init_utc).dt.total_seconds() / 3600
    if not (lead == lead.round()).all() or frame.valid_utc.duplicated().any():
        raise ValueError(f"Invalid hourly time axis: {run}")
    frame["lead_h"] = lead.astype("int64")
    for name in VARIABLES:
        frame[name] = pd.to_numeric(frame[name], errors="coerce").astype("float64")
    return frame[["run_init_utc", "valid_utc", "lead_h", *VARIABLES]]


def marker_path(root: Path, run: datetime) -> Path:
    return root / MARKERS / f"{run:%Y-%m-%dT%H%M}Z.http400.json"


def fetch(client: WeatherClient, root: Path, run: datetime) -> dict | None:
    """Response JSON, or None for HTTP 400 (remembered so cache-only reruns agree)."""
    marker = marker_path(root, run)
    if marker.exists():
        return None
    try:
        return client.single_run(run.strftime("%Y-%m-%dT%H:%M"))
    except requests.HTTPError as error:
        if error.response is None or error.response.status_code != 400:
            raise
        reason = error.response.text[:300]
        atomic_write(marker, (json.dumps({"run": run.isoformat(), "reason": reason})
                              + "\n").encode())
        return None


def dump(root: Path = ROOT, budget: int = 800, pause_s: float = 0.12) -> dict:
    days = [FIRST_DAY + timedelta(n) for n in range((LAST_DAY - FIRST_DAY).days + 1)]
    chosen, log = [], []
    grid = None
    with WeatherClient(root, request_budget=budget) as client:
        for index, day in enumerate(days, 1):
            start, end = window(day)
            entry = {"issue_day": day.isoformat(), "tried": [], "status": "missing"}
            for kind, run in candidates(day):
                if (
                    kind == "06Z"
                    and day < DENSE_06Z_FROM
                    and (day - FIRST_DAY).days % PROBE_EVERY
                ):
                    entry["tried"].append({"run": kind, "result": "skipped_sparse"})
                    continue
                before = client.network_attempts
                data = fetch(client, root, run)
                if client.network_attempts > before and not client.cache_only:
                    time.sleep(pause_s)
                if data is None:
                    entry["tried"].append({"run": kind, "result": "http_400"})
                    continue
                cell = (data["latitude"], data["longitude"])
                grid = grid or cell
                if cell != grid:
                    raise ValueError(f"Grid changed for {run}: {cell} != {grid}")
                frame = to_frame(run, data)
                win = frame[frame.valid_utc.between(start, end)]
                nulls = int(win[CORE].isna().any(axis=1).sum()) if len(win) == 48 else 48
                entry["tried"].append({"run": kind, "result": "ok",
                                       "null_hours_in_window": nulls})
                if nulls == 0:
                    frame["run_cycle"] = run.hour
                    frame["issue_day"] = pd.Timestamp(day)
                    frame["fallback"] = kind
                    frame["in_dayahead_window"] = frame.valid_utc.between(start, end)
                    chosen.append(frame)
                    entry.update(status="ok", run=kind,
                                 run_init_utc=run.isoformat(),
                                 leads=[int(win.lead_h.min()), int(win.lead_h.max())])
                    break
            log.append(entry)
            if index % 50 == 0:
                print(f"{index}/{len(days)} days, network={client.network_attempts}",
                      flush=True)
        network = client.network_attempts

    frame = pd.concat(chosen, ignore_index=True)
    output = root / OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.parquet")
    frame.to_parquet(temporary, index=False)
    temporary.replace(output)

    report = monthly_report(log)
    since = [e for e in log if e["issue_day"] >= "2024-08-01"]
    missing_since = sum(e["status"] != "ok" for e in since) / len(since)
    decision = "go" if missing_since < 0.05 else "no-go"
    summary = {
        "days": len(days),
        "days_ok": sum(e["status"] == "ok" for e in log),
        "runs_by_cycle": frame.drop_duplicates("run_init_utc")
        .fallback.value_counts()
        .to_dict(),
        "missing_days": [e["issue_day"] for e in log if e["status"] != "ok"],
        "missing_share_since_2024_08": round(missing_since, 4),
        "decision": decision,
        "grid": grid,
        "rows": len(frame),
        "dayahead_lead_range": [
            int(frame[frame.in_dayahead_window].lead_h.min()),
            int(frame[frame.in_dayahead_window].lead_h.max()),
        ],
        "monthly": report,
        "network_attempts_this_execution": network,
        "parquet_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "provenance": "Open-Meteo Single Runs ecmwf_ifs 9 km; before 2025-10 the "
        "archive is the IFS Cycle 49R1 hindcast, from 2025-10-01 real-time open "
        "data; CC BY 4.0",
        "days_log": log,
    }
    atomic_write(root / MANIFEST, (json.dumps(summary, indent=2) + "\n").encode())
    print(json.dumps({k: v for k, v in summary.items() if k != "days_log"}, indent=2))
    return summary


def monthly_report(log: list[dict]) -> list[dict]:
    rows = []
    for entry in log:
        tried = [t for t in entry["tried"] if t["result"] != "skipped_sparse"]
        rows.append({
            "month": entry["issue_day"][:7],
            "requested": len(tried),
            "received": sum(t["result"] == "ok" for t in tried),
            "null_runs": sum(t.get("null_hours_in_window", 0) > 0 for t in tried),
            "missing_day": entry["status"] != "ok",
            "fallback": entry.get("run") not in (None, "06Z"),
        })
    table = pd.DataFrame(rows).groupby("month").agg(
        days=("month", "size"),
        requested=("requested", "sum"),
        received=("received", "sum"),
        null_runs=("null_runs", "sum"),
        missing_days=("missing_day", "sum"),
        fallback_days=("fallback", "sum"),
    )
    table["missing_pct"] = (100 * table.missing_days / table.days).round(1)
    return table.reset_index().to_dict(orient="records")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Cache and output root")
    parser.add_argument("--budget", type=int, default=800, help="Max network attempts")
    args = parser.parse_args()
    dump(args.root, args.budget)


if __name__ == "__main__":
    main()
