"""LLM-планировщик не может остановить выпуск: сбой или непроверяемый ответ откатывается на правила."""
import json
from datetime import datetime, timezone
from pathlib import Path

from windagent.agent.runtime import run_issue
from windagent.schemas import IssueDecision

FIXTURES = Path(__file__).parent / "fixtures" / "nwp"
AT = datetime(2026, 1, 31, 18, tzinfo=timezone.utc)


class BrokenPlanner:
    mode = "openai"
    model = "stub"

    def decide(self, context):
        raise TimeoutError("LLM API timed out")


class InventingPlanner:
    mode = "openai"
    model = "stub"

    def decide(self, context):
        return IssueDecision(publish=True, reason="initial_issue", used_runs=["2026-01-31T12:00:00Z"],
                             summary_ru="Ссылается на ран, которого не было на момент выпуска.")


class WithholdingPlanner:
    mode = "openai"
    model = "stub"

    def decide(self, context):
        return IssueDecision(publish=False, reason="quality_gate_rejected", used_runs=[context["nwp_run_init_utc"]],
                             summary_ru="Отклонение ветра выше порога, не публикуем.")


def _decision(run_dir):
    return json.loads((run_dir / "decision.json").read_text())


def test_llm_error_falls_back_to_rules(tmp_path):
    run_dir = run_issue(AT, FIXTURES, tmp_path, demo=True, planner=BrokenPlanner())
    decision = _decision(run_dir)
    assert decision["publish"] and decision["reason"] == "initial_issue"
    assert decision["planner"] == "openai" and decision["fallback_reason"].startswith("TimeoutError")
    step = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()][7]
    assert step["fallback_reason"] == decision["fallback_reason"]


def test_llm_invented_run_is_rejected(tmp_path):
    run_dir = run_issue(AT, FIXTURES, tmp_path, demo=True, planner=InventingPlanner())
    decision = _decision(run_dir)
    assert decision["used_runs"] == ["2026-01-31T06:00:00Z"]
    assert "UNSUPPORTED_DECISION" in decision["fallback_reason"]


def test_llm_cannot_reject_a_passed_quality_gate(tmp_path):
    run_dir = run_issue(AT, FIXTURES, tmp_path, demo=True, planner=WithholdingPlanner())
    decision = _decision(run_dir)
    assert decision["publish"] and decision["reason"] == "initial_issue"
    assert "contradicts quality gate" in decision["fallback_reason"]
