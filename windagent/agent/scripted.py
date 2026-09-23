"""Deterministic policy with the same decision interface as the LLM planner."""
from windagent.schemas import IssueDecision


class ScriptedPlanner:
    mode = "scripted"

    def decide(self, context: dict) -> IssueDecision:
        accepted = context["quality"]["accepted"]
        divergence = context.get("divergence_ms")
        reissue = bool(context.get("previous") and context["new_run"] and (
            context["reissue_on_new_run"] or (divergence is not None and divergence > context["threshold_ms"])
        ))
        publish = accepted and (not context.get("previous") or reissue)
        reason = "initial_issue" if not context.get("previous") else "new_nwp_run" if reissue else "no_material_change"
        if not accepted:
            reason = "quality_gate_rejected"
        return IssueDecision(
            publish=publish, reason=reason, used_runs=[context["nwp_run_init_utc"]],
            reissue_recommended=reissue,
            summary_ru="Демонстрационный прогноз: не использовать для оценки качества модели."
            if context["quality"]["data_kind"] == "demo" else "Прогноз прошёл проверку входных данных.",
        )
