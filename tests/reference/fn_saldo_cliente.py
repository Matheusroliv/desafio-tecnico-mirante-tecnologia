from decimal import Decimal

import psycopg


def fn_saldo_cliente(conn: psycopg.Connection, p_cliente_id: int) -> Decimal:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(saldo), 0)
          FROM contas
         WHERE cliente_id = %s
           AND status = 'ATIVA'
        """,
        (p_cliente_id,),
    ).fetchone()
    return row[0]
