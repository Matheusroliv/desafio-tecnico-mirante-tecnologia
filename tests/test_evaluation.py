import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal

import pytest

from conftest import FIXTURES, ROUTINES, SAMPLE_B, FixedLLM, load_ir, reference, source
from modernize.evaluation import equivalence
from modernize.evaluation.equivalence import (
    _compare,
    _effect,
    _legacy_call,
    _python_result,
    _typed_args,
    canonical,
    evaluate_in_subprocess,
    run_scenarios,
)
from modernize.evaluation.fidelity import contract_score
from modernize.evaluation.runner import run_evaluation
from modernize.evaluation.scenarios import SCENARIOS
from modernize.graph.builder import build_graph
from modernize.persistence.history import MemoryHistory

# ------------------------------------------------------------ fidelidade


def test_fidelidade_pesos() -> None:
    ir = load_ir("fn_saldo_cliente")
    perfect = contract_score(ir, SAMPLE_B)
    assert perfect["checks"] == {
        "ast_parse": 1,
        "symbol_and_params": 1,
        "decision_coverage": 1,
        "operation_coverage": 1,
    }
    assert perfect["score"] == 1.0
    broken = contract_score(ir, "def fn_saldo_cliente(conn, p_cliente_id):\n    return 1\n")
    assert broken["checks"]["operation_coverage"] == 0
    assert broken["score"] == 0.8
    no_return = contract_score(ir, "def fn_saldo_cliente(conn, p_cliente_id):\n    'SELECT'\n")
    assert no_return["checks"]["operation_coverage"] == 0
    invalid = contract_score(ir, "def (")
    assert invalid["checks"]["ast_parse"] == 0
    assert invalid["checks"]["symbol_and_params"] == 0
    assert contract_score(None, "x")["score"] == 0.0
    assert contract_score(ir, None)["score"] == 0.0


@pytest.mark.parametrize("name", ROUTINES)
def test_fidelidade_da_referencia_e_1(name: str) -> None:
    assert contract_score(load_ir(name), reference(name))["score"] == 1.0


# ------------------------------------------------------ normalizacao (sem banco)


@dataclass(frozen=True)
class _Out:
    a: int
    b: Decimal


def test_canonical_normaliza_numero_data_e_dataclass() -> None:
    assert canonical(Decimal("10.00")) == canonical(10) == canonical(Decimal("10")) == "10"
    assert canonical(Decimal("0.00")) == "0"
    assert canonical(dt.date(2024, 1, 1)) == "2024-01-01"
    assert canonical(_Out(1, Decimal("2.50"))) == ["1", "2.5"]
    assert canonical({"b": 1, "a": [Decimal("1.0"), None, True]}) == {"a": ["1", None, True], "b": "1"}
    assert canonical(object()).startswith("<object")


def test_python_result_desmonta_dataclass_e_tupla() -> None:
    assert _python_result([_Out(1, Decimal("2"))]) == [[1, Decimal("2")]]
    assert _python_result((1, 2)) == [1, 2]
    assert _python_result(None) is None


def test_argumentos_tipados_pelo_ir() -> None:
    args = _typed_args(load_ir("sp_transferir_entre_contas"), [1, 4, "100.00"])
    assert args == [1, 4, Decimal("100.00")]
    assert _typed_args(load_ir("sp_processar_lote_taxas"), ["2024-05-10"]) == [dt.date(2024, 5, 10)]
    assert _typed_args(load_ir("sp_atualizar_status_contas_inativas"), [None]) == [None]


def test_chamada_legada_por_tipo_de_rotina() -> None:
    assert _legacy_call(load_ir("fn_saldo_cliente")) == "SELECT fn_saldo_cliente(%s::bigint)"
    assert _legacy_call(load_ir("sp_atualizar_status_contas_inativas")) == (
        "CALL sp_atualizar_status_contas_inativas(%s::integer, NULL)"
    )
    assert _legacy_call(load_ir("sp_relatorio_mensal_cliente")).startswith("SELECT * FROM sp_relatorio_mensal_cliente(")


