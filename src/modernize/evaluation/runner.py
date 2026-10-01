"""Avaliacao da pipeline sobre os anexos B-F: Fidelidade de Contrato e Equivalencia Comportamental.

``python -m modernize.evaluation.runner`` roda a avaliacao completa e grava
``results/<rotina>/module.py`` e ``results/<rotina>/report.json``.
"""

import json
from pathlib import Path
from typing import Any

from modernize.evaluation.equivalence import evaluate_in_subprocess, legacy_dsn
from modernize.evaluation.fidelity import contract_score
from modernize.evaluation.scenarios import SCENARIOS
from modernize.ir.models import RoutineIR
from modernize.observability.tracing import record_score
from modernize.persistence.history import HistoryRepository
from modernize.pipeline import execute

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
ORDER = [
    "fn_saldo_cliente.sql",
    "sp_atualizar_status_contas_inativas.sql",
    "sp_transferir_entre_contas.sql",
    "sp_processar_lote_taxas.sql",
    "sp_relatorio_mensal_cliente.sql",
]
CONTRACT = "contract_fidelity"
BEHAVIOR = "behavioral_equivalence"


def run_evaluation(
    compiled_graph: Any,
    repo: HistoryRepository,
    fixtures_dir: Path | None = None,
    write_dir: Path | None = None,
    equivalence_dsn: str | None = None,
) -> dict:
    base = fixtures_dir or FIXTURES
    schema = (base / "schema.sql").read_text(encoding="utf-8")
    dsn = equivalence_dsn if equivalence_dsn is not None else legacy_dsn()
    runs: list[dict] = []
    for filename in ORDER:
        source = (base / filename).read_text(encoding="utf-8")
        state = execute(compiled_graph, source, schema, origin="evaluate")
        ir = RoutineIR.model_validate(state["ir"]) if state.get("ir") else None
        runs.append(
            {
                "name": ir.name if ir else filename.removesuffix(".sql"),
                "source": source,
                "ir": ir,
                "state": state,
                "contract": contract_score(ir, state.get("generated_code")),
            }
        )
    generated = {run["name"]: run["state"].get("generated_code") for run in runs if run["state"].get("generated_code")}
    sources = {run["name"]: run["source"] for run in runs}
    for run in runs:
        run["behavior"] = _behavior(dsn, run, generated, sources) if dsn else None
        _record(repo, run)
        if write_dir is not None:
            _write_result(write_dir, run)
    routines = [
        {
            "name": run["name"],
            "status": run["state"].get("status"),
            "history_id": run["state"].get("history_id"),
            "trace_id": _trace_id(run["state"]),
            "score": run["contract"]["score"],
            "checks": run["contract"]["checks"],
            BEHAVIOR: _behavior_view(run["behavior"]),
        }
        for run in runs
    ]
    behaviors = [run["behavior"]["score"] for run in runs if run["behavior"] is not None]
    return {
        "metric": CONTRACT,
        "aggregate": round(sum(item["score"] for item in routines) / len(routines), 4),
        "behavioral_aggregate": round(sum(behaviors) / len(behaviors), 4) if dsn and behaviors else None,
        "routines": routines,
    }


def _behavior(dsn: str, run: dict, generated: dict[str, str], sources: dict[str, str]) -> dict:
    ir: RoutineIR | None = run["ir"]
    scenarios = SCENARIOS.get(run["name"], [])
    code = run["state"].get("generated_code")
    if ir is None or not code or not scenarios:
        reason = "sem codigo gerado" if not code else "sem cenarios para a rotina"
        return {"score": 0.0, "passed": 0, "total": len(scenarios), "scenarios": [], "reason": reason}
    modules = {name: generated[name] for name in [*ir.dependencies, ir.name] if name in generated}
    legacy_sources = {name: sources[name] for name in [*ir.dependencies, ir.name] if name in sources}
    return evaluate_in_subprocess(dsn, ir, legacy_sources, modules, scenarios)


def _behavior_view(behavior: dict | None) -> dict | None:
    if behavior is None:
        return None
    return {key: behavior[key] for key in ("score", "passed", "total")} | {
        "failures": [
            {"scenario": item["name"], "reason": item["reason"]}
            for item in behavior.get("scenarios", [])
            if not item["equivalent"]
        ]
    }


def _trace_id(state: dict) -> str | None:
    return ((state.get("report") or {}).get("meta") or {}).get("trace_id")


def _record(repo: HistoryRepository, run: dict) -> None:
    history_id = run["state"].get("history_id")
    trace_id = _trace_id(run["state"])
    metrics = [(CONTRACT, run["contract"]["score"], run["contract"]["checks"])]
    if run["behavior"] is not None:
        metrics.append((BEHAVIOR, run["behavior"]["score"], run["behavior"]))
    for metric, score, detail in metrics:
        if history_id is not None:
            repo.insert_score(
                history_id=history_id, routine_name=run["name"], metric=metric, score=score, detail=detail
            )
        record_score(metric, score, trace_id, comment=run["name"])


def _write_result(write_dir: Path, run: dict) -> None:
    folder = write_dir / run["name"]
    folder.mkdir(parents=True, exist_ok=True)
    state = run["state"]
    code = state.get("generated_code")
    module = folder / "module.py"
    if code:
        module.write_text(code.rstrip() + "\n", encoding="utf-8")
    elif module.exists():
        module.unlink()
    payload = {
        "status": state.get("status"),
        "history_id": state.get("history_id"),
        "model": (state.get("report") or {}).get("generation", {}).get("model"),
        "attempts": state.get("attempts"),
        "metrics": {CONTRACT: run["contract"], BEHAVIOR: run["behavior"]},
        "report": state.get("report"),
    }
    (folder / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def main() -> None:
    from modernize.graph.builder import graph
    from modernize.observability.tracing import flush
    from modernize.persistence.history import PsycopgHistory

    try:
        payload = run_evaluation(graph, PsycopgHistory(), write_dir=ROOT / "results")
    finally:
        flush()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
