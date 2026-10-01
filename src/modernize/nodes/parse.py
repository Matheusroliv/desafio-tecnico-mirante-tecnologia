import copy

from modernize.graph.state import PipelineState
from modernize.observability.tracing import node_span
from modernize.parsing.parser import ParseFailure, parse_routine


def parse_node(state: PipelineState) -> dict:
    with node_span("parse"):
        report = copy.deepcopy(state["report"])
        try:
            ir = parse_routine(state["source_code"])
        except ParseFailure as exc:
            report["parsing"] = {
                "ok": False,
                "error": exc.message,
                "routine_name": None,
                "routine_kind": None,
            }
            return {"report": report, "status": "falha", "error": exc.message, "ir": None}
        report["parsing"] = {
            "ok": True,
            "error": None,
            "routine_name": ir.name,
            "routine_kind": ir.kind,
        }
        return {"report": report, "ir": ir.model_dump(), "error": None}
