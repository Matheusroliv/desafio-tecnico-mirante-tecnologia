from fastapi.testclient import TestClient

from conftest import SAMPLE_B, FixedLLM, source
from modernize.api.app import create_app
from modernize.evaluation.runner import ORDER
from modernize.graph.builder import build_graph
from modernize.persistence.history import MemoryHistory


def _client(repo=None, llm=None) -> tuple[TestClient, MemoryHistory]:
    repo = repo if repo is not None else MemoryHistory()
    graph = build_graph(repo, llm or FixedLLM(SAMPLE_B), max_repairs=0)
    return TestClient(create_app(graph, repo)), repo


def test_health() -> None:
    client, _ = _client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_modernize_rejeita_corpo_invalido_sem_gravar() -> None:
    client, repo = _client()
    assert client.post("/modernize", json={"source_code": "  "}).status_code == 422
    assert client.post("/modernize", json={}).status_code == 422
    assert client.post("/modernize", json={"source_code": "x", "extra": 1}).status_code == 422
    assert client.post("/modernize", json={"source_code": "x" * 1_048_577}).status_code == 422
    assert repo.rows == []


def test_modernize_devolve_codigo_e_relatorio() -> None:
    client, repo = _client()
    response = client.post("/modernize", json={"source_code": source("fn_saldo_cliente"), "schema_ddl": "CREATE ..."})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sucesso"
    assert body["id"] == 1
    assert "def fn_saldo_cliente" in body["generated_code"]
    assert {"parsing", "semantic_analysis", "generation", "validation"} <= set(body["report"])
    assert len(repo.rows) == 1


def test_modernize_falha_de_pipeline_e_http_200() -> None:
    client, repo = _client()
    response = client.post("/modernize", json={"source_code": "SELECT 1"})
    assert response.status_code == 200
    assert response.json()["status"] == "falha"
    assert repo.rows[0]["status"] == "falha"


class _FlakyRepo(MemoryHistory):
    """Falha nas primeiras ``failures`` escritas (simula banco fora no no persist)."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def insert(self, **kwargs):  # type: ignore[override]
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("banco fora")
        return super().insert(**kwargs)


def test_persist_falha_e_api_grava_a_falha_uma_vez() -> None:
    repo = _FlakyRepo(failures=1)
    client, _ = _client(repo=repo)
    response = client.post("/modernize", json={"source_code": source("fn_saldo_cliente")})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "falha"
    assert "pipeline abortou" in body["report"]["parsing"]["error"]
    assert len(repo.rows) == 1
    assert repo.rows[0]["report"]["parsing"]["error"].startswith("pipeline abortou")


def test_banco_fora_duas_vezes_e_http_500() -> None:
    client, repo = _client(repo=_FlakyRepo(failures=2))
    response = client.post("/modernize", json={"source_code": source("fn_saldo_cliente")})
    assert response.status_code == 500
    assert repo.rows == []


def test_history_le_a_linha_gravada() -> None:
    client, _ = _client()
    created = client.post("/modernize", json={"source_code": source("fn_saldo_cliente")}).json()
    response = client.get(f"/history/{created['id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "sucesso"
    assert response.json()["generated_code"] == created["generated_code"]
    assert client.get("/history/999").status_code == 404


class _BrokenReadRepo(MemoryHistory):
    def get(self, history_id: int):
        raise RuntimeError("banco fora")


def test_history_banco_fora_e_503() -> None:
    client, _ = _client(repo=_BrokenReadRepo())
    assert client.get("/history/1").status_code == 503


def test_evaluate_roda_os_cinco_anexos(monkeypatch) -> None:
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    client, repo = _client()
    payload = client.post("/evaluate").json()
    assert payload["metric"] == "contract_fidelity"
    assert payload["behavioral_aggregate"] is None
    assert len(payload["routines"]) == len(ORDER)
    assert len(repo.rows) == len(ORDER)
    assert len(repo.scores) == len(ORDER)
    first = payload["routines"][0]
    assert first["name"] == "fn_saldo_cliente"
    assert first["score"] == 1.0
    assert first["behavioral_equivalence"] is None
