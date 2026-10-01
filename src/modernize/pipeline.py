"""Execucao de uma rodada da pipeline com trace raiz no Langfuse.

API e runner da metrica usam a mesma funcao, entao a arvore de observacoes e o
mesmo ``report.meta`` saem dos dois caminhos.
"""

import time
from typing import Any

from modernize.graph.state import PipelineState, initial_state
from modernize.observability.tracing import pipeline_trace


def execute(compiled_graph: Any, source_code: str, schema_ddl: str | None, *, origin: str = "api") -> PipelineState:
    with pipeline_trace(
        "modernize",
        input={"source_chars": len(source_code), "schema_ddl": bool(schema_ddl), "origin": origin},
        metadata={"origin": origin},
    ) as trace:
        state = initial_state(source_code, schema_ddl, trace_id=trace.trace_id, started_at=time.monotonic())
        result: PipelineState = compiled_graph.invoke(state)
        trace.update(
            output={
                "status": result.get("status"),
                "history_id": result.get("history_id"),
                "routine": (result.get("report") or {}).get("parsing", {}).get("routine_name"),
                "attempts": result.get("attempts"),
            }
        )
        return result
