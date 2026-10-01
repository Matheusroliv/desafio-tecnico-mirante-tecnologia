import psycopg

def sp_processar_lote_taxas(conn, p_data_referencia):
    # DECISION: cursor_n_plus_1
    # DECISION: jsonb
    # DECISION: date_of_timestamp

    with conn.cursor() as cur:
        # Materialize the cursor query
        cur.execute("""
            SELECT id, conta_origem_id, tipo, valor
            FROM transacoes
            WHERE DATE(data_transacao) = %s
              AND status = 'EFETIVADA'
              AND tipo <> 'TARIFA'
        """, (p_data_referencia,))
        transacoes = cur.fetchall()

        v_total_taxas = Decimal('0')
        v_count = 0

        for v_id, v_origem, v_tipo, v_valor in transacoes:
            cur.execute("""
                SELECT percentual, valor_minimo
                FROM taxas
                WHERE tipo_operacao = %s
                  AND vigente_de <= %s
                  AND (vigente_ate IS NULL OR vigente_ate >= %s)
                ORDER BY vigente_de DESC
                LIMIT 1
            """, (v_tipo, p_data_referencia, p_data_referencia))
            row = cur.fetchone()
            if row:
                v_percentual, v_minimo = row
            else:
                continue

            v_taxa = max(v_valor * v_percentual / Decimal('100.0'), v_minimo)

            if v_tipo == 'TRANSFERENCIA':
                v_taxa = v_taxa
            elif v_tipo == 'SAQUE':
                v_taxa = v_taxa * Decimal('1.10')
            else:
                v_taxa = v_taxa * Decimal('0.90')

            if v_origem is not None:
                cur.execute("""
                    UPDATE contas SET saldo = saldo - %s WHERE id = %s
                """, (v_taxa, v_origem))
                cur.execute("""
                    INSERT INTO transacoes (conta_origem_id, tipo, valor, status)
                    VALUES (%s, 'TARIFA', %s, 'EFETIVADA')
                """, (v_origem, v_taxa))
                cur.execute("""
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

        cur.execute("""
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