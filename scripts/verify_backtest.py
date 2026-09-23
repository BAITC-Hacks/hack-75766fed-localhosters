"""Offline integration check for the committed ECMWF archive and saved submission."""
import csv
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from windagent.agent.runtime import run_issue
from windagent.backtest import PRIMARY_MODEL, run_and_write, run_window
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
    # v0 through the agent must reproduce the direct model computation exactly
    v0_path, _ = run_and_write("test", "v0")
    reference = run_window("test")
    with v0_path.open() as file:
        agent_rows = list(csv.DictReader(file))
    ref_rows = [{k: str(v) for k, v in row.items()} for row in reference.astype(object).to_dict("records")]
    assert [(r["issue_time_utc"], r["turbine"], r["lead_h"], float(r["p50"])) for r in agent_rows] == \
           [(r["issue_time_utc"], r["turbine"], r["lead_h"], float(r["p50"])) for r in ref_rows]
    # the submission model: every issue goes through the agent (run_issue)
    path, flat_path = run_and_write("test", PRIMARY_MODEL)
    runs_root = Path("runs/backtest") / PRIMARY_MODEL / "test"
    dayahead = sorted(runs_root.glob("*-dayahead"))
    reissue = sorted(runs_root.glob("*-reissue"))
    assert len(dayahead) == 29 and len(reissue) == 29, (len(dayahead), len(reissue))
    for run_dir in dayahead + reissue:
        trace = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]
        assert len(trace) == 11 and all("ms" not in row for row in trace), run_dir
        assert json.loads((run_dir / "status.json").read_text())["status"] == "published", run_dir
    for run_dir in reissue:
        inputs = json.loads((run_dir / "inputs.json").read_text())
        assert inputs["nwp_run_init_utc"].endswith("T12:00:00Z"), run_dir
        assert json.loads((run_dir / "decision.json").read_text())["reissue_recommended"], run_dir
    # ...and the submission model through the agent == the same model computed directly
    with path.open() as file:
        agent_primary = [(r["issue_time_utc"], r["turbine"], r["lead_h"], float(r["p50"])) for r in csv.DictReader(file)]
    direct_primary = run_window("test", PRIMARY_MODEL)
    assert agent_primary == [(r.issue_time_utc, r.turbine, str(r.lead_h), float(r.p50)) for r in direct_primary.itertuples()]
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
    print(f"PASS: {PRIMARY_MODEL} — 29 issues via agent + 29 reissues (11-step traces); v0 and {PRIMARY_MODEL} agent == direct model; "
          "2784 rows, 1344 hourly rows, all as-of, 19Z rejects 12Z, real 06Z→12Z revision")


if __name__ == "__main__":
    main()
