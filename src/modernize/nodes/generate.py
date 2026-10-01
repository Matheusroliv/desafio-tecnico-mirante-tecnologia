import copy

from modernize.generation.llm import Generator
from modernize.generation.prompt import build_prompt, decisions_for, strip_fence
from modernize.graph.state import PipelineState
from modernize.ir.models import RoutineIR
from modernize.observability.tracing import node_span


def generate_node(state: PipelineState, llm: Generator) -> dict:
    with node_span("generate") as span:
        report = copy.deepcopy(state["report"])
        ir = RoutineIR.model_validate(state["ir"])
        decisions = [item.model_dump() for item in decisions_for(ir)]
        model = getattr(llm, "model", None)
        attempts = state.get("attempts", 0) + 1
        repairing = attempts > 1
        prompt = build_prompt(
            ir,
            state.get("schema_ddl"),
            state["source_code"],
            previous_code=state.get("generated_code") if repairing else None,
            feedback=state.get("feedback") if repairing else None,
        )
        span.update(metadata={"attempt": attempts, "repair": repairing})
        error: str | None = None
        code = ""
        try:
            code = strip_fence(llm.complete(prompt))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        if error is None and not code.strip():
            error = "modelo devolveu codigo vazio"
        report["generation"] = {
            "ok": error is None,
            "error": error,
            "model": model,
            "attempts": attempts,
            "decisions": decisions,
        }
        if error is not None:
            # No reparo, uma falha do LLM preserva o melhor codigo ja validado.
            keep = state.get("generated_code") if repairing else None
            return {
                "report": report,
                "status": state.get("status", "falha") if keep else "falha",
                "error": error,
                "generated_code": keep,
                "attempts": attempts,
            }
        previous = (
            {
                "code": state.get("generated_code"),
                "status": state.get("status"),
                "validation": state["report"]["validation"],
            }
            if repairing
            else None
        )
        return {"report": report, "generated_code": code, "attempts": attempts, "error": None, "previous": previous}
