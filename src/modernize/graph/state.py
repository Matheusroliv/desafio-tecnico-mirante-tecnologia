from typing import TypedDict


class PipelineState(TypedDict, total=False):
    source_code: str
    schema_ddl: str | None
    ir: dict | None
    risks: list
    generated_code: str | None
    report: dict
    status: str
    error: str | None
    history_id: int | None


def empty_report() -> dict:
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
        "generation": {"ok": False, "error": None, "model": None, "decisions": []},
        "validation": {
            "ok": False,
            "ast_parse_ok": False,
            "ruff_ok": False,
            "symbol_ok": False,
            "issues": [],
        },
    }


def initial_state(source_code: str, schema_ddl: str | None) -> PipelineState:
    return {
        "source_code": source_code,
        "schema_ddl": schema_ddl,
        "ir": None,
        "risks": [],
        "generated_code": None,
        "report": empty_report(),
        "error": None,
        "history_id": None,
    }
