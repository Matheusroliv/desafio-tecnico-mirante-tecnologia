from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class OutParams:
    p_afetadas: int | None


def sp_atualizar_status_contas_inativas(conn: psycopg.Connection, p_dias: int) -> OutParams:
    # DECISION: raise_exception
    if p_dias is None or p_dias <= 0:
        raise ValueError(f"Parametro p_dias deve ser positivo, recebido: {p_dias}")
    # DECISION: bulk_update
    cur = conn.execute(
        """
        UPDATE contas c
           SET status = 'INATIVA'
         WHERE c.status = 'ATIVA'
           AND NOT EXISTS (
               SELECT 1
                 FROM transacoes t
                WHERE (t.conta_origem_id = c.id OR t.conta_destino_id = c.id)
                  AND t.data_transacao >= NOW() - make_interval(days => %s::integer)
           )
        """,
        (p_dias,),
    )
    # DECISION: get_diagnostics
    p_afetadas = cur.rowcount
    # DECISION: jsonb
    conn.execute(
        """
        INSERT INTO log_auditoria (entidade, acao, detalhes)
        VALUES ('contas', 'INATIVACAO_LOTE', jsonb_build_object('dias', %s::integer, 'afetadas', %s::integer))
        """,
        (p_dias, p_afetadas),
    )
    # DECISION: out_parameter
    return OutParams(p_afetadas=p_afetadas)
