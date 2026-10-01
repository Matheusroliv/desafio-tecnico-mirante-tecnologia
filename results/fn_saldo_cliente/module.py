import psycopg

def fn_saldo_cliente(conn, p_cliente_id: int) -> Decimal:
    # DECISION: op:select
    # DECISION: op:return
    v_total = Decimal(0)
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COALESCE(SUM(saldo), 0) FROM contas WHERE cliente_id = %s AND status = 'ATIVA'",
            (p_cliente_id,)
        )
        row = cursor.fetchone()
        if row:
            v_total = Decimal(row[0])
    return v_total