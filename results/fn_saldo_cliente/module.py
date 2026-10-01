import psycopg
from decimal import ROUND_HALF_UP, Decimal

def fn_saldo_cliente(conn: psycopg.Connection, p_cliente_id: int) -> Decimal:
    sql = """
    SELECT COALESCE(SUM(saldo), 0)
    FROM contas
    WHERE cliente_id = %s
      AND status = 'ATIVA';
    """
    with conn.cursor() as cur:
        cur.execute(sql, (p_cliente_id,))
        result = cur.fetchone()
        v_total = result[0] if result else Decimal("0.00")
        return v_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
