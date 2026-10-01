import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

from modernize.ir.models import RoutineIR
from modernize.validation.policy import policy_problems


def check_module(ir: RoutineIR, code: str) -> dict:
    issues: list[str] = []
    tree = _parse(code, issues)
    ast_ok = tree is not None
    symbol_issues = symbol_problems(tree, ir) if tree is not None else ["simbolo nao verificado"]
    if tree is not None:
        issues.extend(symbol_issues)
    symbol_ok = tree is not None and not symbol_issues
    if tree is not None:
        ruff_clean, ruff_issues = ruff_problems(code)
        issues.extend(ruff_issues)
        policy_issues = policy_problems(tree, ir)
    else:
        ruff_clean = False
        policy_issues = []
    issues.extend(policy_issues)
    missing = decision_ids_missing(code, [risk.id for risk in ir.risks])
    if missing:
        issues.append("DECISION ausente: " + ", ".join(missing))
    if not code.strip() or not ast_ok:
        status = "falha"
    elif (not ruff_clean) or (not symbol_ok) or missing or policy_issues:
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
            "policy_ok": ast_ok and not policy_issues,
            "policy_issues": policy_issues,
            "issues": issues,
        },
    }


def decision_ids_missing(code: str, risk_ids: list[str]) -> list[str]:
    return [risk_id for risk_id in risk_ids if f"DECISION: {risk_id}" not in code]


def symbol_problems(tree: ast.Module, ir: RoutineIR) -> list[str]:
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == ir.name]
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
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    proc = subprocess.run(
        [binary, "check", "--select", "E9,F", "--output-format", "concise", "--no-cache", "--isolated"]
        + ["--stdin-filename", "module.py", "-"],
        input=code,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )
    if proc.returncode == 0:
        return True, []
    lines = []
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("Found ") or line.startswith("[*]"):
            continue
        # "module.py:15:21: F821 Undefined name" -> "ruff linha 15: F821 Undefined name"
        location, _, message = line.partition(": ")
        parts = location.rsplit(":", 2)
        lines.append(f"ruff linha {parts[-2]}: {message}" if len(parts) == 3 and message else line)
    return False, lines[:20] or ["ruff encontrou problemas"]


def _parse(code: str, issues: list[str]) -> ast.Module | None:
    try:
        return ast.parse(code)
    except SyntaxError as exc:
        issues.append(f"ast.parse linha {exc.lineno}: {exc.msg}")
        return None


def _out_params(tree: ast.Module, names: list[str]) -> bool:
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
