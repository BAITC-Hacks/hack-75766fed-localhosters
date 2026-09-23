"""Conservative ECMWF publication policy for historical replay."""
from datetime import datetime, timedelta, timezone

AVAIL_LAG = {"ecmwf_ifs": {0: 8, 6: 7, 12: 8, 18: 7}}


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("Clock requires timezone-aware UTC")
    return value.astimezone(timezone.utc)


def available_at(run_init: datetime, model: str = "ecmwf_ifs") -> datetime:
    run_init = require_utc(run_init)
    if run_init.hour not in (0, 6, 12, 18) or run_init.minute or run_init.second:
        raise ValueError("Invalid ECMWF cycle")
    return run_init + timedelta(hours=AVAIL_LAG[model][run_init.hour])


def allowed_runs(issue_time: datetime, runs, model: str = "ecmwf_ifs"):
    issue_time = require_utc(issue_time)
    return sorted((run for run in runs if available_at(run, model) <= issue_time))


def latest_available_run(issue_time: datetime, runs, model: str = "ecmwf_ifs"):
    eligible = allowed_runs(issue_time, runs, model)
    if not eligible:
        raise ValueError("WEATHER_NOT_AVAILABLE: no run published by issue time")
    return eligible[-1]


def assert_as_of(issue_time: datetime, run_init: datetime, targets, model: str = "ecmwf_ifs"):
    issue_time = require_utc(issue_time)
    if available_at(run_init, model) > issue_time:
        raise ValueError("NWP_LEAKAGE: run published after issue")
    # UTC target labels are interval starts. The interval end must be future.
    if any(require_utc(target) + timedelta(hours=1) <= issue_time for target in targets):
        raise ValueError("TARGET_LEAKAGE: target interval ended before issue")
