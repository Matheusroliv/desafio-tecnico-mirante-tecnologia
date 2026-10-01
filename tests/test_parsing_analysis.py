import pytest

from conftest import load_ir
from modernize.parsing.parser import ParseFailure, parse_routine

EXPECTED = {
    "fn_saldo_cliente": {
        "kind": "function",
        "params": [("p_cliente_id", "in", "bigint")],
        "returns": "numeric",
        "set_returning": False,
        "risks": set(),
        "operations": {"select", "return"},
        "constructs": {"parameter_in", "variable"},
        "dependencies": [],
    },
    "sp_atualizar_status_contas_inativas": {
        "kind": "procedure",
        "params": [("p_dias", "in", "integer"), ("p_afetadas", "out", "integer")],
        "returns": None,
        "set_returning": False,
        "risks": {"raise_exception", "out_parameter", "get_diagnostics", "jsonb", "bulk_update"},
        "operations": {"update", "insert"},
        "constructs": {"parameter_in", "parameter_out", "raise", "get_diagnostics", "jsonb", "bulk_update"},
        "dependencies": [],
    },
    "sp_transferir_entre_contas": {
        "kind": "procedure",
        "params": [
            ("p_conta_origem", "in", "bigint"),
            ("p_conta_destino", "in", "bigint"),
            ("p_valor", "in", "numeric"),
        ],
        "returns": None,
        "set_returning": False,
        "risks": {
            "raise_exception",
            "for_update",
            "jsonb",
            "exception_handler",
            "three_valued_logic",
            "audit_lost_on_rollback",
        },
        "operations": {"select", "update", "insert"},
        "constructs": {"parameter_in", "variable", "raise", "for_update", "jsonb", "exception_handler"},
        "dependencies": [],
    },
    "sp_processar_lote_taxas": {
        "kind": "procedure",
        "params": [("p_data_referencia", "in", "date")],
        "returns": None,
        "set_returning": False,
        "risks": {"cursor_n_plus_1", "jsonb", "date_of_timestamp"},
        "operations": {"select", "update", "insert"},
        "constructs": {"parameter_in", "variable", "cursor", "loop", "jsonb", "select_into"},
        "dependencies": [],
    },
    "sp_relatorio_mensal_cliente": {
        "kind": "function",
        "params": [
            ("p_cliente_id", "in", "bigint"),
            ("p_data_inicio", "in", "date"),
            ("p_data_fim", "in", "date"),
        ],
        "returns": "record",
        "set_returning": True,
        "risks": {
            "raise_exception",
            "recursion",
            "nested_routine_call",
            "exception_handler",
            "set_returning",
            "swallowed_exception",
        },
        "operations": {"select", "return"},
        "constructs": {
            "parameter_in",
            "variable",
            "raise",
            "routine_call",
            "cte_recursive",
            "return_query",
            "exception_handler",
        },
        "dependencies": ["fn_saldo_cliente"],
    },
}


@pytest.mark.parametrize("source", ["SELECT 1", "   ", "CREATE TABLE x (id int);", "isto nao e sql"])
def test_parser_rejeita_entrada_que_nao_e_rotina(source: str) -> None:
    with pytest.raises(ParseFailure) as info:
        parse_routine(source)
    assert info.value.message


def test_parser_rejeita_duas_rotinas() -> None:
    one = "CREATE FUNCTION f() RETURNS int LANGUAGE plpgsql AS $$ BEGIN RETURN 1; END; $$;"
    with pytest.raises(ParseFailure):
        parse_routine(one + "\n" + one.replace(" f(", " g("))


@pytest.mark.parametrize("name", list(EXPECTED))
def test_anexos_batem_com_o_ouro(name: str) -> None:
    expected = EXPECTED[name]
    ir = load_ir(name)
    assert ir.name == name
    assert ir.kind == expected["kind"]
    assert ir.language == "plpgsql"
    assert ir.set_returning is expected["set_returning"]
    assert ir.returns == expected["returns"]
    assert [(item.name, item.mode, item.type_name) for item in ir.parameters] == expected["params"]
    assert {risk.id for risk in ir.risks} == expected["risks"]
    assert {item.kind for item in ir.operations} == expected["operations"]
    assert expected["constructs"] <= set(ir.constructs)
    assert ir.dependencies == expected["dependencies"]


def test_variaveis_tem_tipo_e_ignoram_implicitas() -> None:
    ir = load_ir("sp_processar_lote_taxas")
    types = {item.name: item.type_name for item in ir.variables}
    assert types["v_id"] == "bigint"
    assert types["v_valor"] == "numeric"
    assert types["v_count"] == "integer"
    assert not any(name.startswith("__") for name in types)
    assert "found" not in types


def test_returns_table_vira_colunas_de_retorno() -> None:
    ir = load_ir("sp_relatorio_mensal_cliente")
    assert [(item.name, item.type_name) for item in ir.return_columns] == [
        ("mes_referencia", "date"),
        ("total_creditos", "numeric"),
        ("total_debitos", "numeric"),
        ("saldo_consolidado", "numeric"),
        ("qtd_transacoes", "integer"),
    ]
    names = {item.name for item in ir.variables}
    assert names == {"v_saldo_atual"}


def test_operacoes_nao_contam_subquery() -> None:
    ir = load_ir("sp_atualizar_status_contas_inativas")
    counts = {item.kind: item.count for item in ir.operations}
    assert counts == {"update": 1, "insert": 1}
