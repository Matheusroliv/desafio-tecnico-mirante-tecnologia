import psycopg
from decimal import Decimal

def sp_transferir_entre_contas(conn: psycopg.Connection, p_conta_origem: object, p_conta_destino: object, p_valor: object):
    # DECISION: raise_exception
    # DECISION: for_update
    # DECISION: jsonb
    # DECISION: exception_handler
    # DECISION: three_valued_logic
    # DECISION: audit_lost_on_rollback

    if p_valor is None or p_valor <= 0:
        raise ValueError(f'Valor invalido para transferencia: {p_valor}')

    if p_conta_origem == p_conta_destino:
        raise ValueError('Conta de origem e destino nao podem ser iguais')

    sql = """
    SELECT saldo, status
        FROM contas
        WHERE id = %s
        FOR UPDATE
    """
    conn.execute(sql, (p_conta_origem,))
    v_saldo_origem, v_status_origem = conn.fetchone()

    if v_saldo_origem is None:
        raise ValueError(f'Conta de origem {p_conta_origem} nao encontrada')

    sql = """
    SELECT status
        FROM contas
        WHERE id = %s
        FOR UPDATE
    """
    conn.execute(sql, (p_conta_destino,))
    v_status_destino, = conn.fetchone()

    if v_status_origem != 'ATIVA' or v_status_destino != 'ATIVA':
        raise ValueError('Ambas as contas precisam estar ATIVAS')

    if v_saldo_origem < p_valor:
        raise ValueError(f'Saldo insuficiente: saldo={v_saldo_origem} valor={p_valor}')

    sql = """
    UPDATE contas SET saldo = saldo - %s WHERE id = %s
    """
    conn.execute(sql, (p_valor, p_conta_origem))

    sql = """
    UPDATE contas SET saldo = saldo + %s WHERE id = %s
    """
    conn.execute(sql, (p_valor, p_conta_destino))

    sql = """
    INSERT INTO transacoes (conta_origem_id, conta_destino_id, tipo, valor)
    VALUES (%s, %s, 'TRANSFERENCIA', %s)
    """
    conn.execute(sql, (p_conta_origem, p_conta_destino, p_valor))

    sql = """
    INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
    VALUES (
        'transacoes',
        NULL,
        'TRANSFERENCIA_OK',
        jsonb_build_object(
            'origem', %s,
            'destino', %s,
            'valor', %s
        )
    )
    """
    conn.execute(sql, (p_conta_origem, p_conta_destino, p_valor))

    try:
        conn.commit()
    except Exception as e:
        sql = """
        INSERT INTO log_auditoria (entidade, acao, detalhes)
        VALUES (
            'transacoes',
            'TRANSFERENCIA_ERRO',
            jsonb_build_object(
                'origem', %s,
                'destino', %s,
                'valor', %s,
                'erro', %s
            )
        )
        """
        conn.execute(sql, (p_conta_origem, p_conta_destino, p_valor, str(e)))
        raise