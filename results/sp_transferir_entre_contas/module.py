import psycopg

def sp_transferir_entre_contas(conn, p_conta_origem, p_conta_destino, p_valor):
    # DECISION: raise_exception
    # DECISION: for_update
    # DECISION: jsonb
    # DECISION: exception_handler
    # DECISION: three_valued_logic
    # DECISION: audit_lost_on_rollback

    if p_valor is None or p_valor <= 0:
        raise Exception(f'Valor invalido para transferencia: {p_valor}')

    if p_conta_origem == p_conta_destino:
        raise Exception('Conta de origem e destino nao podem ser iguais')

    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT saldo, status
            FROM contas
            WHERE id = %s
            FOR UPDATE
        """, (p_conta_origem,))
        v_saldo_origem, v_status_origem = cursor.fetchone()

        cursor.execute("""
            SELECT status
            FROM contas
            WHERE id = %s
            FOR UPDATE
        """, (p_conta_destino,))
        v_status_destino = cursor.fetchone()[0]

        if v_saldo_origem is None:
            raise Exception(f'Conta de origem {p_conta_origem} nao encontrada')

        if v_status_origem != 'ATIVA' or v_status_destino != 'ATIVA':
            raise Exception('Ambas as contas precisam estar ATIVAS')

        if v_saldo_origem < p_valor:
            raise Exception(f'Saldo insuficiente: saldo={v_saldo_origem} valor={p_valor}')

        cursor.execute("""
            UPDATE contas SET saldo = saldo - %s WHERE id = %s
        """, (p_valor, p_conta_origem))

        cursor.execute("""
            UPDATE contas SET saldo = saldo + %s WHERE id = %s
        """, (p_valor, p_conta_destino))

        cursor.execute("""
            INSERT INTO transacoes (conta_origem_id, conta_destino_id, tipo, valor)
            VALUES (%s, %s, 'TRANSFERENCIA', %s)
        """, (p_conta_origem, p_conta_destino, p_valor))

        cursor.execute("""
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
        """, (p_conta_origem, p_conta_destino, p_valor))

    except Exception as e:
        with conn.cursor() as cursor:
            cursor.execute("""
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
            """, (p_conta_origem, p_conta_destino, p_valor, str(e)))
        raise e