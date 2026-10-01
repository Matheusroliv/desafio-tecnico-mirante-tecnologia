import re

from modernize.ir.models import Operation, Risk, RoutineIR

BUILTINS = {
    "coalesce",
    "now",
    "date_trunc",
    "greatest",
    "least",
    "jsonb_build_object",
    "date",
    "sum",
    "count",
    "min",
    "max",
    "avg",
    "nullif",
    "cast",
    "lower",
    "upper",
    "abs",
    "round",
    "exists",
    "not",
    "and",
    "or",
    "in",
    "case",
    "when",
    "extract",
    "overlay",
    "substring",
    "position",
    "trim",
    "btrim",
    "length",
    "replace",
    "to_char",
    "to_date",
    "to_timestamp",
    "make_interval",
    "date_part",
}

CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
RELATION = re.compile(r"(?i)(?:\binto|\bfrom|\bjoin|\bupdate|\btable)\s+$")
SQL_WORDS = {
    "where",
    "values",
    "select",
    "as",
    "from",
    "numeric",
    "int",
    "integer",
    "bigint",
    "varchar",
    "char",
    "interval",
    "with",
    "recursive",
    "exists",
    "not",
    "and",
    "or",
    "in",
    "on",
    "join",
    "set",
    "update",
    "insert",
    "delete",
    "into",
    "table",
    "case",
    "when",
    "then",
    "else",
    "end",
    "by",
    "group",
    "order",
    "limit",
    "returning",
    "left",
    "right",
    "inner",
    "outer",
    "union",
    "all",
    "distinct",
    "having",
    "over",
    "filter",
    "lateral",
}
DATE_CALL = re.compile(r"(?<![\w])date\s*\(", re.IGNORECASE)
CMP = re.compile(r"<>|(?<![<>!:])=(?!=)")
BULK_WHERE = re.compile(r"(?is)\bwhere\s+[\w.]+\s*=\s*[\w.]+\s*$")
WORD = re.compile(r"\b[\w.]+\b")


def analyze(ir: RoutineIR) -> RoutineIR:
    data = ir.model_copy(deep=True)
    texts = _texts(data)
    blob = "\n".join(texts).lower()
    data.dependencies = _dependencies(data, texts)
    data.operations = _operations(data)
    data.constructs = _constructs(data, blob)
    data.risks = _risks(data, blob)
    return data


def _texts(ir: RoutineIR) -> list[str]:
    found = [stmt.sql for stmt in ir.statements]
    found.extend(ir.conditions)
    found.extend(ir.assigns)
    found.extend(ir.return_queries)
    return found


def _dependencies(ir: RoutineIR, texts: list[str]) -> list[str]:
    found: list[str] = []
    for text in texts:
        for match in CALL.finditer(text):
            key = match.group(1).lower()
            if key in BUILTINS or key in SQL_WORDS or key == ir.name.lower() or key in found:
                continue
            if RELATION.search(text[: match.start()]):
                continue
            found.append(key)
    return found


def _operations(ir: RoutineIR) -> list[Operation]:
    counts: dict[str, int] = {}
    for stmt in ir.statements:
        kind = _sql_kind(stmt.sql)
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    for sql in ir.return_queries:
        kind = _sql_kind(sql)
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    if ir.kind == "function" and (ir.return_queries or _function_returns(ir)):
        counts["return"] = counts.get("return", 0) + 1
    return [Operation(kind=kind, count=count) for kind, count in counts.items()]  # type: ignore[arg-type]


def _function_returns(ir: RoutineIR) -> bool:
    return ir.kind == "function" and not ir.set_returning


def _sql_kind(sql: str) -> str | None:
    head = sql.lstrip().lower()
    for kind in ("select", "insert", "update", "delete"):
        if head.startswith(kind):
            return kind
    if head.startswith("with"):
        return "select"
    return None


def _constructs(ir: RoutineIR, blob: str) -> list[str]:
    found: list[str] = []

    def add(name: str, present: bool) -> None:
        if present and name not in found:
            found.append(name)

    add("parameter_in", any(item.mode == "in" for item in ir.parameters))
    add("parameter_out", any(item.mode == "out" for item in ir.parameters))
    add("variable", bool(ir.variables))
    add("cursor", ir.has_cursor)
    add("raise", bool(ir.raises))
    add("for_update", "for update" in blob)
    add("jsonb", "jsonb" in blob)
    add("get_diagnostics", ir.has_get_diagnostics)
    add("exception_handler", ir.has_exception)
    add("cte_recursive", "with recursive" in blob)
    add("routine_call", bool(ir.dependencies))
    add("return_query", bool(ir.return_queries))
    add("loop", ir.has_loop)
    add("select_into", any(stmt.into for stmt in ir.statements))
    add("bulk_update", _has_bulk_update(ir))
    return found


def _risks(ir: RoutineIR, blob: str) -> list[Risk]:
    found: list[Risk] = []

    def add(risk_id: str, present: bool, detail: str) -> None:
        if present:
            found.append(Risk(id=risk_id, detail=detail))

    add(
        "cursor_n_plus_1",
        ir.has_cursor and any(stmt.in_loop for stmt in ir.statements),
        "cursor com SQL dentro do loop",
    )
    add(
        "raise_exception",
        any(item.level >= 21 and item.message for item in ir.raises),
        "RAISE EXCEPTION",
    )
    add("for_update", "for update" in blob, "FOR UPDATE")
    add("jsonb", "jsonb" in blob, "JSONB")
    add("recursion", "with recursive" in blob, "CTE recursiva")
    add("get_diagnostics", ir.has_get_diagnostics, "GET DIAGNOSTICS")
    add(
        "out_parameter",
        any(item.mode == "out" for item in ir.parameters),
        "parametro OUT",
    )
    add(
        "nested_routine_call",
        bool(ir.dependencies),
        "chamada a rotina de usuario",
    )
    add("exception_handler", ir.has_exception, "bloco EXCEPTION")
    add("set_returning", ir.set_returning, "RETURNS TABLE")
    add("bulk_update", _has_bulk_update(ir), "UPDATE de conjunto")
    add("three_valued_logic", _three_valued(ir), "comparacao com variavel que pode ser NULL")
    add(
        "audit_lost_on_rollback",
        ir.has_exception and ir.exception_has_insert and ir.exception_reraises,
        "INSERT de erro seguido de RAISE na mesma transacao",
    )
    add("date_of_timestamp", bool(DATE_CALL.search(blob)), "DATE() sobre timestamp")
    add(
        "swallowed_exception",
        ir.has_exception and not ir.exception_reraises,
        "WHEN OTHERS sem propagar",
    )
    return found


def _has_bulk_update(ir: RoutineIR) -> bool:
    for stmt in ir.statements:
        if _sql_kind(stmt.sql) != "update":
            continue
        if not BULK_WHERE.search(stmt.sql.strip()):
            return True
    return False


def _three_valued(ir: RoutineIR) -> bool:
    targets = {name for stmt in ir.statements for name in stmt.into_targets}
    if not targets:
        return False
    for cond in ir.conditions:
        lowered = cond.lower()
        if "is null" in lowered or "is not null" in lowered:
            continue
        if not CMP.search(cond):
            continue
        words = set(WORD.findall(cond))
        if targets & words:
            return True
    return False
