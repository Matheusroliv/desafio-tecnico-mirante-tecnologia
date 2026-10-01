"""Checagens de politica de traducao sobre o AST do modulo gerado.

Cada regra e deterministica e aponta um desvio objetivo da politica do PRD
(secao 6.5). Violacao nao bloqueia: deixa a execucao em ``parcial`` e vira
feedback para o laco de reparo.
"""

import ast
import re
from collections.abc import Iterator

from modernize.ir.models import RoutineIR

EXECUTE_METHODS = {"execute", "executemany"}
TRANSACTION_METHODS = {"commit", "rollback"}


def policy_problems(tree: ast.Module, ir: RoutineIR) -> list[str]:
    risk_ids = {risk.id for risk in ir.risks}
    issues: list[str] = []
    issues.extend(_transaction_control(tree))
    issues.extend(_connection_open(tree))
    issues.extend(_floats(tree))
    issues.extend(_prints(tree))
    issues.extend(_sql_string_building(tree))
    issues.extend(_untyped_jsonb_params(tree))
    if "cursor_n_plus_1" in risk_ids:
        issues.extend(_query_in_loop(tree))
    return issues


def _calls(tree: ast.AST) -> Iterator[ast.Call]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _method_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def _transaction_control(tree: ast.AST) -> list[str]:
    found = sorted(
        {
            name
            for call in _calls(tree)
            if isinstance(call.func, ast.Attribute) and (name := call.func.attr) in TRANSACTION_METHODS
        }
    )
    return [f"no_transaction_control: chamada .{name}() — o chamador e dono da transacao" for name in found]


def _connection_open(tree: ast.AST) -> list[str]:
    for call in _calls(tree):
        if _method_name(call) == "connect":
            return ["no_connection_open: a funcao gerada nao abre conexao; use o conn recebido"]
    return []


def _floats(tree: ast.AST) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            return [f"no_float: literal float {node.value!r}; use Decimal('...') com string"]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
            return ["no_float: chamada float(); NUMERIC vira Decimal"]
    return []


def _prints(tree: ast.AST) -> list[str]:
    for call in _calls(tree):
        if isinstance(call.func, ast.Name) and call.func.id == "print":
            return ["no_print: RAISE NOTICE/WARNING vira logging, nao print"]
    return []


def _is_built_string(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(value, ast.FormattedValue) for value in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod | ast.Add):
        return not (isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant))
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"


def _sql_string_building(tree: ast.AST) -> list[str]:
    for call in _calls(tree):
        if _method_name(call) not in EXECUTE_METHODS or not call.args:
            continue
        if _is_built_string(call.args[0]):
            return ["no_sql_string_building: SQL montado por string; use placeholder %s e parametros"]
    return []


def _jsonb_arguments(sql: str) -> Iterator[str]:
    """Texto entre os parenteses de cada ``jsonb_build_object(...)`` (parenteses balanceados)."""
    lowered = sql.lower()
    start = lowered.find("jsonb_build_object(")
    while start != -1:
        index = start + len("jsonb_build_object(")
        depth = 1
        begin = index
        while index < len(sql) and depth:
            depth += {"(": 1, ")": -1}.get(sql[index], 0)
            index += 1
        yield sql[begin : index - 1]
        start = lowered.find("jsonb_build_object(", index)


def _untyped_jsonb_params(tree: ast.AST) -> list[str]:
    """psycopg 3 envia texto com tipo desconhecido; ``jsonb_build_object`` recebe ``"any"`` e falha
    com "could not determine data type of parameter". Todo placeholder ali precisa de cast explicito."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        for arguments in _jsonb_arguments(node.value):
            if re.search(r"%(?:s|\(\w+\)s)(?!\s*::)", arguments):
                return [
                    "no_untyped_jsonb_param: placeholder sem cast dentro de jsonb_build_object; "
                    "use %s::bigint, %s::numeric, %s::date ou %s::text"
                ]
    return []


def _string_constants(tree: ast.AST) -> dict[str, str]:
    """Nome -> texto SQL para atribuicoes simples ``sql = \"\"\"...\"\"\"``."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value.value
    return found


def _sql_text(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _is_read(sql: str) -> bool:
    head = sql.lstrip().lower()
    return head.startswith(("select", "with"))


def _query_in_loop(tree: ast.AST) -> list[str]:
    constants = _string_constants(tree)
    for loop in ast.walk(tree):
        if not isinstance(loop, ast.For | ast.While | ast.AsyncFor):
            continue
        for stmt in loop.body + loop.orelse:
            for call in _calls(stmt):
                if _method_name(call) not in EXECUTE_METHODS or not call.args:
                    continue
                sql = _sql_text(call.args[0], constants)
                if sql is not None and _is_read(sql):
                    return [
                        "no_query_in_loop: SELECT dentro do laco do cursor (N+1); "
                        "materialize as linhas motoras e as taxas vigentes antes do laco e case em memoria"
                    ]
    return []
