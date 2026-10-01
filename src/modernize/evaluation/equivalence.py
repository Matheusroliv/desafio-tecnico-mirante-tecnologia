"""Metrica de Equivalencia Comportamental.

Mesma entrada na rotina PL/pgSQL original e na funcao Python gerada, cada uma
num schema temporario recem-criado (schema do anexo A + massa de teste), dentro
de uma transacao desfeita no fim. Compara retorno (ou erro) e o retrato das
tabelas depois da chamada.

O codigo gerado pelo LLM so roda no subprocesso ``equivalence_worker``, com
timeout. ``run_scenarios`` e importavel para os testes rodarem traducoes de
referencia (codigo confiavel) sem subprocesso.
"""

import dataclasses
import datetime as dt
import json
import os
import subprocess
import sys
import types
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from modernize.ir.models import RoutineIR

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
TABLES = ("clientes", "contas", "transacoes", "taxas", "log_auditoria")
NOW_MARK = "<now>"
SQL_CAST = {
    "smallint": "smallint",
    "integer": "integer",
    "bigint": "bigint",
    "numeric": "numeric",
    "date": "date",
    "timestamp": "timestamp",
    "varchar": "varchar",
    "text": "text",
    "boolean": "boolean",
}
WORKER_TIMEOUT_SECONDS = 120
WORKER_ENV = ("PATH", "PYTHONPATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL", "VIRTUAL_ENV")


def legacy_dsn() -> str | None:
    value = os.environ.get("LEGACY_DATABASE_URL", "").strip()
    return value or None


# ---------------------------------------------------------------- normalizacao


def canonical(value: Any) -> Any:
    """Forma comparavel e serializavel: numero -> texto decimal normalizado, data -> ISO, dataclass -> lista."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int | float | Decimal):
        number = Decimal(str(value)).normalize()
        return format(number, "f") if number != 0 else "0"
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return [canonical(getattr(value, field.name)) for field in dataclasses.fields(value)]
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [canonical(item) for item in value]
    return repr(value)


def _message(exc: BaseException) -> str:
    first = (str(exc).strip().splitlines() or [""])[0]
    return " ".join(first.replace("<NULL>", "None").split())


def _typed_args(ir: RoutineIR, args: list[Any]) -> list[Any]:
    params = [item for item in ir.parameters if item.mode != "out"]
    typed: list[Any] = []
    for param, raw in zip(params, args, strict=True):
        if raw is None:
            typed.append(None)
        elif param.type_name == "numeric":
            typed.append(Decimal(str(raw)))
        elif param.type_name == "date":
            typed.append(dt.date.fromisoformat(raw))
        else:
            typed.append(raw)
    return typed


# ------------------------------------------------------------------- execucao


def _legacy_call(ir: RoutineIR) -> str:
    ins = [item for item in ir.parameters if item.mode != "out"]
    placeholders = [f"%s::{SQL_CAST.get(item.type_name, item.type_name)}" for item in ins]
    if ir.kind == "procedure":
        placeholders += ["NULL" for item in ir.parameters if item.mode == "out"]
        return f"CALL {ir.name}({', '.join(placeholders)})"
    if ir.set_returning:
        return f"SELECT * FROM {ir.name}({', '.join(placeholders)})"
    return f"SELECT {ir.name}({', '.join(placeholders)})"


def _legacy_result(ir: RoutineIR, cur: Any) -> Any:
    if cur.description is None:
        return None
    rows = cur.fetchall()
    if ir.set_returning:
        return [list(row) for row in rows]
    if ir.kind == "procedure":
        return list(rows[0]) if rows else None
    return rows[0][0] if rows else None


def _python_result(value: Any) -> Any:
    if isinstance(value, list):
        return [_python_result(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return [getattr(value, field.name) for field in dataclasses.fields(value)]
    if isinstance(value, tuple):
        return list(value)
    return value


def load_modules(modules: dict[str, str], order: list[str]) -> dict[str, types.ModuleType]:
    """Carrega o codigo gerado como ``modernized.<rotina>`` (convencao de import das dependencias)."""
    package = sys.modules.get("modernized")
    if package is None:
        package = types.ModuleType("modernized")
        package.__path__ = []
        sys.modules["modernized"] = package
    loaded: dict[str, types.ModuleType] = {}
    for name in order:
        module = types.ModuleType(f"modernized.{name}")
        sys.modules[module.__name__] = module
        setattr(package, name, module)
        exec(compile(modules[name], f"<modernized.{name}>", "exec"), module.__dict__)  # noqa: S102
        loaded[name] = module
    return loaded


def _snapshot(conn: Any) -> dict[str, dict[str, Any]]:
    now_text = conn.execute("SELECT to_jsonb(now()::timestamp) #>> '{}'").fetchone()[0]
    snapshot = {}
    for table in TABLES:
        rows = conn.execute(f"SELECT id, to_jsonb(t) FROM {table} t ORDER BY id").fetchall()  # noqa: S608
        snapshot[table] = {str(row[0]): _mark_now(canonical(row[1]), now_text) for row in rows}
    return snapshot


def _effect(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Diferenca por tabela entre o retrato antes e depois da chamada (linhas inseridas, removidas, alteradas).

    Comparar o efeito, e nao o retrato inteiro, neutraliza a massa com datas relativas a NOW().
    """
    effect: dict[str, Any] = {}
    for table in TABLES:
        old, new = before[table], after[table]
        changes = {
            "added": [new[key] for key in new if key not in old],
            "removed": sorted(key for key in old if key not in new),
            "changed": [new[key] for key in new if key in old and new[key] != old[key]],
        }
        if any(changes.values()):
            effect[table] = changes
    return effect


