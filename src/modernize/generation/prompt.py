"""Montagem do prompt de geracao a partir das saidas das etapas deterministicas.

Ordem dos blocos (PRD secao 11): politica fixa, IR em JSON, riscos com acao e
instrucao especifica, contrato de saida, schema opcional, fonte original e, so no
reparo, o codigo anterior com os achados da validacao. A analise por regras
escolhe o que o modelo le: risco ausente nao entra no prompt.
"""

import json

from pydantic import BaseModel

from modernize.ir.models import Parameter, RoutineIR

POLICY = """
POLITICA DE TRADUCAO

Alvo: Python 3.14. NUMERIC vira Decimal. Sem float para dinheiro, nem Decimal(1.10): use Decimal("1.10").
A funcao recebe conn (psycopg 3) como primeiro argumento. Nao abre conexao, nao chama commit nem rollback.
psycopg 3: cur = conn.execute(sql, params) devolve cursor; use cur.fetchone(), cur.fetchall(), cur.rowcount.
Nunca psycopg2. Nao importe nome que o modulo nao usa.
SQL de conjunto, agregacao, UPDATE em massa e CTE recursiva permanecem SQL, com placeholder %s.
Todo parametro ou variavel PL/pgSQL citado dentro de um SQL vira placeholder %s com o valor Python
correspondente. Nunca deixe nome de variavel PL/pgSQL (p_*, v_*) dentro do texto SQL.
Placeholder passado a funcao SQL polimorfica ou de data (jsonb_build_object, DATE_TRUNC, aritmetica com INTERVAL)
leva cast explicito: %s::bigint, %s::integer, %s::numeric, %s::date, %s::text.
Literal % dentro de SQL com parametros vira %%.
Controle, validacao e RAISE viram Python, na mesma ordem do legado.
SELECT INTO sem linha vira None nos alvos. Nao reaproveite valor da iteracao anterior.
Atribuicao a variavel NUMERIC(p,s) arredonda para s casas: reproduza com
.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) (ajuste as casas pelo DECLARE da fonte) a cada atribuicao.
RAISE NOTICE e RAISE WARNING viram logging.getLogger(__name__); nunca print.
Nao corrija semantica suspeita do legado; preserve o comportamento.
Para cada risco listado, escreva o comentario # DECISION: <id> dentro da funcao, perto do trecho tratado.
Devolva so o modulo Python, sem cerca Markdown.
""".strip()

RISK_POLICY: dict[str, tuple[str, str]] = {
    "cursor_n_plus_1": ("rewritten_python", "Materializar o conjunto e buscar as taxas uma vez."),
    "raise_exception": ("rewritten_python", "RAISE vira excecao Python com a mesma mensagem."),
    "for_update": ("delegated_sql", "FOR UPDATE permanece no SQL, dentro da transacao do chamador."),
    "jsonb": ("delegated_sql", "jsonb_build_object permanece no SQL."),
    "recursion": ("delegated_sql", "WITH RECURSIVE permanece no SQL."),
    "get_diagnostics": ("rewritten_python", "rowcount do UPDATE, lido antes do INSERT de auditoria."),
    "out_parameter": ("rewritten_python", "OUT vira campo da dataclass OutParams."),
    "nested_routine_call": ("preserved", "Chamada Python de mesmo nome, recebendo conn."),
    "exception_handler": ("rewritten_python", "EXCEPTION vira try/except no mesmo bloco, com savepoint."),
    "set_returning": ("rewritten_python", "RETURNS TABLE vira list[Row]."),
    "bulk_update": ("delegated_sql", "UPDATE de conjunto permanece um unico comando SQL."),
    "three_valued_logic": ("preserved", "Desigualdade com NULL nao dispara o if."),
    "audit_lost_on_rollback": ("divergent", "Log de erro sobrevive so se o chamador passar audit_conn."),
    "date_of_timestamp": ("delegated_sql", "DATE(data_transacao) permanece na SQL."),
    "swallowed_exception": ("preserved", "O except devolve a linha de fallback e nao propaga."),
}

