"""HTTP surface for the gateway (hop ②). Run: uvicorn medsync_agent.api:app --port 8000"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.memory import InMemorySaver

from . import experiment
from .external import HttpExternal
from .graph import StepRunner, build_graph
from .models import ActionRequest, Outcome
from .pharmacist import RagPharmacist
from .tool_ledger import InMemoryToolLedger, PostgresToolLedger


def runner_from_env() -> tuple[StepRunner, Any, experiment.BaselineRunner]:
    external = HttpExternal(os.environ.get("MEDSYNC_EXTERNAL_URL", "http://127.0.0.1:9000"),
                            float(os.environ.get("MEDSYNC_EXTERNAL_TIMEOUT_S", "5")))
    attempts = experiment.Attempts()
    baseline = experiment.BaselineRunner(external, attempts)
    rag_url = os.environ.get("MEDSYNC_RAG_URL")
    pharmacist = RagPharmacist(rag_url, float(os.environ.get("MEDSYNC_RAG_TIMEOUT_S", "60"))) if rag_url else None
    dsn = os.environ.get("MEDSYNC_PG_DSN")
    if not dsn:
        graph = build_graph(InMemoryToolLedger(), external, InMemorySaver(), attempts=attempts, pharmacist=pharmacist)
        return StepRunner(graph), None, baseline
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(dsn, max_size=10, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    graph = build_graph(PostgresToolLedger(pool), external, checkpointer, attempts=attempts, pharmacist=pharmacist)
    return StepRunner(graph), pool, baseline


def create_app(runner: StepRunner | None = None, baseline: experiment.BaselineRunner | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = None
        app.state.runner, app.state.baseline = runner, baseline
        if runner is None:
            app.state.runner, pool, app.state.baseline = runner_from_env()
        yield
        if pool is not None:
            pool.close()

    app = FastAPI(title="MedSync agent", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/v1/actions/run", response_model=Outcome)
    def run(body: dict[str, Any]) -> Outcome:
        request = ActionRequest.model_validate(body)
        mode = request.experiment_mode
        if mode is not None:
            if not experiment.enabled() or mode not in experiment.MODES:
                raise HTTPException(400, "experiment modes are disabled")
            if mode != "full":
                return app.state.baseline.run(request)
        return app.state.runner.run(request)

    @app.post("/v1/actions/{step_key}/resume", response_model=Outcome)
    def resume(step_key: str, body: dict[str, Any]) -> Outcome:
        account_id = body.pop("account_id", None)
        if not account_id:
            raise HTTPException(400, "account_id is required")
        try:
            return app.state.runner.resume(account_id, step_key, body)
        except LookupError as error:
            raise HTTPException(409, str(error)) from error

    return app


app = create_app()
