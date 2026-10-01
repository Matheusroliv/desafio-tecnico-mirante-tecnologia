"""Cenarios da Equivalencia Comportamental, por rotina dos anexos B-F.

Cada cenario e uma lista de argumentos IN, em JSON: inteiro, texto decimal
("100.00") para NUMERIC, texto ISO ("2024-05-10") para DATE, ou null. A massa
esta em ``fixtures/legacy_seed.sql``. Cada cenario existe para proteger uma regra
da politica de traducao; o nome diz qual.
"""

SCENARIOS: dict[str, list[dict]] = {
    "fn_saldo_cliente": [
        {"name": "cliente com conta inativa fora da soma", "args": [1]},
        {"name": "cliente com conta de saldo zero", "args": [2]},
        {"name": "cliente so com conta encerrada devolve 0", "args": [3]},
        {"name": "cliente sem conta devolve 0 e nao None", "args": [4]},
    ],
    "sp_atualizar_status_contas_inativas": [
        {"name": "janela de 30 dias", "args": [30]},
        {"name": "janela de 5 dias", "args": [5]},
        {"name": "p_dias zero levanta antes do UPDATE", "args": [0]},
        {"name": "p_dias nulo levanta", "args": [None]},
    ],
    "sp_transferir_entre_contas": [
        {"name": "transferencia valida", "args": [1, 4, "100.00"]},
        {"name": "valor zero", "args": [1, 4, "0.00"]},
        {"name": "origem igual ao destino", "args": [1, 1, "10.00"]},
        {"name": "origem inexistente", "args": [999, 4, "10.00"]},
        {"name": "destino inexistente: NULL <> 'ATIVA' nao dispara o IF (erro vem da FK)", "args": [1, 999, "50.00"]},
        {"name": "destino inativo", "args": [1, 3, "10.00"]},
        {"name": "saldo insuficiente", "args": [2, 4, "5000.00"]},
        {"name": "valor igual ao saldo passa", "args": [4, 1, "300.00"]},
    ],
    "sp_processar_lote_taxas": [
        {"name": "lote com arredondamento, minimo, origem nula e ramo ELSE", "args": ["2024-05-10"]},
        {"name": "vigencia mais recente vence", "args": ["2024-06-15"]},
        {"name": "linha sem taxa nao herda taxa da linha anterior", "args": ["2023-12-20"]},
        {"name": "data sem transacoes grava lote vazio", "args": ["2025-01-01"]},
    ],
    "sp_relatorio_mensal_cliente": [
        {"name": "tres meses com dupla contagem intra-cliente", "args": [1, "2024-01-15", "2024-03-10"]},
        {"name": "um mes so", "args": [1, "2024-02-01", "2024-02-29"]},
        {"name": "periodo invalido cai no fallback", "args": [1, "2024-03-10", "2024-01-01"]},
        {"name": "cliente sem contas", "args": [4, "2024-01-01", "2024-03-31"]},
        {"name": "outro cliente", "args": [2, "2024-01-01", "2024-06-30"]},
    ],
}
