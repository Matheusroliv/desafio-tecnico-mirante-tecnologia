import psycopg
from decimal import Decimal

def sp_transferir_entre_contas(conn: psycopg.Connection, p_conta_origem: int, p_conta_destino: int, p_valor: Decimal, audit_conn: psycopg.Connection | None = None) -> None:
    if p_valor is None or p_valor <= 0:
        raise ValueError(f'Valor invalido para transferencia: {p_valor}')

    if p_conta_origem == p_conta_destino:
        raise ValueError('Conta de origem e destino nao podem ser iguais')

    try:
        with conn.transaction():
            cur = conn.execute(
                "SELECT saldo, status FROM contas WHERE id = %s FOR UPDATE",
                (p_conta_origem,)
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f'Conta de origem {p_conta_origem} nao encontrada')
            v_saldo_origem, v_status_origem = row

            cur = conn.execute(
                "SELECT status FROM contas WHERE id = %s FOR UPDATE",
                (p_conta_destino,)
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f'Conta de destino {p_conta_destino} nao encontrada')
            v_status_destino = row[0]

            if v_status_origem != 'ATIVA' or v_status_destino != 'ATIVA':
                raise ValueError('Ambas as contas precisam estar ATIVAS')

            if v_saldo_origem < p_valor:
                raise ValueError(f'Saldo insuficiente: saldo={v_saldo_origem} valor={p_valor}')

            conn.execute(
                "UPDATE contas SET saldo = saldo - %s WHERE id = %s",
                (p_valor, p_conta_origem)
            )
            conn.execute(
                "UPDATE contas SET saldo = saldo + %s WHERE id = %s",
                (p_valor, p_conta_destino)
            )

            conn.execute(
                "INSERT INTO transacoes (conta_origem_id, conta_destino_id, tipo, valor) VALUES (%s, %s, %s, %s)",
                (p_conta_origem, p_conta_destino, 'TRANSFERENCIA', p_valor)
            )

            conn.execute(
                "INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes) VALUES (%s, %s, %s, %s)",
                ('transacoes', None, 'TRANSFERENCIA_OK', psycopg.sql.SQL("jsonb_build_object('origem', %s::bigint, 'destino', %s::bigint, 'valor', %s::numeric)").as_tuple(p_conta_origem, p_conta_destino, p_valor))
            )
    except Exception as exc:
        (audit_conn or conn).execute(
            "INSERT INTO log_auditoria (entidade, acao, detalhes) VALUES (%s, %s, %s)",
            ('transacoes', 'TRANSFERENCIA_ERRO', psycopg.sql.SQL("jsonb_build_object('origem', %s::bigint, 'destino', %s::bigint, 'valor', %s::numeric, 'erro', %s)").as_tuple(p_conta_origem, p_conta_destino, p_valor, str(exc)))
        )
        raise
