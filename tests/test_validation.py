import ast

import pytest

from conftest import ROUTINES, SAMPLE_B, load_ir, reference
from modernize.validation.checks import check_module, decision_ids_missing, ruff_problems
from modernize.validation.policy import policy_problems


@pytest.mark.parametrize("name", ROUTINES)
def test_traducao_de_referencia_passa_em_tudo(name: str) -> None:
    result = check_module(load_ir(name), reference(name))
    assert result["validation"]["issues"] == []
    assert result["status"] == "sucesso"
    assert result["validation"]["policy_ok"] is True


def test_sintaxe_invalida_e_falha() -> None:
    result = check_module(load_ir("fn_saldo_cliente"), "def fn_saldo_cliente(conn:\n")
    assert result["status"] == "falha"
    assert result["validation"]["ast_parse_ok"] is False
    assert result["validation"]["ruff_ok"] is False
    assert any(issue.startswith("ast.parse linha") for issue in result["validation"]["issues"])


def test_codigo_vazio_e_falha() -> None:
    assert check_module(load_ir("fn_saldo_cliente"), "   ")["status"] == "falha"


def test_simbolo_ausente_e_parcial() -> None:
    result = check_module(load_ir("fn_saldo_cliente"), "def outra(conn):\n    return 1\n")
    assert result["status"] == "parcial"
    assert "funcao fn_saldo_cliente ausente" in result["validation"]["issues"]


def test_primeiro_parametro_e_parametros_in() -> None:
    result = check_module(load_ir("fn_saldo_cliente"), "def fn_saldo_cliente(x):\n    return 1\n")
    issues = result["validation"]["issues"]
    assert "primeiro parametro deve ser conn" in issues
    assert "parametro p_cliente_id ausente" in issues


def test_out_sem_dataclass_e_sem_return() -> None:
    code = "# " + "\n# ".join(f"DECISION: {r.id}" for r in load_ir("sp_atualizar_status_contas_inativas").risks)
    code += "\ndef sp_atualizar_status_contas_inativas(conn, p_dias):\n    pass\n"
    issues = check_module(load_ir("sp_atualizar_status_contas_inativas"), code)["validation"]["issues"]
    assert "OutParams sem os campos de saida" in issues
    assert "procedure com OUT sem return" in issues


def test_decision_ausente_e_parcial() -> None:
    ir = load_ir("sp_atualizar_status_contas_inativas")
    code = reference("sp_atualizar_status_contas_inativas").replace("# DECISION: jsonb", "")
    result = check_module(ir, code)
    assert result["status"] == "parcial"
    assert "DECISION ausente: jsonb" in result["validation"]["issues"]
    assert decision_ids_missing(code, ["jsonb", "bulk_update"]) == ["jsonb"]


def test_ruff_aponta_nome_indefinido_com_linha() -> None:
    clean, issues = ruff_problems("def f():\n    return y\n")
    assert clean is False
    assert issues == ["ruff linha 2: F821 Undefined name `y`"]
    assert ruff_problems(SAMPLE_B) == (True, [])


def _policy(code: str, routine: str = "fn_saldo_cliente") -> list[str]:
    return policy_problems(ast.parse(code), load_ir(routine))


@pytest.mark.parametrize(
    ("code", "rule"),
    [
        ("def f(conn):\n    conn.commit()\n", "no_transaction_control"),
        ("def f(conn):\n    conn.rollback()\n", "no_transaction_control"),
        ("import psycopg\ndef f():\n    psycopg.connect('x')\n", "no_connection_open"),
        ("def f(v):\n    return v * 1.10\n", "no_float"),
        ("def f(v):\n    return float(v)\n", "no_float"),
        ("def f(v):\n    print(v)\n", "no_print"),
        ("def f(conn, v):\n    conn.execute(f'SELECT {v}')\n", "no_sql_string_building"),
        ("def f(conn, v):\n    conn.execute('SELECT %s' % v)\n", "no_sql_string_building"),
        ("def f(conn, v):\n    conn.execute('SELECT ' + v)\n", "no_sql_string_building"),
        ("def f(conn, v):\n    conn.execute('SELECT {}'.format(v))\n", "no_sql_string_building"),
    ],
)
def test_politica_aponta_violacao(code: str, rule: str) -> None:
    assert any(issue.startswith(rule) for issue in _policy(code))


def test_politica_aceita_codigo_limpo() -> None:
    code = (
        "from decimal import Decimal\n"
        "import logging\n"
        "def f(conn, v):\n"
        "    logging.getLogger(__name__).warning('x')\n"
        "    with conn.transaction():\n"
        "        conn.execute('SELECT %s', (v,))\n"
        "    return v * Decimal('1.10')\n"
    )
    assert _policy(code) == []


def test_n_mais_1_so_conta_com_o_risco_de_cursor() -> None:
    code = (
        "def f(conn, linhas):\n"
        "    sql = 'SELECT percentual FROM taxas WHERE tipo_operacao = %s'\n"
        "    for linha in linhas:\n"
        "        conn.execute(sql, (linha,))\n"
    )
    assert any(item.startswith("no_query_in_loop") for item in _policy(code, "sp_processar_lote_taxas"))
    assert _policy(code, "fn_saldo_cliente") == []
    writes = (
        "def f(conn, linhas):\n    for linha in linhas:\n        conn.execute('UPDATE contas SET x = %s', (linha,))\n"
    )
    assert _policy(writes, "sp_processar_lote_taxas") == []


def test_politica_viola_status_parcial() -> None:
    code = SAMPLE_B.replace("    return row[0]", "    conn.commit()\n    return row[0]")
    result = check_module(load_ir("fn_saldo_cliente"), code)
    assert result["status"] == "parcial"
    assert result["validation"]["policy_ok"] is False
    assert result["validation"]["policy_issues"]


def test_jsonb_sem_cast_e_violacao() -> None:
    template = 'def f(conn, v):\n    conn.execute("{sql}", (v, v))\n'
    bad = template.format(sql="INSERT INTO t VALUES (jsonb_build_object('a', %s, 'b', %s::text))")
    named = template.format(sql="SELECT jsonb_build_object('a', %(v)s)")
    good = template.format(sql="SELECT jsonb_build_object('a', %s::bigint, 'b', lower(%s::text))")
    assert any(item.startswith("no_untyped_jsonb_param") for item in _policy(bad))
    assert any(item.startswith("no_untyped_jsonb_param") for item in _policy(named))
    assert _policy(good) == []