def _mark_now(value: Any, now_text: str) -> Any:
    if isinstance(value, str):
        return NOW_MARK if value == now_text else value
    if isinstance(value, dict):
        return {key: _mark_now(item, now_text) for key, item in value.items()}
    if isinstance(value, list):
        return [_mark_now(item, now_text) for item in value]
    return value


def _prepare(conn: Any, legacy_sources: list[str]) -> None:
    from psycopg.types.json import set_json_loads

    set_json_loads(lambda text: json.loads(text, parse_float=Decimal), conn)
    schema = f"eq_{uuid.uuid4().hex[:12]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET LOCAL search_path TO {schema}")
    conn.execute("SET LOCAL statement_timeout = '15s'")
    conn.execute("SET LOCAL client_min_messages = 'error'")
    conn.execute((FIXTURES / "schema.sql").read_text(encoding="utf-8"))
    conn.execute((FIXTURES / "legacy_seed.sql").read_text(encoding="utf-8"))
    for source in legacy_sources:
        conn.execute(source)


def _run_side(dsn: str, legacy_sources: list[str], call: Any) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        try:
            _prepare(conn, legacy_sources)
            outcome: dict[str, Any] = {"error": None, "result": None}
            before = _snapshot(conn)
            try:
                with conn.transaction():
                    outcome["result"] = canonical(call(conn))
            except Exception as exc:
                outcome["error"] = _message(exc)
            outcome["effect"] = _effect(before, _snapshot(conn))
            return outcome
        finally:
            conn.rollback()


def _compare(legacy: dict, python: dict) -> tuple[bool, str]:
    if legacy["error"] is not None or python["error"] is not None:
        if legacy["error"] is None:
            return False, f"python levantou erro e o legado nao: {python['error']}"
        if python["error"] is None:
            return False, f"legado levantou erro e o python nao: {legacy['error']}"
        if legacy["error"] != python["error"]:
            return False, f"mensagens de erro diferentes: legado={legacy['error']!r} python={python['error']!r}"
        return True, "mesmo erro"
    if legacy["result"] != python["result"]:
        return False, f"retorno diferente: legado={legacy['result']!r} python={python['result']!r}"
    for table in TABLES:
        if legacy["effect"].get(table) != python["effect"].get(table):
            return False, f"efeito diferente na tabela {table}"
    return True, "mesmo retorno e mesmo efeito"