RISK_GUIDANCE: dict[str, str] = {
    "cursor_n_plus_1": (
        "Proibido SELECT por linha. Antes do laco: (1) leia todas as linhas do cursor com uma query e fetchall(); "
        "(2) leia a tabela de lookup do laco numa unica query, com o mesmo filtro de vigencia e sem o filtro por "
        "linha; (3) monte um dict em memoria escolhendo, por chave, a linha que o ORDER BY ... LIMIT 1 original "
        "escolheria. No laco: so calculo em Decimal e escritas parametrizadas. Linha sem lookup segue para a "
        "proxima (CONTINUE)."
    ),
    "raise_exception": (
        "RAISE EXCEPTION 'msg %', x vira raise ValueError(f\"msg {x}\") com a mesma mensagem, no mesmo ponto do fluxo."
    ),
    "for_update": (
        "Mantenha FOR UPDATE em cada SELECT, na ordem original. Linha ausente: cur.fetchone() devolve None e as "
        "variaveis de destino ficam None."
    ),
    "jsonb": (
        "jsonb_build_object permanece no SQL. Cada valor vai como placeholder com cast explicito "
        "(%s::bigint, %s::numeric, %s::date, %s::text)."
    ),
    "recursion": "WITH RECURSIVE permanece num unico SQL. Nao gere a sequencia de meses em Python.",
    "get_diagnostics": (
        "GET DIAGNOSTICS x = ROW_COUNT vira x = cur.rowcount do cursor do UPDATE, lido logo depois dele e antes "
        "de qualquer outro comando."
    ),
    "out_parameter": "Parametro OUT nao entra na assinatura. Retorne OutParams(...) com os valores finais.",
    "nested_routine_call": (
        "Rotina de usuario chamada pelo legado: importe com from modernized.<nome> import <nome> e chame "
        "<nome>(conn, ...). Nao copie o SQL dela."
    ),
    "exception_handler": (
        "BEGIN ... EXCEPTION WHEN OTHERS vira try/except Exception envolvendo exatamente as instrucoes do bloco, "
        "inclusive os RAISE de validacao do mesmo bloco. Dentro do try use with conn.transaction(): para que o "
        "erro desfaca so as escritas do bloco (savepoint), como no PL/pgSQL. SQLERRM vira str(exc)."
    ),
    "set_returning": (
        "Declare @dataclass(frozen=True) class Row com as colunas do RETURNS TABLE, na ordem e tipos do contrato, "
        "e retorne list[Row]."
    ),
    "bulk_update": (
        "Um unico UPDATE de conjunto com a mesma subquery. Intervalo em dias: make_interval(days => %s); "
        "nunca concatene texto para montar INTERVAL."
    ),
    "three_valued_logic": (
        "Comparacao SQL (<> ou =) com variavel que pode ser NULL segue logica de tres valores: o IF so dispara se "
        "o resultado for verdadeiro. Escreva (x is not None and x != 'VALOR'). Exemplo: IF a <> 'X' OR b <> 'X' "
        "vira if (a is not None and a != 'X') or (b is not None and b != 'X'):"
    ),
    "audit_lost_on_rollback": (
        "A assinatura termina com audit_conn: psycopg.Connection | None = None. No except: grave o INSERT de erro "
        "em (audit_conn or conn), com as mesmas colunas do legado, e depois raise para propagar."
    ),
    "date_of_timestamp": "Mantenha DATE(coluna) dentro da SQL; nao compare datas em Python.",
    "swallowed_exception": (
        "Inicialize com None as variaveis usadas no fallback antes do try. O try cobre todo o bloco, inclusive a "
        "validacao RAISE. No except: logging warning com a mensagem do legado e retorne o fallback; nao propague."
    ),
}

