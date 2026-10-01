import time

import pytest

from conftest import SAMPLE_B, BoomLLM, FixedLLM, SequenceLLM, reference, source
from modernize.graph.builder import build_graph, max_repair_attempts
from modernize.graph.state import initial_state
from modernize.persistence.history import MemoryHistory

PARTIAL_C = "def sp_atualizar_status_contas_inativas(conn, p_dias: int):\n    return None\n"


def _run(llm, routine: str = "fn_saldo_cliente", max_repairs: int = 1, repo: MemoryHistory | None = None):
    repo = repo if repo is not None else MemoryHistory()
    graph = build_graph(repo, llm, max_repairs=max_repairs)
    state = initial_state(source(routine), None, trace_id="trace-x", started_at=time.monotonic())
    return graph.invoke(state), repo


def test_sucesso_percorre_os_cinco_nos_e_grava_uma_linha() -> None:
    result, repo = _run(FixedLLM(SAMPLE_B))
    assert result["status"] == "sucesso"
    assert result["attempts"] == 1
    assert len(repo.rows) == 1
    row = repo.rows[0]
    assert row["status"] == "sucesso"
    assert row["generated_code"] == SAMPLE_B.strip()
    assert set(row["report"]) >= {"parsing", "semantic_analysis", "generation", "validation", "meta"}
    assert row["report"]["meta"]["trace_id"] == "trace-x"
    assert isinstance(row["report"]["meta"]["duration_ms"], int)
    assert row["report"]["generation"]["model"] == "fake"


def test_fonte_invalida_grava_falha_sem_chamar_llm() -> None:
    llm = FixedLLM(SAMPLE_B)
    repo = MemoryHistory()
    result = build_graph(repo, llm).invoke(initial_state("SELECT 1", None))
    assert result["status"] == "falha"
    assert result["generated_code"] is None
    assert llm.prompts == []
    assert len(repo.rows) == 1
    assert repo.rows[0]["generated_code"] is None
    assert repo.rows[0]["report"]["parsing"]["ok"] is False


def test_llm_indisponivel_grava_falha() -> None:
    result, repo = _run(BoomLLM())
    assert result["status"] == "falha"
    assert result["report"]["generation"]["ok"] is False
    assert "LLM indisponivel" in result["report"]["generation"]["error"]
    assert repo.rows[0]["status"] == "falha"


def test_codigo_vazio_grava_falha() -> None:
    result, _ = _run(FixedLLM("```python\n```"))
    assert result["status"] == "falha"
    assert result["report"]["generation"]["error"] == "modelo devolveu codigo vazio"


def test_parcial_sem_reparo() -> None:
    result, repo = _run(FixedLLM(PARTIAL_C), "sp_atualizar_status_contas_inativas", max_repairs=0)
    assert result["status"] == "parcial"
    assert result["attempts"] == 1
    assert repo.rows[0]["status"] == "parcial"


def test_reparo_conserta_e_registra_tentativas() -> None:
    llm = FixedLLM(PARTIAL_C, reference("sp_atualizar_status_contas_inativas"))
    result, repo = _run(llm, "sp_atualizar_status_contas_inativas", max_repairs=1)
    assert result["status"] == "sucesso"
    assert result["attempts"] == 2
    assert result["report"]["generation"]["attempts"] == 2
    assert "REPARO" in llm.prompts[1]
    assert PARTIAL_C.strip() in llm.prompts[1]
    assert "DECISION ausente" in llm.prompts[1]
    assert len(repo.rows) == 1


def test_sintaxe_invalida_tambem_vai_para_reparo() -> None:
    llm = FixedLLM("def fn_saldo_cliente(conn:", SAMPLE_B)
    result, _ = _run(llm)
    assert result["status"] == "sucesso"
    assert result["attempts"] == 2


def test_reparo_limitado_por_tentativas() -> None:
    llm = FixedLLM(PARTIAL_C)
    result, _ = _run(llm, "sp_atualizar_status_contas_inativas", max_repairs=2)
    assert result["status"] == "parcial"
    assert result["attempts"] == 3
    assert len(llm.prompts) == 3


def test_reparo_que_piora_mantem_tentativa_anterior() -> None:
    llm = FixedLLM(PARTIAL_C, "def quebrado(:")
    result, repo = _run(llm, "sp_atualizar_status_contas_inativas", max_repairs=1)
    assert result["status"] == "parcial"
    assert result["generated_code"] == PARTIAL_C.strip()
    assert any("reparo descartado" in issue for issue in result["report"]["validation"]["issues"])
    assert repo.rows[0]["generated_code"] == PARTIAL_C.strip()


