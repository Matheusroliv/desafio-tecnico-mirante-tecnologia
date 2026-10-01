import os
from pathlib import Path

import pytest

from modernize.analysis.analyzer import analyze
from modernize.env import load_local_env
from modernize.ir.models import RoutineIR
from modernize.parsing.parser import parse_routine

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
REFERENCE = Path(__file__).resolve().parent / "reference"

ROUTINES = [
    "fn_saldo_cliente",
    "sp_atualizar_status_contas_inativas",
    "sp_transferir_entre_contas",
    "sp_processar_lote_taxas",
    "sp_relatorio_mensal_cliente",
]

SAMPLE_B = '''import psycopg
from decimal import Decimal


def fn_saldo_cliente(conn: psycopg.Connection, p_cliente_id: int) -> Decimal:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(saldo), 0)
          FROM contas
         WHERE cliente_id = %s AND status = 'ATIVA'
        """,
        (p_cliente_id,),
    ).fetchone()
    return row[0]
'''


def source(name: str) -> str:
    return (FIXTURES / f"{name}.sql").read_text(encoding="utf-8")


def reference(name: str) -> str:
    return (REFERENCE / f"{name}.py").read_text(encoding="utf-8")


def load_ir(name: str) -> RoutineIR:
    return analyze(parse_routine(source(name)))


class FixedLLM:
    """LLM falso que devolve respostas fixas, em ordem; a ultima se repete."""

    model = "fake"

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.texts) - 1)
        return self.texts[index]


class BoomLLM:
    model = "fake"

    def complete(self, prompt: str) -> str:
        raise RuntimeError("LLM indisponivel")


class SequenceLLM:
    """Primeira chamada devolve texto; as seguintes levantam erro (LLM cai no reparo)."""

    model = "fake"

    def __init__(self, first: str) -> None:
        self.first = first
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            return self.first
        raise RuntimeError("LLM caiu no reparo")


@pytest.fixture(autouse=True)
def _no_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


def _reachable(dsn: str) -> str | None:
    import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=3):
            return None
    except Exception as exc:
        return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def _dsn(name: str, default: str) -> str:
    load_local_env()
    return os.environ.get(name) or default


@pytest.fixture(scope="session")
def pipeline_dsn() -> str:
    dsn = _dsn("DATABASE_URL", "postgresql://pipeline:pipeline@localhost:5432/pipeline")
    problem = _reachable(dsn)
    if problem:
        pytest.skip(f"Postgres da pipeline indisponivel ({problem}); suba com docker compose up -d postgres")
    return dsn


@pytest.fixture(scope="session")
def legacy_dsn() -> str:
    dsn = _dsn("LEGACY_DATABASE_URL", "postgresql://pipeline:pipeline@localhost:5432/legacy")
    problem = _reachable(dsn)
    if problem:
        pytest.skip(f"database legacy indisponivel ({problem}); suba com docker compose up -d postgres")
    return dsn
