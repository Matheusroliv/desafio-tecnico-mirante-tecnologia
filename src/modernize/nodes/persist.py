from modernize.graph.state import PipelineState, empty_report
from modernize.observability.tracing import node_span


def persist_node(state: PipelineState, repo) -> dict:
    with node_span("persist"):
        status = state.get("status") or "falha"
        history_id = repo.insert(
            source_code=state.get("source_code") or "",
            generated_code=state.get("generated_code"),
            report=state.get("report") or empty_report(),
            status=status,
        )
        return {"history_id": history_id, "status": status}
