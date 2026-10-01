import psycopg
from decimal import Decimal

def sp_processar_lote_taxas(conn: psycopg.Connection, p_data_referencia: object):
    # DECISION: cursor_n_plus_1
    # DECISION: jsonb
    # DECISION: date_of_timestamp

    cur_transacoes = conn.cursor()
    cur_transacoes.execute("""
        SELECT id, conta_origem_id, tipo, valor
        FROM transacoes
        WHERE DATE(data_transacao) = %s
          AND status = 'EFETIVADA'
          AND tipo <> 'TARIFA'
    """, (p_data_referencia,))

    v_id = None
    v_origem = None
    v_tipo = None
    v_valor = None
    v_taxa = None
    v_percentual = None
    v_minimo = None
    v_total_taxas = Decimal(0)
    v_count = 0

    for row in cur_transacoes:
        v_id, v_origem, v_tipo, v_valor = row

        cur_taxas = conn.cursor()
        cur_taxas.execute("""
            SELECT percentual, valor_minimo
            FROM taxas
            WHERE tipo_operacao = %s
              AND vigente_de <= %s
              AND (vigente_ate IS NULL OR vigente_ate >= %s)
            ORDER BY vigente_de DESC
            LIMIT 1
        """, (v_tipo, p_data_referencia, p_data_referencia))

        taxas_row = cur_taxas.fetchone()
        if taxas_row:
            v_percentual, v_minimo = taxas_row

        if v_percentual is None:
            continue

        v_taxa = max(v_valor * v_percentual / Decimal(100.0), v_minimo)

        if v_tipo == 'TRANSFERENCIA':
            v_taxa = v_taxa
        elif v_tipo == 'SAQUE':
            v_taxa = v_taxa * Decimal(1.10)
        else:
            v_taxa = v_taxa * Decimal(0.90)

        if v_origem is not None:
            conn.execute("""
                UPDATE contas SET saldo = saldo - %s WHERE id = %s
            """, (v_taxa, v_origem))

            conn.execute("""
                INSERT INTO transacoes (conta_origem_id, tipo, valor, status)
                VALUES (%s, 'TARIFA', %s, 'EFETIVADA')
            """, (v_origem, v_taxa))

            conn.execute("""
                INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                VALUES (
                    'transacoes',
                    %s,
                    'TARIFA_APLICADA',
                    jsonb_build_object(
                        'transacao_origem', %s,
                        'tipo_origem', %s,
                        'valor_origem', %s,
                        'percentual', %s,
                        'taxa_aplicada', %s
                    )
                )
            """, (v_id, v_id, v_tipo, v_valor, v_percentual, v_taxa))

            v_total_taxas += v_taxa
            v_count += 1

    cur_transacoes.close()

    conn.execute("""
        INSERT INTO log_auditoria (entidade, acao, detalhes)
        VALUES (
            'lote_taxas',
            'LOTE_PROCESSADO',
            jsonb_build_object(
                'data_referencia', %s,
                'transacoes', %s,
                'total_taxas', %s
            )
        )
    """, (p_data_referencia, v_count, v_total_taxas))