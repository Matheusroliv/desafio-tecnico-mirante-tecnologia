import datetime
from decimal import ROUND_HALF_UP, Decimal

import psycopg

CENTAVO = Decimal("0.01")


def _numeric_18_2(value: Decimal) -> Decimal:
    return value.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def sp_processar_lote_taxas(conn: psycopg.Connection, p_data_referencia: datetime.date) -> None:
    # DECISION: cursor_n_plus_1
    # DECISION: date_of_timestamp
    linhas = conn.execute(
        """
        SELECT id, conta_origem_id, tipo, valor
          FROM transacoes
         WHERE DATE(data_transacao) = %s
           AND status = 'EFETIVADA'
           AND tipo <> 'TARIFA'
        """,
        (p_data_referencia,),
    ).fetchall()
    vigentes = conn.execute(
        """
        SELECT tipo_operacao, percentual, valor_minimo
          FROM taxas
         WHERE vigente_de <= %s
           AND (vigente_ate IS NULL OR vigente_ate >= %s)
         ORDER BY tipo_operacao, vigente_de DESC
        """,
        (p_data_referencia, p_data_referencia),
    ).fetchall()
    taxas: dict[str, tuple[Decimal, Decimal]] = {}
    for tipo, percentual, minimo in vigentes:
        taxas.setdefault(tipo, (percentual, minimo))

    v_total_taxas = Decimal("0")
    v_count = 0
    for v_id, v_origem, v_tipo, v_valor in linhas:
        taxa = taxas.get(v_tipo)
        if taxa is None or taxa[0] is None:
            continue
        v_percentual, v_minimo = taxa
        v_taxa = _numeric_18_2(max(v_valor * v_percentual / Decimal("100.0"), v_minimo))
        if v_tipo == "TRANSFERENCIA":
            v_taxa = v_taxa
        elif v_tipo == "SAQUE":
            v_taxa = _numeric_18_2(v_taxa * Decimal("1.10"))
        else:
            v_taxa = _numeric_18_2(v_taxa * Decimal("0.90"))
        if v_origem is not None:
            conn.execute("UPDATE contas SET saldo = saldo - %s WHERE id = %s", (v_taxa, v_origem))
            conn.execute(
                "INSERT INTO transacoes (conta_origem_id, tipo, valor, status) VALUES (%s, 'TARIFA', %s, 'EFETIVADA')",
                (v_origem, v_taxa),
            )
            # DECISION: jsonb
            conn.execute(
                """
                INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                VALUES ('transacoes', %s, 'TARIFA_APLICADA', jsonb_build_object(
                    'transacao_origem', %s::bigint, 'tipo_origem', %s::text, 'valor_origem', %s::numeric,
                    'percentual', %s::numeric, 'taxa_aplicada', %s::numeric))
                """,
                (v_id, v_id, v_tipo, v_valor, v_percentual, v_taxa),
            )
            v_total_taxas = _numeric_18_2(v_total_taxas + v_taxa)
            v_count += 1

    conn.execute(
        """
        INSERT INTO log_auditoria (entidade, acao, detalhes)
        VALUES ('lote_taxas', 'LOTE_PROCESSADO', jsonb_build_object(
            'data_referencia', %s::date, 'transacoes', %s::integer, 'total_taxas', %s::numeric))
        """,
        (p_data_referencia, v_count, v_total_taxas),
    )
