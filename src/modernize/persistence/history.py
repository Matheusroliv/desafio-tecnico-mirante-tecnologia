"""Repositorio do historico da pipeline (porta + implementacoes Postgres e memoria)."""

import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "db" / "migrations"


class HistoryRepository(Protocol):
    def insert(self, *, source_code: str, generated_code: str | None, report: dict, status: str) -> int: ...

    def insert_score(self, *, history_id: int, routine_name: str, metric: str, score: float, detail: dict) -> int: ...

    def get(self, history_id: int) -> dict | None: ...


class MemoryHistory:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.scores: list[dict] = []
        self._lock = threading.Lock()

    def insert(self, *, source_code: str, generated_code: str | None, report: dict, status: str) -> int:
        with self._lock:
            self.rows.append(
                {
                    "id": len(self.rows) + 1,
                    "source_code": source_code,
                    "generated_code": generated_code,
                    "report": report,
                    "status": status,
                    "created_at": datetime.now(UTC),
                }
            )
            return len(self.rows)

    def insert_score(self, *, history_id: int, routine_name: str, metric: str, score: float, detail: dict) -> int:
        with self._lock:
            self.scores.append(
                {
                    "history_id": history_id,
                    "routine_name": routine_name,
                    "metric": metric,
                    "score": score,
                    "detail": detail,
                }
            )
            return len(self.scores)

    def get(self, history_id: int) -> dict | None:
        if 1 <= history_id <= len(self.rows):
            return dict(self.rows[history_id - 1])
        return None


class PsycopgHistory:
    """Uma conexao curta por escrita: o servidor nao guarda estado entre requisicoes.

    Com volume, trocar por ``psycopg_pool.ConnectionPool`` sem mudar a porta.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn
        self._ready = False
        self._lock = threading.Lock()

    @property
    def dsn(self) -> str:
        return self._dsn if self._dsn is not None else os.environ.get("DATABASE_URL", "")

    def insert(self, *, source_code: str, generated_code: str | None, report: dict, status: str) -> int:
        return self._insert(
            """
            INSERT INTO modernization_history (source_code, generated_code, report, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (source_code, generated_code, report, status),
        )

    def insert_score(self, *, history_id: int, routine_name: str, metric: str, score: float, detail: dict) -> int:
        return self._insert(
            """
            INSERT INTO evaluation_scores (history_id, routine_name, metric, score, detail)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (history_id, routine_name, metric, score, detail),
        )

    def get(self, history_id: int) -> dict | None:
        from psycopg.rows import dict_row

        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, source_code, generated_code, report, status, created_at
                  FROM modernization_history
                 WHERE id = %s
                """,
                (history_id,),
            )
            return cur.fetchone()

    def _connect(self) -> Any:
        import psycopg

        if not self.dsn:
            raise RuntimeError("DATABASE_URL ausente")
        conn = psycopg.connect(self.dsn, connect_timeout=5)
        self._migrate(conn)
        return conn

    def _migrate(self, conn: Any) -> None:
        """Aplica as migracoes idempotentes uma vez por processo (o init do Compose ja as roda)."""
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            for path in sorted(MIGRATIONS.glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))
            conn.commit()
            self._ready = True

    def _insert(self, sql: str, params: tuple) -> int:
        from psycopg.types.json import Jsonb

        values = tuple(Jsonb(item) if isinstance(item, dict) else item for item in params)
        with self._connect() as conn:
            row = conn.execute(sql, values).fetchone()
        if row is None:
            raise RuntimeError("insert sem retorno")
        return int(row[0])