PY_TYPES = {
    "smallint": "int",
    "integer": "int",
    "bigint": "int",
    "numeric": "Decimal",
    "date": "datetime.date",
    "timestamp": "datetime.datetime",
    "timestamptz": "datetime.datetime",
    "varchar": "str",
    "text": "str",
    "boolean": "bool",
    "jsonb": "dict",
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


def py_type(type_name: str) -> str:
    return PY_TYPES.get(type_name, "object")


def _annotated(params: list[Parameter]) -> list[str]:
    return [f"{item.name}: {py_type(item.type_name)}" for item in params]


def _contract(ir: RoutineIR) -> str:
    ins = [item for item in ir.parameters if item.mode != "out"]
    outs = [item for item in ir.parameters if item.mode != "in"]
    risk_ids = {risk.id for risk in ir.risks}
    args = ["conn: psycopg.Connection", *_annotated(ins)]
    if "audit_lost_on_rollback" in risk_ids:
        args.append("audit_conn: psycopg.Connection | None = None")
    if ir.set_returning:
        returns = "list[Row]"
    elif outs:
        returns = "OutParams"
    elif ir.kind == "function" and ir.returns:
        returns = py_type(ir.returns)
    else:
        returns = "None"
    types_used = {py_type(item.type_name) for item in [*ins, *outs, *ir.return_columns]} | {returns}
    imports = ["import psycopg"]
    if any("datetime." in name for name in types_used):
        imports.insert(0, "import datetime")
    if any("Decimal" in name for name in types_used) or any(v.type_name == "numeric" for v in ir.variables):
        imports.append("from decimal import ROUND_HALF_UP, Decimal  (importe so o que usar)")
    lines = [
        "CONTRATO DE SAIDA. O arquivo e invalido se faltar qualquer item.",
        f"1. Assinatura exata: def {ir.name}({', '.join(args)}) -> {returns}:",
        "2. Imports no topo: " + "; ".join(imports) + ".",
        "3. Sem cerca ``` e sem frase antes ou depois do codigo.",
        "4. ast.parse tem de aceitar o arquivo. Nao importe nome que o corpo nao usa.",
    ]
    if outs:
        fields = "\n".join(f"    {item.name}: {py_type(item.type_name)} | None" for item in outs)
        lines.append(
            "5. OUT nao entra na assinatura. Declare e retorne esta classe:\n"
            "from dataclasses import dataclass\n\n"
            "@dataclass(frozen=True)\n"
            "class OutParams:\n"
            f"{fields}"
        )
    if ir.set_returning and ir.return_columns:
        fields = "\n".join(f"    {item.name}: {py_type(item.type_name)}" for item in ir.return_columns)
        lines.append(
            "6. RETURNS TABLE vira esta classe; retorne list[Row] na ordem do ORDER BY:\n"
            "from dataclasses import dataclass\n\n"
            "@dataclass(frozen=True)\n"
            "class Row:\n"
            f"{fields}"
        )
    if ir.dependencies:
        lines.append(
            "7. Dependencias: " + "; ".join(f"from modernized.{name} import {name}" for name in ir.dependencies) + "."
        )
    if ir.risks:
        lines.append("8. Copie estas linhas dentro da funcao, exatamente assim:")
        lines.extend(f"# DECISION: {risk.id}" for risk in ir.risks)
    else:
        lines.append("8. Nao invente comentario DECISION.")
    return "\n".join(lines)


def _risk_block(ir: RoutineIR) -> str:
    if not ir.risks:
        return "RISCOS DETECTADOS: nenhum."
    lines = ["RISCOS DETECTADOS (acao obrigatoria e instrucao):"]
    for risk in ir.risks:
        action, rationale = RISK_POLICY[risk.id]
        lines.append(f"- {risk.id} [{action}] {rationale} {RISK_GUIDANCE[risk.id]}")
    return "\n".join(lines)


def build_prompt(
    ir: RoutineIR,
    schema_ddl: str | None,
    source: str,
    previous_code: str | None = None,
    feedback: list[str] | None = None,
) -> str:
    decisions = [item.model_dump() for item in decisions_for(ir)]
    ir_view = ir.model_dump(
        include={
            "name",
            "kind",
            "parameters",
            "return_columns",
            "returns",
            "set_returning",
            "variables",
            "constructs",
            "operations",
            "dependencies",
            "risks",
        }
    )
    blocks = [
        POLICY,
        "IR DA ROTINA (saida do parser e da analise):\n" + json.dumps(ir_view, ensure_ascii=False),
        _risk_block(ir),
        "DECISOES DO RELATORIO:\n" + json.dumps(decisions, ensure_ascii=False),
        _contract(ir),
        "SCHEMA DO BANCO LEGADO:\n"
        + (schema_ddl.strip() if schema_ddl and schema_ddl.strip() else "nenhum schema informado"),
        "FONTE PL/pgSQL ORIGINAL:\n" + source,
    ]
    if previous_code is not None:
        blocks.append(
            "REPARO. A tentativa anterior falhou na validacao. Corrija todos os achados abaixo e devolva o modulo "
            "completo.\nACHADOS:\n"
            + "\n".join(f"- {item}" for item in feedback or [])
            + "\nCODIGO ANTERIOR:\n"
            + previous_code
        )
    return "\n\n".join(blocks)


def strip_fence(text: str) -> str:
    cleaned = text.strip()
    if "```" not in cleaned:
        return cleaned
    start = cleaned.find("```")
    body = cleaned[start:].splitlines()[1:]
    end = next((index for index, line in enumerate(body) if line.strip().startswith("```")), len(body))
    return "\n".join(body[:end]).strip()
