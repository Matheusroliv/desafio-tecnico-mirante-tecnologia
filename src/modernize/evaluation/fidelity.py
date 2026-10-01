import ast

from modernize.ir.models import RoutineIR
from modernize.validation.checks import decision_ids_missing, symbol_problems

WEIGHTS = {
    "ast_parse": 0.35,
    "symbol_and_params": 0.25,
    "decision_coverage": 0.20,
    "operation_coverage": 0.20,
}


def contract_score(ir: RoutineIR | None, code: str | None) -> dict:
    checks = {name: 0 for name in WEIGHTS}
    if ir is None or not code or not code.strip():
        return {"score": 0.0, "checks": checks}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    checks["ast_parse"] = 1 if tree is not None else 0
    checks["symbol_and_params"] = 1 if tree is not None and not symbol_problems(tree, ir) else 0
    checks["decision_coverage"] = 0 if decision_ids_missing(code, [risk.id for risk in ir.risks]) else 1
    checks["operation_coverage"] = 1 if _operations_covered(ir, code, tree) else 0
    score = round(sum(checks[name] * WEIGHTS[name] for name in WEIGHTS), 4)
    return {"score": score, "checks": checks}


def _operations_covered(ir: RoutineIR, code: str, tree: ast.AST | None) -> bool:
    upper = code.upper()
    for operation in ir.operations:
        if operation.kind == "return":
            if tree is None or not any(isinstance(node, ast.Return) for node in ast.walk(tree)):
                return False
            continue
        if operation.kind.upper() not in upper:
            return False
    return True
