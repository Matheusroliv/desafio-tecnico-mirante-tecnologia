"""Integracao com Langfuse (SDK v4, OpenTelemetry).

Arvore de observacoes por execucao da pipeline::

    trace "modernize"            <- pipeline_trace (API / runner da metrica)
      span "parse"               <- node_span em cada no do grafo
      span "analyze"
      span "generate"
        generation "llm"         <- llm_generation no adaptador do LLM (modelo, tokens, latencia, custo)
      span "validate"
      span "persist"
    score contract_fidelity / behavioral_equivalence  <- record_score com o trace_id

Sem LANGFUSE_PUBLIC_KEY e LANGFUSE_SECRET_KEY tudo vira no-op. Falha do Langfuse
nunca derruba a pipeline: a observabilidade e acessoria.
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def _client() -> Any | None:
    if not enabled():
        return None
    os.environ.setdefault("OTEL_SERVICE_NAME", "modernize-pipeline")
    try:
        from langfuse import get_client

        return get_client()
    except Exception:  # pragma: no cover - depende do ambiente
        logger.warning("Langfuse indisponivel; seguindo sem tracing", exc_info=True)
        return None


@dataclass
class ObservationHandle:
    """Alca estavel para atualizar uma observacao, com ou sem Langfuse."""

    trace_id: str | None = None
    _observation: Any = field(default=None, repr=False)

    def update(self, **fields: Any) -> None:
        if self._observation is None:
            return
        try:
            self._observation.update(**fields)
        except Exception:  # pragma: no cover - defensivo
            logger.debug("falha ao atualizar observacao", exc_info=True)


@contextmanager
def _observation(as_type: str, name: str, **fields: Any) -> Iterator[ObservationHandle]:
    client = _client()
    if client is None:
        yield ObservationHandle()
        return
    try:
        manager = client.start_as_current_observation(as_type=as_type, name=name, **fields)
        observation = manager.__enter__()
    except Exception:  # pragma: no cover - defensivo
        logger.debug("falha ao abrir observacao %s", name, exc_info=True)
        yield ObservationHandle()
        return
    handle = ObservationHandle(trace_id=getattr(observation, "trace_id", None), _observation=observation)
    try:
        yield handle
    except BaseException as exc:
        handle.update(level="ERROR", status_message=str(exc)[:500])
        manager.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        manager.__exit__(None, None, None)


@contextmanager
def pipeline_trace(name: str, *, input: Any = None, metadata: dict | None = None) -> Iterator[ObservationHandle]:
    """Observacao raiz: um trace por execucao da pipeline."""
    with _observation("chain", name, input=input, metadata=metadata) as handle:
        yield handle


@contextmanager
def node_span(name: str) -> Iterator[ObservationHandle]:
    """Span filho do trace corrente, um por no do grafo."""
    with _observation("span", name) as handle:
        yield handle


@contextmanager
def llm_generation(*, model: str, prompt: str, model_parameters: dict | None = None) -> Iterator[ObservationHandle]:
    """Observacao do tipo generation: modelo, prompt, resposta, tokens e latencia."""
    with _observation(
        "generation",
        "llm",
        model=model,
        input=prompt,
        model_parameters=model_parameters,
    ) as handle:
        yield handle


def record_score(name: str, value: float, trace_id: str | None, comment: str | None = None) -> None:
    client = _client()
    if client is None or trace_id is None:
        return
    try:
        client.create_score(name=name, value=value, data_type="NUMERIC", trace_id=trace_id, comment=comment)
    except Exception:  # pragma: no cover - defensivo
        logger.debug("falha ao registrar score %s", name, exc_info=True)


def flush() -> None:
    client = _client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:  # pragma: no cover - defensivo
        logger.debug("falha no flush do Langfuse", exc_info=True)
