import psycopg
from decimal import Decimal

def fn_saldo_cliente(conn: psycopg.Connection, p_cliente_id: object):
    v_total = Decimal('0.00')
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(SUM(saldo), 0) FROM contas WHERE cliente_id = %s AND status = 'ATIVA'", (p_cliente_id,))
    result = cursor.fetchone()
    if result:
        v_total = Decimal(result[0])
    cursor.close()
    return v_total