from decimal import Decimal

import psycopg


def sp_transferir_entre_contas(
    conn: psycopg.Connection,
    p_conta_origem: int,
    p_conta_destino: int,
    p_valor: Decimal,
    audit_conn: psycopg.Connection | None = None,
) -> None:
    # DECISION: exception_handler
    try:
        with conn.transaction():
            # DECISION: raise_exception
            if p_valor is None or p_valor <= 0:
                raise ValueError(f"Valor invalido para transferencia: {p_valor}")
            if p_conta_origem == p_conta_destino:
                raise ValueError("Conta de origem e destino nao podem ser iguais")
            # DECISION: for_update
            row = conn.execute(
                "SELECT saldo, status FROM contas WHERE id = %s FOR UPDATE", (p_conta_origem,)
            ).fetchone()
            v_saldo_origem, v_status_origem = row if row else (None, None)
            row = conn.execute("SELECT status FROM contas WHERE id = %s FOR UPDATE", (p_conta_destino,)).fetchone()
            v_status_destino = row[0] if row else None
            if v_saldo_origem is None:
                raise ValueError(f"Conta de origem {p_conta_origem} nao encontrada")
            # DECISION: three_valued_logic
            if (v_status_origem is not None and v_status_origem != "ATIVA") or (
                v_status_destino is not None and v_status_destino != "ATIVA"
            ):
                raise ValueError("Ambas as contas precisam estar ATIVAS")
            if v_saldo_origem < p_valor:
                raise ValueError(f"Saldo insuficiente: saldo={v_saldo_origem} valor={p_valor}")
            conn.execute("UPDATE contas SET saldo = saldo - %s WHERE id = %s", (p_valor, p_conta_origem))
            conn.execute("UPDATE contas SET saldo = saldo + %s WHERE id = %s", (p_valor, p_conta_destino))
            conn.execute(
                "INSERT INTO transacoes (conta_origem_id, conta_destino_id, tipo, valor) "
                "VALUES (%s, %s, 'TRANSFERENCIA', %s)",
                (p_conta_origem, p_conta_destino, p_valor),
            )
            # DECISION: jsonb
            conn.execute(
                """
                INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                VALUES ('transacoes', NULL, 'TRANSFERENCIA_OK',
                        jsonb_build_object('origem', %s::bigint, 'destino', %s::bigint, 'valor', %s::numeric))
                """,
                (p_conta_origem, p_conta_destino, p_valor),
            )
    except Exception as exc:
        # DECISION: audit_lost_on_rollback
        (audit_conn or conn).execute(
            """
            INSERT INTO log_auditoria (entidade, acao, detalhes)
            VALUES ('transacoes', 'TRANSFERENCIA_ERRO',
                    jsonb_build_object('origem', %s::bigint, 'destino', %s::bigint, 'valor', %s::numeric,
                                       'erro', %s::text))
            """,
            (p_conta_origem, p_conta_destino, p_valor, str(exc)),
        )
        raise
