import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "db" / "migrations" / "001_init.sql"


class MemoryHistory:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.scores: list[dict] = []

    def insert(self, *, source_code: str, generated_code: str | None, report: dict, status: str) -> int:
        self.rows.append(
            {
                "source_code": source_code,
                "generated_code": generated_code,
                "report": report,
                "status": status,
            }
        )
        return len(self.rows)

    def insert_score(
        self,
        *,
        history_id: int,
        routine_name: str,
        metric: str,
        score: float,
        detail: dict,
    ) -> int:
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


class PsycopgHistory:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn if dsn is not None else os.environ.get("DATABASE_URL", "")
        self._ready = False

    def insert(self, *, source_code: str, generated_code: str | None, report: dict, status: str) -> int:
        return self._execute(
            """
            INSERT INTO modernization_history (source_code, generated_code, report, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (source_code, generated_code, report, status),
        )

    def insert_score(
        self,
        *,
        history_id: int,
        routine_name: str,
        metric: str,
        score: float,
        detail: dict,
    ) -> int:
        return self._execute(
            """
            INSERT INTO evaluation_scores (history_id, routine_name, metric, score, detail)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (history_id, routine_name, metric, score, detail),
        )

    def _execute(self, sql: str, params: tuple) -> int:
        import psycopg
        from psycopg.types.json import Json

        if not self.dsn:
            raise RuntimeError("DATABASE_URL ausente")
        values = tuple(Json(item) if isinstance(item, dict) else item for item in params)
        with psycopg.connect(self.dsn) as conn:
            if not self._ready:
                conn.execute(MIGRATION.read_text(encoding="utf-8"))
                self._ready = True
            row = conn.execute(sql, values).fetchone()
        if row is None:
            raise RuntimeError("insert sem retorno")
        return int(row[0])
