import psycopg
from decimal import Decimal

# DECISION: raise_exception
# DECISION: recursion
# DECISION: nested_routine_call
# DECISION: exception_handler
# DECISION: set_returning
# DECISION: swallowed_exception

def sp_relatorio_mensal_cliente(conn: psycopg.Connection, p_cliente_id: object, p_data_inicio: object, p_data_fim: object):
    if p_data_inicio > p_data_fim:
        raise ValueError(f'Periodo invalido: inicio {p_data_inicio} > fim {p_data_fim}')

    v_saldo_atual = fn_saldo_cliente(conn, p_cliente_id)
    print(f'Saldo atual do cliente {p_cliente_id}: {v_saldo_atual}')

    meses_query = """
    WITH RECURSIVE meses AS (
        SELECT DATE_TRUNC('month', %s)::DATE AS mes
        UNION ALL
        SELECT (mes + INTERVAL '1 month')::DATE
        FROM meses
        WHERE mes < DATE_TRUNC('month', %s)
    ),
    movimento AS (
        SELECT
            DATE_TRUNC('month', t.data_transacao)::DATE AS mes,
            SUM(CASE
                WHEN t.conta_destino_id IN (
                    SELECT id FROM contas WHERE cliente_id = %s
                ) THEN t.valor ELSE 0 END) AS creditos,
            SUM(CASE
                WHEN t.conta_origem_id IN (
                    SELECT id FROM contas WHERE cliente_id = %s
                ) THEN t.valor ELSE 0 END) AS debitos,
            COUNT(*) AS qtd
        FROM transacoes t
        WHERE t.status = 'EFETIVADA'
          AND t.data_transacao >= %s
          AND t.data_transacao < %s + INTERVAL '1 day'
          AND (
              t.conta_origem_id IN (SELECT id FROM contas WHERE cliente_id = %s)
              OR t.conta_destino_id IN (SELECT id FROM contas WHERE cliente_id = %s)
          )
        GROUP BY 1
    )
    SELECT
        m.mes AS mes_referencia,
        COALESCE(mv.creditos, 0) AS total_creditos,
        COALESCE(mv.debitos, 0) AS total_debitos,
        v_saldo_atual + COALESCE(mv.creditos, 0) - COALESCE(mv.debitos, 0) AS saldo_consolidado,
        COALESCE(mv.qtd, 0)::INT AS qtd_transacoes
    FROM meses m
    LEFT JOIN movimento mv ON mv.mes = m.mes
    ORDER BY m.mes
    """

    cursor = conn.cursor()
    cursor.execute(meses_query, (p_data_inicio, p_data_fim, p_cliente_id, p_cliente_id, p_data_inicio, p_data_fim, p_cliente_id, p_cliente_id))
    result = cursor.fetchall()
    cursor.close()

    if not result:
        return [
            (p_data_inicio, Decimal('0.00'), Decimal('0.00'), Decimal(v_saldo_atual) if v_saldo_atual is not None else Decimal('0.00'), 0)
        ]

    return result