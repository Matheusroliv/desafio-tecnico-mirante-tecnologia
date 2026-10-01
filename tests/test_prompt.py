import pytest

from conftest import load_ir
from modernize.generation.prompt import (
    POLICY,
    RISK_GUIDANCE,
    RISK_POLICY,
    build_prompt,
    decisions_for,
    strip_fence,
)


def test_prompt_nao_e_so_a_fonte() -> None:
    ir = load_ir("sp_atualizar_status_contas_inativas")
    schema = "CREATE TABLE clientes (id int);"
    prompt = build_prompt(ir, schema, "FONTE ORIGINAL")
    assert prompt.startswith(POLICY)
    assert ir.name in prompt
    assert "bulk_update" in prompt
    assert schema in prompt
    assert prompt.rstrip().endswith("FONTE ORIGINAL")
    assert prompt.strip() != "FONTE ORIGINAL"
    assert "nenhum schema informado" in build_prompt(ir, None, "FONTE")


def test_instrucao_so_para_risco_detectado() -> None:
    ir = load_ir("sp_processar_lote_taxas")
    prompt = build_prompt(ir, None, "FONTE")
    assert RISK_GUIDANCE["cursor_n_plus_1"] in prompt
    assert RISK_GUIDANCE["three_valued_logic"] not in prompt
    assert "# DECISION: cursor_n_plus_1" in prompt


def test_contrato_tipado_pelo_ir() -> None:
    prompt = build_prompt(load_ir("sp_transferir_entre_contas"), None, "FONTE")
    assert (
        "def sp_transferir_entre_contas(conn: psycopg.Connection, p_conta_origem: int, p_conta_destino: int, "
        "p_valor: Decimal, audit_conn: psycopg.Connection | None = None) -> None:"
    ) in prompt


def test_contrato_de_out_e_returns_table() -> None:
    out = build_prompt(load_ir("sp_atualizar_status_contas_inativas"), None, "FONTE")
    assert "class OutParams:\n    p_afetadas: int | None" in out
    assert "-> OutParams:" in out
    table = build_prompt(load_ir("sp_relatorio_mensal_cliente"), None, "FONTE")
    assert "class Row:" in table
    assert "    mes_referencia: datetime.date" in table
    assert "-> list[Row]:" in table
    assert "from modernized.fn_saldo_cliente import fn_saldo_cliente" in table
    scalar = build_prompt(load_ir("fn_saldo_cliente"), None, "FONTE")
    assert "-> Decimal:" in scalar
    assert "Nao invente comentario DECISION" in scalar


def test_prompt_de_reparo_traz_codigo_e_achados() -> None:
    ir = load_ir("fn_saldo_cliente")
    prompt = build_prompt(ir, None, "FONTE", previous_code="def x(): pass", feedback=["ruff linha 1: F821"])
    assert "REPARO" in prompt
    assert "def x(): pass" in prompt
    assert "- ruff linha 1: F821" in prompt
    assert "REPARO" not in build_prompt(ir, None, "FONTE")


def test_decisoes_seguem_a_politica() -> None:
    ir = load_ir("sp_atualizar_status_contas_inativas")
    decisions = {item.risk_id: item for item in decisions_for(ir)}
    for risk in ir.risks:
        assert decisions[risk.id].action == RISK_POLICY[risk.id][0]
    assert decisions["op:update"].action == "delegated_sql"
    assert "make_interval" in decisions["op:update"].rationale


def test_catalogos_cobrem_os_mesmos_riscos() -> None:
    assert set(RISK_POLICY) == set(RISK_GUIDANCE)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("def f():\n    return 1", "def f():\n    return 1"),
        ("```python\ndef f():\n    return 1\n```", "def f():\n    return 1"),
        ("Aqui esta:\n```python\ndef f():\n    return 1\n```\nFim.", "def f():\n    return 1"),
        ("```\nx = 1", "x = 1"),
    ],
)
def test_strip_fence(raw: str, expected: str) -> None:
    assert strip_fence(raw) == expected
