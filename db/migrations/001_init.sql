CREATE TABLE IF NOT EXISTS modernization_history (
    id              BIGSERIAL PRIMARY KEY,
    source_code     TEXT NOT NULL,
    generated_code  TEXT,
    report          JSONB NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('sucesso', 'falha', 'parcial')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluation_scores (
    id            BIGSERIAL PRIMARY KEY,
    history_id    BIGINT NOT NULL REFERENCES modernization_history (id),
    routine_name  TEXT NOT NULL,
    metric        TEXT NOT NULL,
    score         NUMERIC(6, 4) NOT NULL,
    detail        JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
