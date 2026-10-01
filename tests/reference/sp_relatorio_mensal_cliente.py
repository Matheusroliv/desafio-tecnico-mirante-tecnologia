import datetime
import logging
from dataclasses import dataclass
from decimal import Decimal

import psycopg
from modernized.fn_saldo_cliente import fn_saldo_cliente

logger = logging.getLogger(__name__)

RELATORIO = """
WITH RECURSIVE meses AS (
    SELECT DATE_TRUNC('month', %(inicio)s::date)::DATE AS mes
    UNION ALL
    SELECT (mes + INTERVAL '1 month')::DATE
      FROM meses
     WHERE mes < DATE_TRUNC('month', %(fim)s::date)
),
contas_cliente AS (
    SELECT id FROM contas WHERE cliente_id = %(cliente)s
),
movimento AS (
    SELECT DATE_TRUNC('month', t.data_transacao)::DATE AS mes,
           SUM(CASE WHEN t.conta_destino_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS creditos,
           SUM(CASE WHEN t.conta_origem_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS debitos,
           COUNT(*) AS qtd
      FROM transacoes t
     WHERE t.status = 'EFETIVADA'
       AND t.data_transacao >= %(inicio)s::date
       AND t.data_transacao < %(fim)s::date + INTERVAL '1 day'
       AND (t.conta_origem_id IN (SELECT id FROM contas_cliente)
            OR t.conta_destino_id IN (SELECT id FROM contas_cliente))
     GROUP BY 1
)
SELECT m.mes,
       COALESCE(mv.creditos, 0),
       COALESCE(mv.debitos, 0),
       %(saldo)s::numeric + COALESCE(mv.creditos, 0) - COALESCE(mv.debitos, 0),
       COALESCE(mv.qtd, 0)::INT
  FROM meses m
  LEFT JOIN movimento mv ON mv.mes = m.mes
 ORDER BY m.mes
"""


@dataclass(frozen=True)
class Row:
    mes_referencia: datetime.date
    total_creditos: Decimal
    total_debitos: Decimal
    saldo_consolidado: Decimal
    qtd_transacoes: int


def sp_relatorio_mensal_cliente(
    conn: psycopg.Connection, p_cliente_id: int, p_data_inicio: datetime.date, p_data_fim: datetime.date
) -> list[Row]:
    # DECISION: swallowed_exception
    v_saldo_atual: Decimal | None = None
    # DECISION: exception_handler
    try:
        with conn.transaction():
            # DECISION: raise_exception
            if p_data_inicio > p_data_fim:
                raise ValueError(f"Periodo invalido: inicio {p_data_inicio} > fim {p_data_fim}")
            # DECISION: nested_routine_call
            v_saldo_atual = fn_saldo_cliente(conn, p_cliente_id)
            logger.info("Saldo atual do cliente %s: %s", p_cliente_id, v_saldo_atual)
            # DECISION: recursion
            # DECISION: set_returning
            rows = conn.execute(
                RELATORIO,
                {"inicio": p_data_inicio, "fim": p_data_fim, "cliente": p_cliente_id, "saldo": v_saldo_atual},
            ).fetchall()
            return [Row(*row) for row in rows]
    except Exception as exc:
        logger.warning("Falha ao gerar relatorio: %s. Retornando linha de fallback.", exc)
        saldo = v_saldo_atual if v_saldo_atual is not None else Decimal("0")
        return [Row(p_data_inicio.replace(day=1), Decimal("0"), Decimal("0"), saldo, 0)]
