import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException

from modernize.api.schemas import HistoryResponse, ModernizeRequest, ModernizeResponse
from modernize.evaluation.runner import run_evaluation
from modernize.graph.builder import graph
from modernize.graph.state import empty_report
from modernize.persistence.history import HistoryRepository, PsycopgHistory
from modernize.pipeline import execute

logger = logging.getLogger(__name__)


def create_app(compiled_graph: Any, history_repo: HistoryRepository) -> FastAPI:
    app = FastAPI(
        title="Pipeline hibrida PL/pgSQL -> Python 3.14",
        description="Parsing e analise por regras, geracao por LLM, validacao estatica e persistencia.",
        version="0.2.0",
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/modernize", response_model=ModernizeResponse)
    async def modernize(body: ModernizeRequest) -> ModernizeResponse:
        try:
            result = await asyncio.to_thread(execute, compiled_graph, body.source_code, body.schema_ddl)
        except Exception as exc:
            # O grafo estourou antes de persistir (ex.: banco fora no no persist). Uma tentativa de gravar a falha.
            logger.exception("pipeline abortou antes de persistir")
            report = empty_report()
            report["parsing"]["error"] = f"pipeline abortou: {type(exc).__name__}: {exc}"
            try:
                history_id = await asyncio.to_thread(
                    history_repo.insert,
                    source_code=body.source_code,
                    generated_code=None,
                    report=report,
                    status="falha",
                )
            except Exception as persist_exc:
                raise HTTPException(status_code=500, detail="falha ao persistir a execucao") from persist_exc
            return ModernizeResponse(id=history_id, status="falha", generated_code=None, report=report)
        result_id = result.get("history_id")
        if result_id is None:
            raise HTTPException(status_code=500, detail="execucao sem historico")
        return ModernizeResponse(
            id=result_id,
            status=result["status"],
            generated_code=result.get("generated_code"),
            report=result["report"],
        )

    @app.get("/history/{history_id}", response_model=HistoryResponse)
    async def history(history_id: int) -> HistoryResponse:
        try:
            row = await asyncio.to_thread(history_repo.get, history_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="banco indisponivel") from exc
        if row is None:
            raise HTTPException(status_code=404, detail="execucao nao encontrada")
        return HistoryResponse.model_validate(row)

    @app.post("/evaluate")
    async def evaluate() -> dict:
        # O exportador do Langfuse envia em segundo plano; nenhum flush bloqueia a requisicao.
        return await asyncio.to_thread(run_evaluation, compiled_graph, history_repo)

    return app


app = create_app(graph, PsycopgHistory())