def test_llm_cai_no_reparo_preserva_codigo_validado() -> None:
    result, repo = _run(SequenceLLM(PARTIAL_C), "sp_atualizar_status_contas_inativas", max_repairs=1)
    assert result["status"] == "parcial"
    assert result["generated_code"] == PARTIAL_C.strip()
    assert result["report"]["generation"]["ok"] is False
    assert repo.rows[0]["status"] == "parcial"


@pytest.mark.parametrize(("raw", "expected"), [("", 1), ("0", 0), ("3", 3), ("-2", 0), ("abc", 1)])
def test_max_repair_attempts_le_ambiente(monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", raw)
    assert max_repair_attempts() == expected


def test_validacao_dinamica_vira_feedback_de_reparo(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _fake(dsn, ir, source_code, code):
        calls.append(code)
        if "versao 2" in code:
            return {
                "score": 1.0,
                "passed": 1,
                "total": 1,
                "scenarios": [{"name": "c", "equivalent": True, "reason": "ok"}],
            }
        return {"score": 0.0, "passed": 0, "total": 1, "scenarios": [{"name": "c", "equivalent": False, "reason": "x"}]}

    monkeypatch.setattr("modernize.nodes.validate.behavioral_check", _fake)
    llm = FixedLLM(SAMPLE_B, SAMPLE_B + "\n# versao 2\n")
    graph = build_graph(MemoryHistory(), llm, max_repairs=1, behavioral_dsn="dsn")
    result = graph.invoke(initial_state(source("fn_saldo_cliente"), None))
    assert len(calls) == 2
    assert "equivalencia (c): x" in llm.prompts[1]
    assert result["status"] == "sucesso"
    assert result["report"]["validation"]["behavioral"] == {"score": 1.0, "passed": 1, "total": 1}


def test_validacao_dinamica_sem_cenarios_nao_muda_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("modernize.nodes.validate.behavioral_check", lambda *args: None)
    graph = build_graph(MemoryHistory(), FixedLLM(SAMPLE_B), max_repairs=0, behavioral_dsn="dsn")
    result = graph.invoke(initial_state(source("fn_saldo_cliente"), None))
    assert result["status"] == "sucesso"
    assert result["report"]["validation"]["behavioral"] is None


def test_reparo_com_equivalencia_pior_e_descartado(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(dsn, ir, source_code, code):
        score = 0.5 if "versao 2" not in code else 0.25
        return {
            "score": score,
            "passed": 1,
            "total": 2,
            "scenarios": [{"name": "c", "equivalent": False, "reason": "x"}],
        }

    monkeypatch.setattr("modernize.nodes.validate.behavioral_check", _fake)
    llm = FixedLLM(SAMPLE_B, SAMPLE_B + "\n# versao 2\n")
    result = build_graph(MemoryHistory(), llm, max_repairs=1, behavioral_dsn="dsn").invoke(
        initial_state(source("fn_saldo_cliente"), None)
    )
    assert result["status"] == "parcial"
    assert "versao 2" not in result["generated_code"]
    assert result["report"]["validation"]["behavioral"]["score"] == 0.5


@pytest.mark.integration
def test_reparo_guiado_pelo_banco_legado(legacy_dsn: str) -> None:
    correct = reference("sp_transferir_entre_contas")
    naive = correct.replace(
        """            if (v_status_origem is not None and v_status_origem != "ATIVA") or (
                v_status_destino is not None and v_status_destino != "ATIVA"
            ):""",
        """            if v_status_origem != "ATIVA" or v_status_destino != "ATIVA":""",
    )
    llm = FixedLLM(naive, correct)
    graph = build_graph(MemoryHistory(), llm, max_repairs=1, behavioral_dsn=legacy_dsn)
    result = graph.invoke(initial_state(source("sp_transferir_entre_contas"), None))
    assert "destino inexistente" in llm.prompts[1]
    assert result["status"] == "sucesso"
    assert result["attempts"] == 2
    assert result["report"]["validation"]["behavioral"]["score"] == 1.0


def test_empate_de_status_mantem_tentativa_com_menos_achados() -> None:
    partial_c_pior = PARTIAL_C + "\nimport os\n"
    result, _ = _run(FixedLLM(PARTIAL_C, partial_c_pior), "sp_atualizar_status_contas_inativas", max_repairs=1)
    assert result["status"] == "parcial"
    assert "import os" not in result["generated_code"]
