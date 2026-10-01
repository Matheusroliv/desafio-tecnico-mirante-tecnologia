import copy
import time

from modernize.graph.state import PipelineState, empty_report
from modernize.observability.tracing import node_span
from modernize.persistence.history import HistoryRepository


def persist_node(state: PipelineState, repo: HistoryRepository) -> dict:
    with node_span("persist") as span:
        status = state.get("status") or "falha"
        report = copy.deepcopy(state.get("report") or empty_report())
        started_at = state.get("started_at")
        if started_at is not None:
            report.setdefault("meta", {})["duration_ms"] = round((time.monotonic() - started_at) * 1000)
        history_id = repo.insert(
            source_code=state.get("source_code") or "",
            generated_code=state.get("generated_code"),
            report=report,
            status=status,
        )
        span.update(output={"history_id": history_id, "status": status})
        return {"history_id": history_id, "status": status, "report": report}
