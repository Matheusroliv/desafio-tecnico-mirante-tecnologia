from types import SimpleNamespace

import pytest

from modernize.generation import llm as llm_module
from modernize.generation.llm import OpenAIGenerator, _extra_body
from modernize.observability import tracing
from modernize.pipeline import execute


class _FakeObservation:
    def __init__(self, store: list, name: str, fields: dict) -> None:
        self.store = store
        self.name = name
        self.fields = fields
        self.trace_id = "trace-123"
        self.updates: list[dict] = []
        self.exit: object = None

    def update(self, **fields) -> None:
        self.updates.append(fields)

    def __enter__(self):
        self.store.append(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exit = exc_type
        return False


class _FakeLangfuse:
    def __init__(self) -> None:
        self.observations: list[_FakeObservation] = []
        self.scores: list[dict] = []
        self.flushed = 0

    def start_as_current_observation(self, *, as_type: str, name: str, **fields):
        return _FakeObservation(self.observations, name, {"as_type": as_type, **fields})

    def create_score(self, **fields) -> None:
        self.scores.append(fields)

    def flush(self) -> None:
        self.flushed += 1


@pytest.fixture
def fake_langfuse(monkeypatch: pytest.MonkeyPatch) -> _FakeLangfuse:
    client = _FakeLangfuse()
    monkeypatch.setattr(tracing, "_client", lambda: client)
    return client


def test_tracing_sem_chaves_e_no_op() -> None:
    assert tracing.enabled() is False
    with tracing.pipeline_trace("modernize") as trace:
        trace.update(output={"x": 1})
        assert trace.trace_id is None
    with tracing.node_span("parse"):
        pass
    tracing.record_score("m", 1.0, "trace")
    tracing.flush()


def test_tracing_abre_arvore_e_registra_score(fake_langfuse: _FakeLangfuse) -> None:
    with tracing.pipeline_trace("modernize", input={"a": 1}) as trace:
        with tracing.node_span("parse") as span:
            span.update(output={"ok": True})
        with tracing.llm_generation(model="m", prompt="p", model_parameters={"temperature": 0}) as gen:
            gen.update(usage_details={"input": 1, "output": 2})
    assert trace.trace_id == "trace-123"
    names = [(obs.name, obs.fields["as_type"]) for obs in fake_langfuse.observations]
    assert names == [("modernize", "chain"), ("parse", "span"), ("llm", "generation")]
    assert fake_langfuse.observations[2].fields["model"] == "m"
    tracing.record_score("contract_fidelity", 0.8, trace.trace_id, comment="r")
    assert fake_langfuse.scores == [
        {"name": "contract_fidelity", "value": 0.8, "data_type": "NUMERIC", "trace_id": "trace-123", "comment": "r"}
    ]
    tracing.record_score("x", 1.0, None)
    assert len(fake_langfuse.scores) == 1
    tracing.flush()
    assert fake_langfuse.flushed == 1


def test_tracing_marca_erro_e_propaga(fake_langfuse: _FakeLangfuse) -> None:
    with pytest.raises(ValueError), tracing.node_span("validate"):
        raise ValueError("quebrou")
    observation = fake_langfuse.observations[0]
    assert observation.updates[-1]["level"] == "ERROR"
    assert observation.exit is ValueError


def test_execute_abre_trace_e_grava_trace_id(fake_langfuse: _FakeLangfuse) -> None:
    from conftest import SAMPLE_B, FixedLLM, source
    from modernize.graph.builder import build_graph
    from modernize.persistence.history import MemoryHistory

    repo = MemoryHistory()
    result = execute(build_graph(repo, FixedLLM(SAMPLE_B)), source("fn_saldo_cliente"), None)
    assert result["report"]["meta"]["trace_id"] == "trace-123"
    names = [obs.name for obs in fake_langfuse.observations]
    assert names == ["modernize", "parse", "analyze", "generate", "validate", "persist"]
    assert fake_langfuse.observations[0].updates[-1]["output"]["status"] == "sucesso"


def test_llm_sem_chave_falha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY ausente"):
        OpenAIGenerator().complete("prompt")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", None), ('{"options": {"num_ctx": 16384}}', {"options": {"num_ctx": 16384}})],
)
def test_extra_body(monkeypatch: pytest.MonkeyPatch, raw: str, expected) -> None:
    monkeypatch.setenv("OPENAI_EXTRA_BODY", raw)
    assert _extra_body() == expected


@pytest.mark.parametrize("raw", ["{nao json", "[1, 2]"])
def test_extra_body_invalido(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("OPENAI_EXTRA_BODY", raw)
    with pytest.raises(RuntimeError, match="OPENAI_EXTRA_BODY"):
        _extra_body()


def test_llm_chama_provedor_e_registra_uso(monkeypatch: pytest.MonkeyPatch, fake_langfuse: _FakeLangfuse) -> None:
    sent: dict = {}

    class _Completions:
        def create(self, **kwargs):
            sent.update(kwargs)
            usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            message = SimpleNamespace(content="def f():\n    return 1")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    class _OpenAI:
        def __init__(self, **kwargs) -> None:
            sent["client"] = kwargs
            self.chat = SimpleNamespace(completions=_Completions())

    monkeypatch.setattr("openai.OpenAI", _OpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "modelo-x")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://local/v1")
    monkeypatch.setenv("OPENAI_EXTRA_BODY", '{"options": {"num_ctx": 1}}')
    generator = OpenAIGenerator()
    assert generator.complete("PROMPT") == "def f():\n    return 1"
    assert sent["model"] == "modelo-x"
    assert sent["temperature"] == 0
    assert sent["extra_body"] == {"options": {"num_ctx": 1}}
    assert sent["messages"][0]["content"] == llm_module.SYSTEM_PROMPT
    assert sent["client"]["base_url"] == "http://local/v1"
    generation = fake_langfuse.observations[0]
    assert generation.fields["as_type"] == "generation"
    assert generation.updates[-1]["usage_details"] == {"input": 10, "output": 5, "total": 15}
