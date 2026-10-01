import pytest

from modernize.graph.state import empty_report
from modernize.persistence.history import MemoryHistory, PsycopgHistory


def test_memoria_grava_e_le() -> None:
    repo = MemoryHistory()
    first = repo.insert(source_code="a", generated_code=None, report=empty_report(), status="falha")
    second = repo.insert(source_code="b", generated_code="x = 1", report=empty_report(), status="sucesso")
    assert (first, second) == (1, 2)
    assert repo.get(2)["generated_code"] == "x = 1"
    assert repo.get(3) is None
    assert repo.insert_score(history_id=1, routine_name="r", metric="m", score=0.5, detail={}) == 1


def test_postgres_sem_dsn_falha_com_mensagem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL ausente"):
        PsycopgHistory(dsn="").insert(source_code="a", generated_code=None, report={}, status="falha")


@pytest.fixture
def created_ids(pipeline_dsn: str):
    """Ids gravados pelo teste; apagados no fim para nao sujar o historico real."""
    import psycopg

    ids: list[int] = []
    yield ids
    if ids:
        with psycopg.connect(pipeline_dsn) as conn:
            conn.execute("DELETE FROM evaluation_scores WHERE history_id = ANY(%s)", (ids,))
            conn.execute("DELETE FROM modernization_history WHERE id = ANY(%s)", (ids,))


@pytest.mark.integration
def test_postgres_grava_os_tres_desfechos_e_scores(pipeline_dsn: str, created_ids: list[int]) -> None:
    repo = PsycopgHistory(pipeline_dsn)
    ids = {
        status: repo.insert(
            source_code=f"-- {status}",
            generated_code=None if status == "falha" else "x = 1",
            report=empty_report("trace-1"),
            status=status,
        )
        for status in ("sucesso", "parcial", "falha")
    }
    created_ids.extend(ids.values())
    for status, history_id in ids.items():
        row = repo.get(history_id)
        assert row is not None
        assert row["status"] == status
        assert row["report"]["meta"]["trace_id"] == "trace-1"
        assert (row["generated_code"] is None) is (status == "falha")
        assert row["created_at"] is not None
    score_id = repo.insert_score(
        history_id=ids["sucesso"], routine_name="r", metric="contract_fidelity", score=0.8, detail={"a": 1}
    )
    assert score_id > 0
    assert repo.get(10**12) is None


@pytest.mark.integration
def test_postgres_rejeita_status_fora_do_dominio(pipeline_dsn: str) -> None:
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        PsycopgHistory(pipeline_dsn).insert(source_code="x", generated_code=None, report={}, status="ok")
