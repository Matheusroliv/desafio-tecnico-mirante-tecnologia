import psycopg

class OutParams:
    def __init__(self, p_afetadas):
        self.p_afetadas = p_afetadas

def sp_atualizar_status_contas_inativas(conn, p_dias):
    # DECISION: raise_exception
    # DECISION: jsonb
    # DECISION: get_diagnostics
    # DECISION: out_parameter
    # DECISION: bulk_update

    if p_dias is None or p_dias <= 0:
        raise Exception(f'Parametro p_dias deve ser positivo, recebido: {p_dias}')

    with conn.cursor() as cursor:
        # DECISION: bulk_update
        cursor.execute("""
            UPDATE contas c
            SET status = 'INATIVA'
            WHERE c.status = 'ATIVA'
              AND NOT EXISTS (
                  SELECT 1
                  FROM transacoes t
                  WHERE (t.conta_origem_id = c.id OR t.conta_destino_id = c.id)
                    AND t.data_transacao >= NOW() - make_interval(days => %s)
              )
        """, (p_dias,))

        # DECISION: get_diagnostics
        p_afetadas = cursor.rowcount

        # DECISION: jsonb
        cursor.execute("""
            INSERT INTO log_auditoria (entidade, acao, detalhes)
            VALUES (
                'contas',
                'INATIVACAO_LOTE',
                jsonb_build_object('dias', %s, 'afetadas', %s)
            )
        """, (p_dias, p_afetadas))

    return OutParams(p_afetadas)