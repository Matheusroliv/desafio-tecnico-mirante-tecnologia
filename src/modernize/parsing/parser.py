from pglast import parse_plpgsql, parse_sql
from pglast.parser import ParseError

from modernize.ir.models import Parameter, RaiseStmt, RoutineIR, SqlStmt, Variable

TYPE_FAMILY = {
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
    "numeric": "numeric",
    "date": "date",
    "timestamp": "timestamp",
    "timestamptz": "timestamptz",
    "varchar": "varchar",
    "text": "text",
    "jsonb": "jsonb",
    "bool": "boolean",
}

MODE_NAME = {
    "FUNC_PARAM_DEFAULT": "in",
    "FUNC_PARAM_IN": "in",
    "FUNC_PARAM_OUT": "out",
    "FUNC_PARAM_INOUT": "inout",
    "FUNC_PARAM_VARIADIC": "in",
}


class ParseFailure(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def parse_routine(source: str) -> RoutineIR:
    text = source.strip()
    if not text:
        raise ParseFailure("codigo fonte vazio")
    try:
        parsed = parse_sql(text)
    except ParseError as exc:
        raise ParseFailure(str(exc)) from exc
    if len(parsed) != 1 or type(parsed[0].stmt).__name__ != "CreateFunctionStmt":
        raise ParseFailure("a entrada precisa ser uma unica FUNCTION ou PROCEDURE")
    stmt = parsed[0].stmt
    try:
        plpgsql = parse_plpgsql(text)
    except Exception as exc:
        raise ParseFailure(str(exc)) from exc
    if not plpgsql:
        raise ParseFailure("parse_plpgsql nao devolveu corpo")
    return _build(stmt, plpgsql[0]["PLpgSQL_function"])


def _build(stmt, function: dict) -> RoutineIR:
    parameters = _parameters(stmt)
    param_names = {item.name for item in parameters}
    ctx = _Ctx()
    _walk(function.get("action"), ctx)
    for datum in function.get("datums") or []:
        var = datum.get("PLpgSQL_var") or {}
        expr = var.get("cursor_explicit_expr")
        if expr:
            ctx.has_cursor = True
            ctx.statements.append(SqlStmt(sql=_query(expr), cursor=True))
    variables = []
    for datum in function.get("datums") or []:
        var = datum.get("PLpgSQL_var") or {}
        name = var.get("refname")
        if not name or name == "found" or name in param_names or var.get("cursor_explicit_expr"):
            continue
        variables.append(Variable(name=name, type_name="unknown"))
    return_type = _type_family(getattr(stmt, "returnType", None))
    setof = bool(getattr(getattr(stmt, "returnType", None), "setof", False))
    return RoutineIR(
        name=_routine_name(stmt),
        kind="procedure" if stmt.is_procedure else "function",
        parameters=parameters,
        returns=None if stmt.is_procedure else return_type,
        set_returning=setof,
        language=_language(stmt),
        variables=variables,
        statements=ctx.statements,
        conditions=ctx.conditions,
        raises=ctx.raises,
        assigns=ctx.assigns,
        return_queries=ctx.return_queries,
        has_get_diagnostics=ctx.has_get_diagnostics,
        has_loop=ctx.has_loop,
        has_cursor=ctx.has_cursor,
        has_exception=ctx.has_exception,
        exception_reraises=ctx.exception_reraises,
        exception_has_insert=ctx.exception_has_insert,
    )


def _parameters(stmt) -> list[Parameter]:
    found = []
    for param in stmt.parameters or ():
        mode_name = getattr(param.mode, "name", str(param.mode))
        mode = MODE_NAME.get(mode_name)
        if mode is None:
            continue
        found.append(
            Parameter(name=param.name, mode=mode, type_name=_type_family(param.argType))
        )
    return found


def _type_family(type_name) -> str:
    if type_name is None:
        return "unknown"
    names = getattr(type_name, "names", None) or ()
    if not names:
        return "unknown"
    raw = getattr(names[-1], "sval", str(names[-1])).lower()
    return TYPE_FAMILY.get(raw, raw)


def _routine_name(stmt) -> str:
    parts = stmt.funcname or ()
    return getattr(parts[-1], "sval", "rotina")


def _language(stmt) -> str:
    for opt in stmt.options or ():
        if getattr(opt, "defname", None) != "language":
            continue
        arg = opt.arg
        if isinstance(arg, tuple):
            arg = arg[0] if arg else None
        sval = getattr(arg, "sval", None)
        if sval:
            return sval
    return "plpgsql"


def _query(node) -> str:
    if not isinstance(node, dict):
        return ""
    expr = node.get("PLpgSQL_expr")
    if isinstance(expr, dict):
        return expr.get("query") or ""
    return ""


class _Ctx:
    def __init__(self) -> None:
        self.in_exception = False
        self.in_loop = False
        self.has_exception = False
        self.exception_reraises = False
        self.exception_has_insert = False
        self.has_loop = False
        self.has_cursor = False
        self.has_get_diagnostics = False
        self.statements: list[SqlStmt] = []
        self.conditions: list[str] = []
        self.raises: list[RaiseStmt] = []
        self.assigns: list[str] = []
        self.return_queries: list[str] = []


def _walk(node, ctx: _Ctx) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, ctx)
        return
    if not isinstance(node, dict):
        return
    if "PLpgSQL_stmt_block" in node:
        block = node["PLpgSQL_stmt_block"]
        _walk(block.get("body") or [], ctx)
        if block.get("exceptions"):
            _walk(block["exceptions"], ctx)
        return
    if "PLpgSQL_exception_block" in node:
        ctx.has_exception = True
        previous = ctx.in_exception
        ctx.in_exception = True
        try:
            for exc in node["PLpgSQL_exception_block"].get("exc_list") or []:
                action = (exc.get("PLpgSQL_exception") or {}).get("action") or []
                _walk(action, ctx)
        finally:
            ctx.in_exception = previous
        return
    if "PLpgSQL_stmt_if" in node:
        info = node["PLpgSQL_stmt_if"]
        cond = _query(info.get("cond"))
        if cond:
            ctx.conditions.append(cond)
        _walk(info.get("then_body") or [], ctx)
        _walk(info.get("else_body") or [], ctx)
        return
    if "PLpgSQL_stmt_loop" in node:
        ctx.has_loop = True
        previous = ctx.in_loop
        ctx.in_loop = True
        try:
            _walk(node["PLpgSQL_stmt_loop"].get("body") or [], ctx)
        finally:
            ctx.in_loop = previous
        return
    if "PLpgSQL_stmt_case" in node:
        info = node["PLpgSQL_stmt_case"]
        for when in info.get("case_when_list") or []:
            _walk((when.get("PLpgSQL_case_when") or {}).get("stmts") or [], ctx)
        _walk(info.get("else_stmts") or [], ctx)
        return
    if "PLpgSQL_stmt_execsql" in node:
        info = node["PLpgSQL_stmt_execsql"]
        sql = _query(info.get("sqlstmt"))
        targets = _into_targets(info.get("target"))
        ctx.statements.append(
            SqlStmt(
                sql=sql,
                into=bool(info.get("into")),
                into_targets=targets,
                in_loop=ctx.in_loop,
                in_exception=ctx.in_exception,
            )
        )
        if ctx.in_exception and sql.lstrip().lower().startswith("insert"):
            ctx.exception_has_insert = True
        return
    if "PLpgSQL_stmt_raise" in node:
        info = node["PLpgSQL_stmt_raise"]
        level = int(info.get("elog_level") or 0)
        ctx.raises.append(
            RaiseStmt(
                level=level,
                message=info.get("message"),
                in_exception=ctx.in_exception,
            )
        )
        if ctx.in_exception and level >= 21:
            ctx.exception_reraises = True
        return
    if "PLpgSQL_stmt_assign" in node:
        expr = _query(node["PLpgSQL_stmt_assign"].get("expr"))
        if expr:
            ctx.assigns.append(expr)
        return
    if "PLpgSQL_stmt_return_query" in node:
        sql = _query(node["PLpgSQL_stmt_return_query"].get("query"))
        if sql:
            ctx.return_queries.append(sql)
        return
    if "PLpgSQL_stmt_getdiag" in node:
        ctx.has_get_diagnostics = True
        return
    if "PLpgSQL_stmt_open" in node:
        ctx.has_cursor = True


def _into_targets(target) -> list[str]:
    if not isinstance(target, dict):
        return []
    row = target.get("PLpgSQL_row") or {}
    names = []
    for field in row.get("fields") or []:
        name = field.get("name")
        if name:
            names.append(name)
    return names
