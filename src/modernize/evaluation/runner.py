import json
from pathlib import Path

from modernize.evaluation.fidelity import contract_score
from modernize.graph.state import initial_state
from modernize.ir.models import RoutineIR
from modernize.observability.tracing import record_score

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
ORDER = [
    "fn_saldo_cliente.sql",
    "sp_atualizar_status_contas_inativas.sql",
    "sp_transferir_entre_contas.sql",
    "sp_processar_lote_taxas.sql",
    "sp_relatorio_mensal_cliente.sql",
]


def run_evaluation(compiled_graph, repo, fixtures_dir: Path | None = None, write_dir: Path | None = None) -> dict:
    base = fixtures_dir or FIXTURES
    schema = (base / "schema.sql").read_text(encoding="utf-8")
    routines = []
    for filename in ORDER:
        source = (base / filename).read_text(encoding="utf-8")
        state = compiled_graph.invoke(initial_state(source, schema))
        ir = RoutineIR.model_validate(state["ir"]) if state.get("ir") else None
        scored = contract_score(ir, state.get("generated_code"))
        history_id = state.get("history_id")
        routine_name = ir.name if ir else filename.removesuffix(".sql")
        if history_id is not None:
            repo.insert_score(
                history_id=history_id,
                routine_name=routine_name,
                metric="contract_fidelity",
                score=scored["score"],
                detail=scored["checks"],
            )
        record_score("contract_fidelity", scored["score"])
        if write_dir is not None:
            _write_result(write_dir, routine_name, state, scored)
        routines.append(
            {
                "name": routine_name,
                "history_id": history_id,
                "score": scored["score"],
                "checks": scored["checks"],
            }
        )
    aggregate = round(sum(item["score"] for item in routines) / len(routines), 4)
    return {"metric": "contract_fidelity", "aggregate": aggregate, "routines": routines}


def _write_result(write_dir: Path, routine_name: str, state: dict, scored: dict) -> None:
    folder = write_dir / routine_name
    folder.mkdir(parents=True, exist_ok=True)
    code = state.get("generated_code")
    if code:
        (folder / "module.py").write_text(code, encoding="utf-8")
    payload = {
        "status": state.get("status"),
        "history_id": state.get("history_id"),
        "score": scored,
        "report": state.get("report"),
    }
    (folder / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    from modernize.graph.builder import graph
    from modernize.persistence.history import PsycopgHistory

    payload = run_evaluation(graph, PsycopgHistory(), write_dir=ROOT / "results")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
