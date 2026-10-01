from pathlib import Path

from fastapi.testclient import TestClient

from modernize.analysis.analyzer import analyze
from modernize.api.app import create_app
from modernize.evaluation.fidelity import contract_score
from modernize.evaluation.runner import ORDER, run_evaluation
from modernize.generation.prompt import POLICY, build_prompt
from modernize.graph.builder import build_graph
from modernize.graph.state import initial_state
from modernize.parsing.parser import ParseFailure, parse_routine
from modernize.persistence.history import MemoryHistory

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

SAMPLE_B = """
import psycopg
from decimal import Decimal

def fn_saldo_cliente(conn: psycopg.Connection, p_cliente_id: int) -> Decimal:
    row = conn.execute(
        \"\"\"
        SELECT COALESCE(SUM(saldo), 0)
          FROM contas
         WHERE cliente_id = %s AND status = 'ATIVA'
        \"\"\",
        (p_cliente_id,),
    ).fetchone()
    return Decimal(row[0])
"""

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
        "risks": {
            "raise_exception",
            "out_parameter",
            "get_diagnostics",
            "jsonb",
            "bulk_update",
        },
        "operations": {"update", "insert"},
        "constructs": {
            "parameter_in",
            "parameter_out",
            "raise",
            "get_diagnostics",
            "jsonb",
            "bulk_update",
        },
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
        "constructs": {
            "parameter_in",
            "variable",
            "raise",
            "for_update",
            "jsonb",
            "exception_handler",
        },
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


def _load(name: str):
    return analyze(parse_routine((FIXTURES / f"{name}.sql").read_text(encoding="utf-8")))


def test_parser_rejeita_entrada_que_nao_e_rotina():
    try:
        parse_routine("SELECT 1")
    except ParseFailure as exc:
        assert exc.message
    else:
        raise AssertionError("SELECT 1 deveria falhar")
    try:
        parse_routine("   ")
    except ParseFailure:
        return
    raise AssertionError("fonte vazia deveria falhar")


def test_anexos_batem_com_o_ouro():
    for name, expected in EXPECTED.items():
        ir = _load(name)
        assert ir.kind == expected["kind"]
        assert ir.language == "plpgsql"
        assert ir.set_returning is expected["set_returning"]
        assert ir.returns == expected["returns"]
        assert [(item.name, item.mode, item.type_name) for item in ir.parameters] == expected["params"]
        assert {risk.id for risk in ir.risks} == expected["risks"]
        assert {item.kind for item in ir.operations} == expected["operations"]
        assert expected["constructs"] <= set(ir.constructs)
        assert ir.dependencies == expected["dependencies"]


def test_migracao_tem_as_colunas_pedidas():
    sql = (ROOT / "db" / "migrations" / "001_init.sql").read_text(encoding="utf-8")
    for column in ("source_code", "generated_code", "report", "status", "created_at"):
        assert column in sql
    assert "evaluation_scores" in sql


def test_prompt_nao_e_so_a_fonte():
    ir = _load("sp_atualizar_status_contas_inativas")
    schema = "CREATE TABLE clientes (id int);"
    prompt = build_prompt(ir, schema, "FONTE ORIGINAL")
    assert prompt.startswith(POLICY)
    assert ir.name in prompt
    assert "bulk_update" in prompt
    assert schema in prompt
    assert prompt.rstrip().endswith("FONTE ORIGINAL")
    assert "nenhum schema informado" in build_prompt(ir, None, "FONTE")


def test_metrica_checa_pesos():
    ir = _load("fn_saldo_cliente")
    perfect = contract_score(ir, SAMPLE_B)
    assert perfect["checks"]["ast_parse"] == 1
    assert perfect["checks"]["symbol_and_params"] == 1
    assert perfect["checks"]["decision_coverage"] == 1
    assert perfect["checks"]["operation_coverage"] == 1
    assert perfect["score"] == 1.0
    broken = contract_score(ir, "def fn_saldo_cliente(conn, p_cliente_id):\n    return 1\n")
    assert broken["checks"]["operation_coverage"] == 0
    assert broken["score"] == 0.8


def test_grafo_persiste_sucesso_falha_e_parcial():
    repo = MemoryHistory()
    graph = build_graph(repo, _Fixed(SAMPLE_B))
    source_b = (FIXTURES / "fn_saldo_cliente.sql").read_text(encoding="utf-8")
    ok = graph.invoke(initial_state(source_b, None))
    assert ok["status"] == "sucesso"
    assert len(repo.rows) == 1

    invalid = graph.invoke(initial_state("SELECT 1", None))
    assert invalid["status"] == "falha"
    assert invalid["generated_code"] is None

    graph_down = build_graph(repo, _Boom())
    down = graph_down.invoke(initial_state(source_b, None))
    assert down["status"] == "falha"
    assert down["report"]["generation"]["ok"] is False

    source_c = (FIXTURES / "sp_atualizar_status_contas_inativas.sql").read_text(encoding="utf-8")
    partial_graph = build_graph(repo, _Fixed("def sp_atualizar_status_contas_inativas(conn, p_dias: int):\n    return None\n"))
    partial = partial_graph.invoke(initial_state(source_c, None))
    assert partial["status"] == "parcial"
    assert len(repo.rows) == 4


def test_api_health_modernize_e_evaluate():
    repo = MemoryHistory()
    app = create_app(build_graph(repo, _Fixed(SAMPLE_B)), repo)
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    rejected = client.post("/modernize", json={"source_code": "  "})
    assert rejected.status_code == 422
    assert repo.rows == []
    payload = client.post("/evaluate").json()
    assert payload["metric"] == "contract_fidelity"
    assert len(payload["routines"]) == len(ORDER)
    assert len(repo.rows) == len(ORDER)
    assert len(repo.scores) == len(ORDER)
    again = run_evaluation(build_graph(repo, _Fixed(SAMPLE_B)), repo, FIXTURES)
    assert again["aggregate"] == payload["aggregate"]


class _Fixed:
    model = "fake"

    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, prompt: str) -> str:
        return self.text


class _Boom:
    model = "fake"

    def complete(self, prompt: str) -> str:
        raise RuntimeError("LLM indisponivel")