def run_scenarios(
    dsn: str,
    ir: RoutineIR,
    legacy_sources: dict[str, str],
    modules: dict[str, str],
    scenarios: list[dict],
) -> dict[str, Any]:
    """Roda os cenarios no processo atual. So para codigo confiavel ou dentro do worker."""
    # Dependencia ainda nao migrada vira um shim que chama a funcao SQL legada (padrao strangler):
    # a rotina pode ser validada sozinha, antes das dependencias.
    shims = [name for name in ir.dependencies if name not in modules and name in legacy_sources]
    modules = {**modules, **{name: _shim(name) for name in shims}}
    order = [*[name for name in ir.dependencies if name in modules], ir.name]
    try:
        function = getattr(load_modules(modules, order)[ir.name], ir.name)
    except Exception as exc:
        reason = f"modulo gerado nao carregou: {type(exc).__name__}: {exc}"
        results = [{"name": item["name"], "equivalent": False, "reason": reason} for item in scenarios]
        return _summary(results)
    sources = [legacy_sources[name] for name in ir.dependencies if name in legacy_sources] + [legacy_sources[ir.name]]
    sql = _legacy_call(ir)
    results = []
    for scenario in scenarios:
        args = _typed_args(ir, scenario["args"])
        legacy = _run_side(dsn, sources, lambda conn, args=args: _legacy_result(ir, conn.execute(sql, args)))
        python = _run_side(
            dsn, [legacy_sources[name] for name in shims], lambda conn, args=args: _python_result(function(conn, *args))
        )
        equivalent, reason = _compare(legacy, python)
        results.append(
            {
                "name": scenario["name"],
                "equivalent": equivalent,
                "reason": reason,
                "legacy": {"error": legacy["error"], "result": legacy["result"]},
                "python": {"error": python["error"], "result": python["result"]},
            }
        )
    return _summary(results)


def _shim(name: str) -> str:
    return (
        f"def {name}(conn, *args):\n"
        f"    placeholders = ', '.join(['%s'] * len(args))\n"
        f"    return conn.execute(f'SELECT {name}({{placeholders}})', args).fetchone()[0]\n"
    )


def _summary(results: list[dict]) -> dict[str, Any]:
    passed = sum(1 for item in results if item["equivalent"])
    total = len(results)
    return {
        "score": round(passed / total, 4) if total else 0.0,
        "passed": passed,
        "total": total,
        "scenarios": results,
    }


# --------------------------------------------------------------- subprocesso


def evaluate_in_subprocess(
    dsn: str,
    ir: RoutineIR,
    legacy_sources: dict[str, str],
    modules: dict[str, str],
    scenarios: list[dict],
    timeout: int = WORKER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    payload = {
        "dsn": dsn,
        "ir": ir.model_dump(),
        "legacy_sources": legacy_sources,
        "modules": modules,
        "scenarios": scenarios,
    }
    # Ambiente minimo: o codigo gerado nao herda chaves de LLM, Langfuse nem DATABASE_URL do servidor.
    env = {key: os.environ[key] for key in WORKER_ENV if key in os.environ}
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else src
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "modernize.evaluation.equivalence_worker"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _failed(scenarios, f"timeout de {timeout}s no worker")
    if proc.returncode != 0:
        tail = (proc.stderr.strip().splitlines() or ["sem stderr"])[-1]
        return _failed(scenarios, f"worker saiu com {proc.returncode}: {tail}")
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError, IndexError:
        return _failed(scenarios, "worker devolveu saida invalida")


def behavioral_check(dsn: str, ir: RoutineIR, source_code: str, code: str) -> dict[str, Any] | None:
    """Validacao dinamica de uma unica rotina (usada pelo no validate).

    Compara contra a fonte recebida. Dependencias legadas vem do catalogo ``fixtures/`` e entram como
    shim SQL. Devolve None quando nao ha cenarios cadastrados para a rotina.
    """
    from modernize.evaluation.scenarios import SCENARIOS

    scenarios = SCENARIOS.get(ir.name)
    if not scenarios:
        return None
    legacy_sources = {ir.name: source_code}
    for name in ir.dependencies:
        path = FIXTURES / f"{name}.sql"
        if path.exists():
            legacy_sources[name] = path.read_text(encoding="utf-8")
    return evaluate_in_subprocess(dsn, ir, legacy_sources, {ir.name: code}, scenarios)


def _failed(scenarios: list[dict], reason: str) -> dict[str, Any]:
    return _summary([{"name": item["name"], "equivalent": False, "reason": reason} for item in scenarios])
