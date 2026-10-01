import copy

from modernize.generation.prompt import build_prompt, decisions_for, strip_fence
from modernize.graph.state import PipelineState
from modernize.ir.models import RoutineIR
from modernize.observability.tracing import node_span


def generate_node(state: PipelineState, llm) -> dict:
    with node_span("generate"):
        report = copy.deepcopy(state["report"])
        ir = RoutineIR.model_validate(state["ir"])
        decisions = [item.model_dump() for item in decisions_for(ir)]
        model = getattr(llm, "model", None)
        try:
            code = strip_fence(
                llm.complete(build_prompt(ir, state.get("schema_ddl"), state["source_code"]))
            )
        except Exception as exc:
            report["generation"] = {
                "ok": False,
                "error": str(exc),
                "model": model,
                "decisions": decisions,
            }
            return {
                "report": report,
                "status": "falha",
                "error": str(exc),
                "generated_code": None,
            }
        if not code.strip():
            report["generation"] = {
                "ok": False,
                "error": "modelo devolveu codigo vazio",
                "model": model,
                "decisions": decisions,
            }
            return {
                "report": report,
                "status": "falha",
                "error": "modelo devolveu codigo vazio",
                "generated_code": None,
            }
        report["generation"] = {"ok": True, "error": None, "model": model, "decisions": decisions}
        return {"report": report, "generated_code": code}
