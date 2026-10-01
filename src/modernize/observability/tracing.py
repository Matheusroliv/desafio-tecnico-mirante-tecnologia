import os
from contextlib import contextmanager


@contextmanager
def node_span(name: str):
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        yield
        return
    try:
        from langfuse import get_client

        client = get_client()
        observation = client.start_as_current_observation(as_type="span", name=name)
    except Exception:
        yield
        return
    with observation:
        yield


def record_score(name: str, value: float, trace_id: str | None = None) -> None:
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        return
    try:
        from langfuse import get_client

        get_client().create_score(
            name=name,
            value=value,
            data_type="NUMERIC",
            trace_id=trace_id,
        )
    except Exception:
        return
