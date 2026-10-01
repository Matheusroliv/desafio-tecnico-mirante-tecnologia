from typing import Literal, TypedDict

PIPELINE_VERSION = "0.2.0"

Status = Literal["sucesso", "falha", "parcial"]


class PipelineState(TypedDict, total=False):
    source_code: str
    schema_ddl: str | None
    ir: dict | None
    risks: list[dict]
    generated_code: str | None
    report: dict
    status: Status
    error: str | None
    history_id: int | None
    attempts: int
    feedback: list[str]
    previous: dict | None
    started_at: float


def empty_report(trace_id: str | None = None) -> dict:
    return {
        "parsing": {
            "ok": False,
            "error": None,
            "routine_name": None,
            "routine_kind": None,
        },
        "semantic_analysis": {
            "ok": False,
            "constructs": [],
            "risks": [],
            "operations": [],
            "dependencies": [],
        },
        "generation": {"ok": False, "error": None, "model": None, "attempts": 0, "decisions": []},
        "validation": {
            "ok": False,
            "ast_parse_ok": False,
            "ruff_ok": False,
            "symbol_ok": False,
            "policy_ok": False,
            "policy_issues": [],
            "behavioral": None,
            "issues": [],
        },
        "meta": {"trace_id": trace_id, "duration_ms": None, "pipeline_version": PIPELINE_VERSION},
    }


def initial_state(
    source_code: str,
    schema_ddl: str | None,
    trace_id: str | None = None,
    started_at: float | None = None,
) -> PipelineState:
    state: PipelineState = {
        "source_code": source_code,
        "schema_ddl": schema_ddl,
        "ir": None,
        "risks": [],
        "generated_code": None,
        "report": empty_report(trace_id),
        "error": None,
        "history_id": None,
        "attempts": 0,
        "feedback": [],
        "previous": None,
    }
    if started_at is not None:
        state["started_at"] = started_at
    return state
