"""Behavioral acceptance run, including deliberate leakage and missing-hour failures."""
import csv
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from windagent.agent.runtime import run_issue
from windagent.agent.planner import agent
from windagent.schemas import IssueDecision
from pydantic_ai import models
from pydantic_ai.models.test import TestModel


def main():
    models.ALLOW_MODEL_REQUESTS = False
    sample = IssueDecision(publish=True, reason="fixture", used_runs=["2026-01-31T06:00:00Z"], summary_ru="Демо")
    result = agent.run_sync("Validate planner output contract", model=TestModel(custom_output_args=sample.model_dump()),
                            deps={"quality": {"accepted": True}, "nwp_run_init_utc": sample.used_runs[0]})
    assert isinstance(result.output, IssueDecision)
    with tempfile.TemporaryDirectory(prefix="windagent-verify-") as temporary:
        root = Path(temporary)
        at = datetime(2026, 1, 31, 18, tzinfo=timezone.utc)
        cache = Path("tests/fixtures/nwp")
        first = run_issue(at, cache, root / "runs", demo=True)
        second = run_issue(at.replace(hour=20), cache, root / "runs", demo=True)
        for path, run in [(first, "06"), (second, "12")]:
            trace = [json.loads(line) for line in (path / "trace.jsonl").read_text().splitlines()]
            assert len(trace) == 11
            assert trace[2]["result_summary"]["nwp_run_init_utc"] == f"2026-01-31T{run}:00:00Z"
            with (path / "forecast.csv").open() as file:
                rows = list(csv.DictReader(file))
            assert len(rows) == 96
            assert all(0 <= float(row["point"]) <= 1 and row["prediction_kind"] == "demo" for row in rows)
            assert all(row["p10"] == row["p90"] == "" for row in rows)
        compare = json.loads((second / "comparison.json").read_text())
        assert compare["overlap_hours"] == 92 and compare["mean_abs_delta"] > 0
        assert json.loads((second / "decision.json").read_text())["reissue_recommended"]
        # Historical replay must not read memory from the later 19:00 run.
        replay = run_issue(at, cache, root / "runs", demo=True)
        assert json.loads((replay / "comparison.json").read_text())["previous"] is None
        bad_cache = root / "late"
        bad_cache.mkdir()
        late = json.loads((cache / "single_run_2026-01-31T12.json").read_text())
        (bad_cache / "late.json").write_text(json.dumps(late))
        for label, bad in [("late run", late), ("missing hour", {**late, "run_init_utc": "2026-01-31T06:00:00Z", "available_at_utc": "2026-01-31T13:00:00Z", "hourly": late["hourly"][1:]})]:
            (bad_cache / "late.json").write_text(json.dumps(bad))
            try:
                run_issue(at, bad_cache, root / "rejected", demo=True)
            except ValueError:
                pass
            else:
                raise AssertionError(f"Accepted {label}")
        try:
            run_issue(at, cache, root / "production", demo=False)
        except ValueError:
            pass
        else:
            raise AssertionError("Demo fixture accepted in production mode")
    print("PASS: 11 steps, 96 rows, 06Z→12Z revision, no future memory, rejected late/missing/demo inputs, TestModel")


if __name__ == "__main__":
    main()
