import psycopg

def sp_relatorio_mensal_cliente(conn, p_cliente_id, p_data_inicio, p_data_fim):
    # DECISION: raise_exception
    # DECISION: recursion
    # DECISION: nested_routine_call
    # DECISION: exception_handler
    # DECISION: set_returning
    # DECISION: swallowed_exception

    if p_data_inicio > p_data_fim:
        raise Exception(f'Periodo invalido: inicio {p_data_inicio} > fim {p_data_fim}')

    v_saldo_atual = fn_saldo_cliente(conn, p_cliente_id)
    print(f'Saldo atual do cliente {p_cliente_id}: {v_saldo_atual}')

    try:
        with conn.cursor() as cursor:
            sql = """
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
                %s + COALESCE(mv.creditos, 0) - COALESCE(mv.debitos, 0) AS saldo_consolidado,
                COALESCE(mv.qtd, 0)::INT AS qtd_transacoes
            FROM meses m
            LEFT JOIN movimento mv ON mv.mes = m.mes
            ORDER BY m.mes
            """
            cursor.execute(sql, (p_data_inicio, p_data_fim, p_cliente_id, p_cliente_id, p_data_inicio, p_data_fim, p_cliente_id, p_cliente_id, v_saldo_atual))
            return cursor.fetchall()
    except Exception as e:
        print(f'Falha ao gerar relatorio: {e}. Retornando linha de fallback.')
        return [(p_data_inicio, 0, 0, v_saldo_atual, 0)]

def fn_saldo_cliente(conn, p_cliente_id):
    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM contas WHERE cliente_id = %s", (p_cliente_id,))
        result = cursor.fetchone()
        return result[0] if result else 0