def test_efeito_e_comparacao() -> None:
    before = {table: {"1": {"id": "1"}} for table in equivalence.TABLES}
    after = {table: dict(rows) for table, rows in before.items()}
    after["contas"] = {"1": {"id": "1", "saldo": "9"}, "2": {"id": "2"}}
    after["taxas"] = {}
    effect = _effect(before, after)
    assert effect == {
        "contas": {"added": [{"id": "2"}], "removed": [], "changed": [{"id": "1", "saldo": "9"}]},
        "taxas": {"added": [], "removed": ["1"], "changed": []},
    }
    same = {"error": None, "result": "1", "effect": effect}
    assert _compare(same, dict(same)) == (True, "mesmo retorno e mesmo efeito")
    assert _compare(same, {**same, "result": "2"})[0] is False
    assert _compare(same, {**same, "effect": {}})[0] is False
    error = {"error": "x", "result": None, "effect": {}}
    assert _compare(error, dict(error)) == (True, "mesmo erro")
    assert _compare(error, {**error, "error": "y"})[0] is False
    assert _compare(error, same)[0] is False
    assert _compare(same, error)[0] is False


def test_modulo_que_nao_carrega_zera_os_cenarios() -> None:
    ir = load_ir("fn_saldo_cliente")
    result = run_scenarios("postgresql://nao-usado", ir, {}, {"fn_saldo_cliente": "def ("}, SCENARIOS[ir.name])
    assert result["score"] == 0.0
    assert result["total"] == len(SCENARIOS[ir.name])
    assert "nao carregou" in result["scenarios"][0]["reason"]


def test_worker_que_falha_zera_os_cenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    ir = load_ir("fn_saldo_cliente")
    result = evaluate_in_subprocess(
        "postgresql://invalido:1/nada?connect_timeout=1",
        ir,
        {ir.name: source(ir.name)},
        {ir.name: SAMPLE_B},
        SCENARIOS[ir.name][:1],
    )
    assert result["score"] == 0.0
    assert "worker saiu com" in result["scenarios"][0]["reason"]

    def _timeout(*args, **kwargs):
        raise equivalence.subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(equivalence.subprocess, "run", _timeout)
    timed_out = evaluate_in_subprocess("dsn", ir, {}, {}, SCENARIOS[ir.name][:1], timeout=1)
    assert "timeout" in timed_out["scenarios"][0]["reason"]


def test_worker_nao_herda_segredos(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def _capture(*args, **kwargs):
        seen.update(kwargs["env"])
        return equivalence.subprocess.CompletedProcess(args, 0, stdout='{"score": 1.0}\n', stderr="")

    monkeypatch.setenv("OPENAI_API_KEY", "segredo")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "segredo")
    monkeypatch.setenv("DATABASE_URL", "postgresql://segredo")
    monkeypatch.setattr(equivalence.subprocess, "run", _capture)
    ir = load_ir("fn_saldo_cliente")
    assert evaluate_in_subprocess("dsn", ir, {}, {}, [])["score"] == 1.0
    assert "segredo" not in json.dumps(seen)
    assert "PYTHONPATH" in seen


def test_worker_com_saida_invalida(monkeypatch: pytest.MonkeyPatch) -> None:
    def _garbage(*args, **kwargs):
        return equivalence.subprocess.CompletedProcess(args, 0, stdout="nao e json\n", stderr="")

    monkeypatch.setattr(equivalence.subprocess, "run", _garbage)
    result = evaluate_in_subprocess("dsn", load_ir("fn_saldo_cliente"), {}, {}, [{"name": "a", "args": [1]}])
    assert result["scenarios"][0]["reason"] == "worker devolveu saida invalida"


# ------------------------------------------------------------ runner (sem banco)


