import asyncio

from fastapi import FastAPI, HTTPException

from modernize.api.schemas import ModernizeRequest, ModernizeResponse
from modernize.evaluation.runner import run_evaluation
from modernize.graph.builder import graph
from modernize.graph.state import empty_report, initial_state
from modernize.persistence.history import PsycopgHistory

repo = PsycopgHistory()


def create_app(compiled_graph, history_repo) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/modernize", response_model=ModernizeResponse)
    async def modernize(body: ModernizeRequest) -> ModernizeResponse:
        try:
            result = await asyncio.to_thread(
                compiled_graph.invoke,
                initial_state(body.source_code, body.schema_ddl),
            )
        except Exception as exc:
            try:
                history_id = history_repo.insert(
                    source_code=body.source_code,
                    generated_code=None,
                    report=empty_report(),
                    status="falha",
                )
            except Exception as persist_exc:
                raise HTTPException(status_code=500, detail="falha ao persistir a execucao") from persist_exc
            report = empty_report()
            report["parsing"]["error"] = str(exc)
            return ModernizeResponse(
                id=history_id,
                status="falha",
                generated_code=None,
                report=report,
            )
        if result.get("history_id") is None:
            raise HTTPException(status_code=500, detail="execucao sem historico")
        return ModernizeResponse(
            id=result["history_id"],
            status=result["status"],
            generated_code=result.get("generated_code"),
            report=result["report"],
        )

    @app.post("/evaluate")
    async def evaluate() -> dict:
        return await asyncio.to_thread(run_evaluation, compiled_graph, history_repo)

    return app


app = create_app(graph, repo)
