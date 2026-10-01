import copy

from modernize.analysis.analyzer import analyze
from modernize.graph.state import PipelineState
from modernize.ir.models import RoutineIR
from modernize.observability.tracing import node_span


def analyze_node(state: PipelineState) -> dict:
    with node_span("analyze"):
        report = copy.deepcopy(state["report"])
        try:
            ir = analyze(RoutineIR.model_validate(state["ir"]))
        except Exception as exc:
            report["semantic_analysis"]["ok"] = False
            return {"report": report, "status": "falha", "error": str(exc)}
        report["semantic_analysis"] = {
            "ok": True,
            "constructs": ir.constructs,
            "risks": [risk.model_dump() for risk in ir.risks],
            "operations": [operation.model_dump() for operation in ir.operations],
            "dependencies": ir.dependencies,
        }
        return {
            "report": report,
            "ir": ir.model_dump(),
            "risks": [risk.model_dump() for risk in ir.risks],
        }