def test_runner_grava_resultados_e_scores(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    repo = MemoryHistory()
    payload = run_evaluation(build_graph(repo, FixedLLM(SAMPLE_B), max_repairs=0), repo, FIXTURES, tmp_path)
    assert payload["aggregate"] == pytest.approx(sum(r["score"] for r in payload["routines"]) / 5, abs=1e-4)
    assert payload["routines"][0]["score"] == 1.0
    assert payload["behavioral_aggregate"] is None
    written = json.loads((tmp_path / "fn_saldo_cliente" / "report.json").read_text(encoding="utf-8"))
    assert written["status"] == "sucesso"
    assert written["metrics"]["contract_fidelity"]["score"] == 1.0
    assert (tmp_path / "fn_saldo_cliente" / "module.py").read_text(encoding="utf-8").startswith("import psycopg")
    assert {row["metric"] for row in repo.scores} == {"contract_fidelity"}


def test_runner_com_equivalencia_usa_o_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _fake(dsn, ir, legacy_sources, modules, scenarios):
        calls.append(ir.name)
        assert set(modules) <= {ir.name, *ir.dependencies}
        return {"score": 0.5, "passed": 1, "total": 2, "scenarios": [{"name": "x", "equivalent": False, "reason": "r"}]}

    monkeypatch.setattr("modernize.evaluation.runner.evaluate_in_subprocess", _fake)
    repo = MemoryHistory()
    payload = run_evaluation(build_graph(repo, FixedLLM(SAMPLE_B), max_repairs=0), repo, equivalence_dsn="dsn")
    assert calls == ROUTINES
    assert payload["behavioral_aggregate"] == 0.5
    assert payload["routines"][0]["behavioral_equivalence"]["failures"] == [{"scenario": "x", "reason": "r"}]
    assert {row["metric"] for row in repo.scores} == {"contract_fidelity", "behavioral_equivalence"}


def test_runner_sem_codigo_zera_equivalencia() -> None:
    repo = MemoryHistory()
    payload = run_evaluation(build_graph(repo, FixedLLM("   "), max_repairs=0), repo, equivalence_dsn="dsn")
    assert payload["behavioral_aggregate"] == 0.0
    assert payload["aggregate"] == 0.0


# ------------------------------------------------------- integracao (Postgres)


def _references(names: list[str]) -> dict[str, str]:
    return {name: reference(name) for name in names}


@pytest.mark.integration
@pytest.mark.parametrize("name", ROUTINES)
def test_referencia_e_equivalente_ao_legado(legacy_dsn: str, name: str) -> None:
    ir = load_ir(name)
    names = [*ir.dependencies, name]
    result = run_scenarios(legacy_dsn, ir, {n: source(n) for n in names}, _references(names), SCENARIOS[name])
    failures = [(item["name"], item["reason"]) for item in result["scenarios"] if not item["equivalent"]]
    assert failures == []
    assert result["score"] == 1.0


@pytest.mark.integration
def test_traducao_ingenua_do_anexo_d_e_pega(legacy_dsn: str) -> None:
    ir = load_ir("sp_transferir_entre_contas")
    naive = reference(ir.name).replace(
        """            if (v_status_origem is not None and v_status_origem != "ATIVA") or (
                v_status_destino is not None and v_status_destino != "ATIVA"
            ):""",
        """            if v_status_origem != "ATIVA" or v_status_destino != "ATIVA":""",
    )
    assert naive != reference(ir.name)
    result = run_scenarios(legacy_dsn, ir, {ir.name: source(ir.name)}, {ir.name: naive}, SCENARIOS[ir.name])
    failed = [item["name"] for item in result["scenarios"] if not item["equivalent"]]
    assert failed == [SCENARIOS[ir.name][4]["name"]]
    assert result["score"] < 1.0


@pytest.mark.integration
def test_taxa_herdada_da_linha_anterior_e_pega(legacy_dsn: str) -> None:
    ir = load_ir("sp_processar_lote_taxas")
    naive = reference(ir.name).replace(
        "    for v_id, v_origem, v_tipo, v_valor in linhas:\n        taxa = taxas.get(v_tipo)\n",
        "    taxa = None\n"
        "    for v_id, v_origem, v_tipo, v_valor in linhas:\n"
        "        taxa = taxas.get(v_tipo) or taxa\n",
    )
    assert naive != reference(ir.name)
    result = run_scenarios(legacy_dsn, ir, {ir.name: source(ir.name)}, {ir.name: naive}, SCENARIOS[ir.name])
    assert result["score"] < 1.0


@pytest.mark.integration
def test_worker_em_subprocesso(legacy_dsn: str) -> None:
    ir = load_ir("sp_relatorio_mensal_cliente")
    names = [*ir.dependencies, ir.name]
    result = evaluate_in_subprocess(
        legacy_dsn, ir, {n: source(n) for n in names}, _references(names), SCENARIOS[ir.name]
    )
    assert result["score"] == 1.0
    assert result["passed"] == len(SCENARIOS[ir.name])


@pytest.mark.integration
def test_dependencia_nao_migrada_vira_shim_sql(legacy_dsn: str) -> None:
    from modernize.evaluation.equivalence import behavioral_check

    ir = load_ir("sp_relatorio_mensal_cliente")
    result = behavioral_check(legacy_dsn, ir, source(ir.name), reference(ir.name))
    assert result is not None
    assert result["score"] == 1.0


def test_behavioral_check_sem_cenarios() -> None:
    from modernize.evaluation.equivalence import behavioral_check

    ir = load_ir("fn_saldo_cliente").model_copy(update={"name": "rotina_sem_cenarios"})
    assert behavioral_check("dsn", ir, "x", "y") is None
