import psycopg
from dataclasses import dataclass

@dataclass
class OutParams:
    p_afetadas: int

def sp_atualizar_status_contas_inativas(conn: psycopg.Connection, p_dias: object):
    # DECISION: raise_exception
    # DECISION: jsonb
    # DECISION: get_diagnostics
    # DECISION: out_parameter
    # DECISION: bulk_update

    if p_dias is None or p_dias <= 0:
        raise ValueError(f'Parametro p_dias deve ser positivo, recebido: {p_dias}')

    cursor = conn.cursor()
    cursor.execute("""
        UPDATE contas c
            SET status = 'INATIVA'
            WHERE c.status = 'ATIVA'
              AND NOT EXISTS (
                  SELECT 1
                  FROM transacoes t
                  WHERE (t.conta_origem_id = c.id OR t.conta_destino_id = c.id)
                    AND t.data_transacao >= NOW() - INTERVAL %s
              )
    """, (f'{p_dias} days',))

    p_afetadas = cursor.rowcount

    cursor.execute("""
        INSERT INTO log_auditoria (entidade, acao, detalhes)
        VALUES (
            'contas',
            'INATIVACAO_LOTE',
            jsonb_build_object('dias', %s, 'afetadas', %s)
        )
    """, (p_dias, p_afetadas))

    conn.commit()

    return OutParams(p_afetadas)