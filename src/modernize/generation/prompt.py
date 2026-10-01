from pydantic import BaseModel

from modernize.ir.models import RoutineIR

POLICY = """
POLITICA DE TRADUCAO

Alvo: Python 3.14, compativel com 3.13. NUMERIC vira Decimal. Sem float para dinheiro.
A funcao recebe conn como primeiro argumento e nao abre conexao nem da commit.
SQL de conjunto, agregacao, UPDATE em massa e CTE recursiva permanecem SQL no psycopg, com placeholder %s.
Controle, validacao e RAISE viram Python. O raise fica no mesmo try do bloco EXCEPTION original.
WHEN OTHERS sem RAISE posterior devolve o fallback e nao propaga.
WHEN OTHERS com RAISE aceita audit_conn=None no fim. Com audit_conn, o INSERT de erro vai nessa conexao. Sem ela, vai na conn.
Cursor: materialize o conjunto motor antes de inserir. Taxas vigentes: uma query e casamento em memoria.
SELECT INTO sem linha vira None. Nao reaproveite valor da iteracao anterior.
Comparacao SQL com NULL nao usa != do Python. None != 'ATIVA' mudaria o legado. IF so dispara em verdadeiro.
Chamada de rotina de usuario vira chamada Python de mesmo nome, com conn. Sem inline.
Nao corrija saldo_consolidado para saldo corrido. Mantenha o ramo identidade de TRANSFERENCIA.
DATE(coluna timestamp) permanece na SQL.
Para cada risco listado, escreva um comentario # DECISION: <id> no corpo da funcao.
Devolva so o modulo Python, sem cerca Markdown.
""".strip()

RISK_POLICY: dict[str, tuple[str, str]] = {
    "cursor_n_plus_1": (
        "rewritten_python",
        "Materializar o conjunto e buscar as taxas uma vez.",
    ),
    "raise_exception": ("rewritten_python", "RAISE vira excecao Python com a mesma mensagem."),
    "for_update": ("delegated_sql", "FOR UPDATE permanece no SQL, dentro da transacao do chamador."),
    "jsonb": ("delegated_sql", "jsonb_build_object permanece no SQL."),
    "recursion": ("delegated_sql", "WITH RECURSIVE permanece no SQL."),
    "get_diagnostics": (
        "rewritten_python",
        "rowcount do UPDATE, lido antes do INSERT de auditoria.",
    ),
    "out_parameter": ("rewritten_python", "OUT vira campo da dataclass OutParams."),
    "nested_routine_call": (
        "preserved",
        "Chamada Python de mesmo nome, recebendo conn.",
    ),
    "exception_handler": ("rewritten_python", "EXCEPTION vira try/except no mesmo bloco."),
    "set_returning": ("rewritten_python", "RETURNS TABLE vira list[Row]."),
    "bulk_update": ("delegated_sql", "UPDATE de conjunto permanece um unico comando SQL."),
    "three_valued_logic": (
        "preserved",
        "Desigualdade com NULL nao dispara o if.",
    ),
    "audit_lost_on_rollback": (
        "divergent",
        "Log de erro sobrevive so se o chamador passar audit_conn.",
    ),
    "date_of_timestamp": ("delegated_sql", "DATE(data_transacao) permanece na SQL."),
    "swallowed_exception": (
        "preserved",
        "O except devolve a linha de fallback e nao propaga.",
    ),
}


class Decision(BaseModel):
    risk_id: str
    action: str
    rationale: str


def decisions_for(ir: RoutineIR) -> list[Decision]:
    found = [
        Decision(risk_id=risk.id, action=action, rationale=rationale)
        for risk in ir.risks
        for action, rationale in [RISK_POLICY[risk.id]]
    ]
    day_concat = any("||" in stmt.sql and "days" in stmt.sql for stmt in ir.statements)
    for operation in ir.operations:
        action = "preserved" if operation.kind == "return" else "delegated_sql"
        rationale = f"{operation.kind} permanece na traducao combinada"
        if operation.kind == "update" and day_concat:
            rationale = "UPDATE permanece SQL. O intervalo de dias usa make_interval."
        found.append(Decision(risk_id=f"op:{operation.kind}", action=action, rationale=rationale))
    return found


def build_prompt(ir: RoutineIR, schema_ddl: str | None, source: str) -> str:
    decisions = [item.model_dump() for item in decisions_for(ir)]
    comments = [f"# DECISION: {risk.id}" for risk in ir.risks]
    return "\n\n".join(
        [
            POLICY,
            ir.model_dump_json(),
            str(decisions),
            "\n".join(comments) if comments else "(sem riscos)",
            schema_ddl.strip() if schema_ddl and schema_ddl.strip() else "nenhum schema informado",
            source,
        ]
    )


def strip_fence(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
