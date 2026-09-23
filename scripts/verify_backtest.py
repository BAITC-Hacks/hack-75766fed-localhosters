"""Offline integration check for the committed ECMWF archive and saved submission."""
import csv
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from windagent.agent.runtime import run_issue
from windagent.backtest import run_and_write
from windagent.clock import assert_as_of, latest_available_run


def main():
    cache = Path("data/nwp_cache/single_runs/ecmwf_ifs")
    runs = [datetime.strptime(p.stem, "%Y-%m-%dT%H%MZ").replace(tzinfo=timezone.utc)
            for p in cache.glob("????-??-??T????Z.json")]
    at19 = datetime(2026, 1, 31, 19, tzinfo=timezone.utc)
    assert latest_available_run(at19, runs).hour == 6
    try:
        assert_as_of(at19, datetime(2026, 1, 31, 12, tzinfo=timezone.utc), [at19])
    except ValueError:
        pass
    else:
        raise AssertionError("12Z was accepted at 19:00 UTC")
    path, flat_path = run_and_write("test")
    with path.open() as file:
        rows = list(csv.DictReader(file))
    with flat_path.open() as file:
        flat = list(csv.DictReader(file))
    assert len(rows) == 2784 and len(flat) == 1344
    assert len({row["issue_time_utc"] for row in rows}) == 29
    assert all(row["p50"] and row["p10"] and row["p90"] for row in rows)
    for row in rows:
        issue = datetime.fromisoformat(row["issue_time_utc"].replace("Z", "+00:00"))
        run = datetime.fromisoformat(row["nwp_run_init_utc"].replace("Z", "+00:00"))
        target = datetime.fromisoformat(row["target_time_utc"].replace("Z", "+00:00"))
        assert_as_of(issue, run, [target])
    with tempfile.TemporaryDirectory(prefix="windagent-real-") as root:
        first = run_issue(datetime(2026, 1, 31, 18, tzinfo=timezone.utc), cache, Path(root),
                          model_adapter="windagent.model.v0:predict_power")
        second = run_issue(datetime(2026, 1, 31, 20, tzinfo=timezone.utc), cache, Path(root),
                           model_adapter="windagent.model.v0:predict_power")
        with (second / "forecast.csv").open() as file:
            revision = list(csv.DictReader(file))
        assert len(revision) == 96 and all(r["nwp_run_init_utc"] == "2026-01-31T12:00:00Z" for r in revision)
        assert first != second
    print("PASS: 29 issues, 2784 rows, 1344 hourly rows, all as-of, 19Z rejects 12Z, real 06Z→12Z revision")


if __name__ == "__main__":
    main()
