import copy

from modernize.graph.state import PipelineState
from modernize.ir.models import RoutineIR
from modernize.observability.tracing import node_span
from modernize.validation.checks import check_module


def validate_node(state: PipelineState) -> dict:
    with node_span("validate"):
        report = copy.deepcopy(state["report"])
        ir = RoutineIR.model_validate(state["ir"])
        result = check_module(ir, state.get("generated_code") or "")
        report["validation"] = result["validation"]
        return {"report": report, "status": result["status"]}
