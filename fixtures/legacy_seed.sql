-- =============================================================
-- Massa de teste do banco legado (metrica de Equivalencia Comportamental).
-- Aplicada sobre fixtures/schema.sql num schema temporario, dentro de uma
-- transacao desfeita no fim de cada cenario. Os ids saem das sequencias na
-- ordem dos INSERT abaixo; os comentarios registram o id esperado.
-- Datas relativas a NOW() alimentam o anexo C; datas fixas alimentam E e F.
-- =============================================================

INSERT INTO clientes (nome, cpf, status) VALUES
    ('Ana Souza',   '11111111111', 'ATIVO'),    -- 1
    ('Bruno Lima',  '22222222222', 'ATIVO'),    -- 2
    ('Carla Dias',  '33333333333', 'INATIVO'),  -- 3
    ('Davi Rocha',  '44444444444', 'ATIVO');    -- 4 (sem contas)

INSERT INTO contas (cliente_id, agencia, numero, tipo, saldo, status) VALUES
    (1, '0001', '1000-1', 'CORRENTE', 1000.00, 'ATIVA'),     -- 1
    (1, '0001', '1000-2', 'POUPANCA',  500.50, 'ATIVA'),     -- 2
    (1, '0001', '1000-3', 'CORRENTE',  200.00, 'INATIVA'),   -- 3
    (2, '0002', '2000-1', 'CORRENTE',  300.00, 'ATIVA'),     -- 4
    (2, '0002', '2000-2', 'SALARIO',     0.00, 'ATIVA'),     -- 5 (sem movimento)
    (3, '0003', '3000-1', 'CORRENTE',   50.00, 'ENCERRADA'), -- 6
    (2, '0002', '2000-3', 'POUPANCA',  100.00, 'ATIVA');     -- 7 (movimento antigo)

INSERT INTO transacoes (conta_origem_id, conta_destino_id, tipo, valor, data_transacao, status) VALUES
    -- Movimento recente (anexo C)
    (1,    4,    'TRANSFERENCIA', 100.00, NOW() - INTERVAL '2 days',   'EFETIVADA'), -- 1
    (NULL, 2,    'DEPOSITO',       50.00, NOW() - INTERVAL '10 days',  'EFETIVADA'), -- 2
    (7,    NULL, 'SAQUE',          20.00, NOW() - INTERVAL '400 days', 'EFETIVADA'), -- 3
    -- Lote de 2024-05-10 (anexo E)
    (1,    4,    'TRANSFERENCIA', 250.00, '2024-05-10 09:00:00', 'EFETIVADA'),  -- 4: taxa 1.875 -> 1.88
    (2,    NULL, 'SAQUE',          80.00, '2024-05-10 10:30:00', 'EFETIVADA'),  -- 5: minimo 2.00 * 1.10
    (NULL, 1,    'DEPOSITO',     1000.00, '2024-05-10 11:00:00', 'EFETIVADA'),  -- 6: origem nula, nao aplica
    (4,    NULL, 'SAQUE',          15.00, '2024-05-10 23:59:59', 'EFETIVADA'),  -- 7: fim do dia entra
    (1,    2,    'TRANSFERENCIA',  40.00, '2024-05-10 12:00:00', 'CANCELADA'),  -- 8: fora (status)
    (4,    NULL, 'TARIFA',          3.00, '2024-05-10 13:00:00', 'EFETIVADA'),  -- 9: fora (tipo)
    (2,    1,    'DEPOSITO',      300.00, '2024-05-10 14:00:00', 'EFETIVADA'),  -- 10: ramo ELSE (0.90)
    (1,    4,    'TRANSFERENCIA',  10.00, '2024-05-11 00:00:00', 'EFETIVADA'),  -- 11: dia seguinte
    -- Relatorio mensal jan-mar/2024 (anexo F, cliente 1 = contas 1, 2, 3)
    (1,    4,    'TRANSFERENCIA', 100.00, '2024-01-15 10:00:00', 'EFETIVADA'),  -- 12: debito
    (4,    2,    'TRANSFERENCIA',  60.00, '2024-01-20 08:00:00', 'EFETIVADA'),  -- 13: credito
    (1,    2,    'TRANSFERENCIA',  30.00, '2024-02-05 16:00:00', 'EFETIVADA'),  -- 14: credito e debito
    (NULL, 1,    'DEPOSITO',      500.00, '2024-03-10 18:00:00', 'EFETIVADA'),  -- 15: ultimo dia entra
    (2,    NULL, 'SAQUE',          25.00, '2024-03-11 09:00:00', 'EFETIVADA'),  -- 16: depois do fim
    (3,    4,    'TRANSFERENCIA',  70.00, '2024-02-20 11:00:00', 'ESTORNADA'),  -- 17: fora (status)
    -- Lotes extras (anexo E): vigencia e linha sem taxa
    (4,    NULL, 'SAQUE',          50.00, '2024-06-15 10:00:00', 'EFETIVADA'),  -- 18
    (2,    1,    'DEPOSITO',      100.00, '2024-06-15 11:00:00', 'EFETIVADA'),  -- 19: taxa mais recente vence
    (1,    NULL, 'SAQUE',         100.00, '2023-12-20 10:00:00', 'EFETIVADA'),  -- 20: tem taxa
    (1,    4,    'TRANSFERENCIA', 500.00, '2023-12-20 11:00:00', 'EFETIVADA');  -- 21: sem taxa vigente

INSERT INTO taxas (tipo_operacao, percentual, valor_minimo, vigente_de, vigente_ate) VALUES
    ('TRANSFERENCIA', 0.5000, 1.00, '2024-01-01', NULL),          -- 1
    ('TRANSFERENCIA', 0.7500, 1.50, '2024-05-01', '2024-05-31'),  -- 2: vence em maio (vigente_de maior)
    ('SAQUE',         1.0000, 2.00, '2023-01-01', NULL),          -- 3
    ('DEPOSITO',      0.2000, 0.50, '2024-06-01', NULL),          -- 4
    ('DEPOSITO',      0.1000, 0.30, '2024-01-01', '2024-12-31');  -- 5
