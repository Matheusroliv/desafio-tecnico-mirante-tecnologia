import datetime
import psycopg
from decimal import Decimal
from dataclasses import dataclass
from modernized.fn_saldo_cliente import fn_saldo_cliente
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO)

@dataclass(frozen=True)
class Row:
    mes_referencia: datetime.date
    total_creditos: Decimal
    total_debitos: Decimal
    saldo_consolidado: Decimal
    qtd_transacoes: int

def sp_relatorio_mensal_cliente(conn: psycopg.Connection, p_cliente_id: int, p_data_inicio: datetime.date, p_data_fim: datetime.date) -> list[Row]:
    # DECISION: raise_exception
    # DECISION: recursion
    # DECISION: nested_routine_call
    # DECISION: exception_handler
    # DECISION: set_returning
    # DECISION: swallowed_exception

    v_saldo_atual = None

    try:
        if p_data_inicio > p_data_fim:
            raise ValueError(f"Periodo invalido: inicio {p_data_inicio} > fim {p_data_fim}")

        v_saldo_atual = fn_saldo_cliente(conn, p_cliente_id)
        logging.info(f'Saldo atual do cliente {p_cliente_id}: {v_saldo_atual}')

        with conn.transaction():
            sql = """
            WITH RECURSIVE meses AS (
                SELECT DATE_TRUNC('month', %s::date)::date AS mes
                UNION ALL
                SELECT (mes + INTERVAL '1 month')::date
                FROM meses
                WHERE mes < DATE_TRUNC('month', %s::date)
            ),
            movimento AS (
                SELECT
                    DATE_TRUNC('month', t.data_transacao)::date AS mes,
                    SUM(CASE
                        WHEN t.conta_destino_id IN (
                            SELECT id FROM contas WHERE cliente_id = %s::bigint
                        ) THEN t.valor ELSE 0 END) AS creditos,
                    SUM(CASE
                        WHEN t.conta_origem_id IN (
                            SELECT id FROM contas WHERE cliente_id = %s::bigint
                        ) THEN t.valor ELSE 0 END) AS debitos,
                    COUNT(*) AS qtd
                FROM transacoes t
                WHERE t.status = 'EFETIVADA'
                  AND t.data_transacao >= %s::date
                  AND t.data_transacao < %s::date + INTERVAL '1 day'
                  AND (
                      t.conta_origem_id IN (SELECT id FROM contas WHERE cliente_id = %s::bigint)
                      OR t.conta_destino_id IN (SELECT id FROM contas WHERE cliente_id = %s::bigint)
                  )
                GROUP BY 1
            )
            SELECT
                m.mes AS mes_referencia,
                COALESCE(mv.creditos, 0)::numeric(18, 2) AS total_creditos,
                COALESCE(mv.debitos, 0)::numeric(18, 2) AS total_debitos,
                %s::numeric(18, 2) + COALESCE(mv.creditos, 0)::numeric(18, 2) - COALESCE(mv.debitos, 0)::numeric(18, 2) AS saldo_consolidado,
                COALESCE(mv.qtd, 0)::int AS qtd_transacoes
            FROM meses m
            LEFT JOIN movimento mv ON mv.mes = m.mes
            ORDER BY m.mes
            """
            params = (p_data_inicio, p_data_fim, p_cliente_id, p_cliente_id, p_data_inicio, p_data_fim, p_cliente_id, p_cliente_id, v_saldo_atual)
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
            return [Row(*row) for row in rows]

    except Exception as exc:
        logging.warning(f'Falha ao gerar relatorio: {str(exc)}. Retornando linha de fallback.')
        return [
            Row(
                mes_referencia=datetime.date(p_data_inicio.year, p_data_inicio.month, 1),
                total_creditos=Decimal("0.00"),
                total_debitos=Decimal("0.00"),
                saldo_consolidado=Decimal("0.00") if v_saldo_atual is None else v_saldo_atual,
                qtd_transacoes=0
            )
        ]
