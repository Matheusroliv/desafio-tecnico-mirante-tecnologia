import copy

from modernize.evaluation.equivalence import behavioral_check
from modernize.graph.state import PipelineState
from modernize.ir.models import RoutineIR
from modernize.observability.tracing import node_span
from modernize.validation.checks import check_module

RANK = {"falha": 0, "parcial": 1, "sucesso": 2}
MAX_BEHAVIOR_ISSUES = 6


def validate_node(state: PipelineState, behavioral_dsn: str | None = None) -> dict:
    with node_span("validate") as span:
        report = copy.deepcopy(state["report"])
        ir = RoutineIR.model_validate(state["ir"])
        code = state.get("generated_code") or ""
        result = check_module(ir, code)
        status = result["status"]
        validation = result["validation"]
        validation["behavioral"] = None
        if behavioral_dsn and status != "falha":
            # Evolucao pedida no enunciado: comparar com a procedure original num banco de teste.
            behavior = behavioral_check(behavioral_dsn, ir, state["source_code"], code)
            if behavior is not None:
                failures = [item for item in behavior["scenarios"] if not item["equivalent"]]
                validation["behavioral"] = {
                    "score": behavior["score"],
                    "passed": behavior["passed"],
                    "total": behavior["total"],
                }
                validation["issues"] = validation["issues"] + [
                    f"equivalencia ({item['name']}): {item['reason']}" for item in failures[:MAX_BEHAVIOR_ISSUES]
                ]
                if failures:
                    status = "parcial"
                    validation["ok"] = False
        feedback = list(validation["issues"])
        update: dict = {}
        previous = state.get("previous")
        if previous and previous.get("code") and _worse(status, validation, previous):
            # O reparo piorou o resultado: mantem a tentativa anterior, registra o motivo.
            validation = copy.deepcopy(previous["validation"])
            feedback = list(validation["issues"])
            validation["issues"] = [*validation["issues"], f"reparo descartado ({status}); mantida tentativa anterior"]
            status = previous["status"]
            update["generated_code"] = previous["code"]
        report["validation"] = validation
        span.update(output={"status": status, "issues": validation["issues"], "behavioral": validation["behavioral"]})
        return {**update, "report": report, "status": status, "feedback": feedback}


def _behavior_score(validation: dict) -> float:
    behavior = validation.get("behavioral")
    return behavior["score"] if behavior else 0.0


def _worse(status: str, validation: dict, previous: dict) -> bool:
    """Ordem: status, depois equivalencia, depois quantidade de achados (empate mantem a tentativa nova)."""
    if RANK[previous["status"]] != RANK[status]:
        return RANK[previous["status"]] > RANK[status]
    if _behavior_score(previous["validation"]) != _behavior_score(validation):
        return _behavior_score(previous["validation"]) > _behavior_score(validation)
    return len(previous["validation"]["issues"]) < len(validation["issues"])
