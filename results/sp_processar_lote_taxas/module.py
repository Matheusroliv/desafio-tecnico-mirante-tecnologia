import datetime
import psycopg
from decimal import ROUND_HALF_UP, Decimal

def sp_processar_lote_taxas(conn: psycopg.Connection, p_data_referencia: datetime.date) -> None:
    # DECISION: cursor_n_plus_1
    # DECISION: jsonb
    # DECISION: date_of_timestamp

    # Fetch all transactions
    sql_transactions = """
        SELECT id, conta_origem_id, tipo, valor
        FROM transacoes
        WHERE DATE(data_transacao) = %s
          AND status = 'EFETIVADA'
          AND tipo <> 'TARIFA'
    """
    cur_transactions = conn.execute(sql_transactions, (p_data_referencia,))
    transactions = cur_transactions.fetchall()

    # Fetch all taxas
    sql_taxas = """
        SELECT tipo_operacao, percentual, valor_minimo
        FROM taxas
        WHERE vigente_de <= %s
          AND (vigente_ate IS NULL OR vigente_ate >= %s)
        ORDER BY vigente_de DESC
    """
    cur_taxas = conn.execute(sql_taxas, (p_data_referencia, p_data_referencia))
    taxas = cur_taxas.fetchall()

    # Create a dictionary for quick lookup
    taxas_dict = {}
    for tipo_operacao, percentual, valor_minimo in taxas:
        if tipo_operacao not in taxas_dict:
            taxas_dict[tipo_operacao] = (percentual, valor_minimo)

    v_total_taxas = Decimal("0")
    v_count = 0

    for v_id, v_origem, v_tipo, v_valor in transactions:
        if v_tipo not in taxas_dict:
            continue

        v_percentual, v_minimo = taxas_dict[v_tipo]
        v_taxa = max(v_valor * v_percentual / Decimal("100"), v_minimo)

        if v_tipo == 'TRANSFERENCIA':
            v_taxa = v_taxa
        elif v_tipo == 'SAQUE':
            v_taxa = v_taxa * Decimal("1.10")
        else:
            v_taxa = v_taxa * Decimal("0.90")

        if v_origem is not None:
            sql_update_conta = """
                UPDATE contas SET saldo = saldo - %s WHERE id = %s
            """
            conn.execute(sql_update_conta, (v_taxa, v_origem))

            sql_insert_transacao = """
                INSERT INTO transacoes (conta_origem_id, tipo, valor, status)
                VALUES (%s, 'TARIFA', %s, 'EFETIVADA')
            """
            conn.execute(sql_insert_transacao, (v_origem, v_taxa))

            sql_insert_log = """
                INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                VALUES ('transacoes', %s, 'TARIFA_APLICADA', jsonb_build_object(
                    'transacao_origem', %s::bigint,
                    'tipo_origem', %s::text,
                    'valor_origem', %s::numeric,
                    'percentual', %s::numeric,
                    'taxa_aplicada', %s::numeric
                ))
            """
            conn.execute(sql_insert_log, (v_id, v_id, v_tipo, v_valor, v_percentual, v_taxa))

            v_total_taxas += v_taxa
            v_count += 1

    sql_insert_log_lote = """
        INSERT INTO log_auditoria (entidade, acao, detalhes)
        VALUES ('lote_taxas', 'LOTE_PROCESSADO', jsonb_build_object(
            'data_referencia', %s::date,
            'transacoes', %s::int,
            'total_taxas', %s::numeric
        ))
    """
    conn.execute(sql_insert_log_lote, (p_data_referencia, v_count, v_total_taxas))
