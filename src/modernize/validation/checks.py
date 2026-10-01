import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from modernize.ir.models import RoutineIR


def check_module(ir: RoutineIR, code: str) -> dict:
    issues: list[str] = []
    tree = _parse(code, issues)
    ast_ok = tree is not None
    symbol_issues = symbol_problems(tree, ir) if tree is not None else ["simbolo nao verificado"]
    if tree is not None:
        issues.extend(symbol_issues)
    symbol_ok = tree is not None and not symbol_issues
    if ast_ok:
        ruff_clean, ruff_issues = ruff_problems(code)
        issues.extend(ruff_issues)
    else:
        ruff_clean = False
    missing = decision_ids_missing(code, [risk.id for risk in ir.risks])
    if missing:
        issues.append("DECISION ausente: " + ", ".join(missing))
    if not code.strip() or not ast_ok:
        status = "falha"
    elif (not ruff_clean) or (not symbol_ok) or missing:
        status = "parcial"
    else:
        status = "sucesso"
    return {
        "status": status,
        "validation": {
            "ok": status == "sucesso",
            "ast_parse_ok": ast_ok,
            "ruff_ok": ruff_clean,
            "symbol_ok": symbol_ok,
            "issues": issues,
        },
    }


def decision_ids_missing(code: str, risk_ids: list[str]) -> list[str]:
    return [risk_id for risk_id in risk_ids if f"DECISION: {risk_id}" not in code]


def symbol_problems(tree: ast.AST, ir: RoutineIR) -> list[str]:
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == ir.name
    ]
    if not functions:
        return [f"funcao {ir.name} ausente"]
    func = functions[0]
    names = [arg.arg for arg in func.args.args]
    issues = []
    if not names or names[0] != "conn":
        issues.append("primeiro parametro deve ser conn")
    for param in ir.parameters:
        if param.mode == "out":
            continue
        if param.name not in names:
            issues.append(f"parametro {param.name} ausente")
    out_names = [param.name for param in ir.parameters if param.mode == "out"]
    if out_names:
        if not _out_params(tree, out_names):
            issues.append("OutParams sem os campos de saida")
        if not any(isinstance(node, ast.Return) for node in ast.walk(func)):
            issues.append("procedure com OUT sem return")
    return issues


def ruff_problems(code: str) -> tuple[bool, list[str]]:
    binary = _ruff_bin()
    if binary is None:
        return False, ["ruff indisponivel"]
    handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    path = handle.name
    try:
        handle.write(code)
        handle.close()
        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        proc = subprocess.run(
            [binary, "check", "--select", "E9,F", "--color", "never", path],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    finally:
        os.remove(path)
    if proc.returncode == 0:
        return True, []
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return False, lines[:20] or ["ruff encontrou problemas"]


def _parse(code: str, issues: list[str]) -> ast.AST | None:
    try:
        return ast.parse(code)
    except SyntaxError as exc:
        issues.append(f"ast.parse: {exc.msg}")
        return None


def _out_params(tree: ast.AST, names: list[str]) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "OutParams":
            continue
        fields = set()
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fields.add(stmt.target.id)
        return set(names) <= fields
    return False


def _ruff_bin() -> str | None:
    found = shutil.which("ruff")
    if found:
        return found
    folder = Path(sys.executable).resolve().parent
    for name in ("ruff.exe", "ruff"):
        candidate = folder / name
        if candidate.exists():
            return str(candidate)
    return None
