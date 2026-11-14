"""FastAPI entry point for MedTrack's local label demo and existing Android APIs."""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from starlette.concurrency import run_in_threadpool

from agent import LabelAgent, gemini_summarize
from label_corpus import DEFAULT_CORPUS
from label_retrieval import LabelIndex, LabelSnapshot, load_model, load_reranker
from medtrack_server import ApiError, DEMO_LABELS, DemoLabels, MedTrack, demo_select, live_service, load_local_config, route

DrugName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
LabelId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{1,80}$")]
Version = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,12}$")]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    session_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f-]{36}$")] | None = None


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class LabelQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Question
    mode: Literal["keyword", "hybrid", "rerank"] = "keyword"
    drug_name: DrugName | None = None
    label_id: LabelId | None = None
    version: Version | None = None

    @model_validator(mode="after")
    def choose_one_label_scope(self):
        if self.drug_name is not None and self.label_id is None and self.version is None:
            return self
        if self.drug_name is None and self.label_id is not None and self.version is not None:
            return self
        raise ValueError("Provide either a drug name or a label ID and version.")


def build_index():
    demo = os.getenv("MEDTRACK_SYNTHETIC_LABELS") == "1"
    path = Path(os.getenv("MEDTRACK_CORPUS", str(DEFAULT_CORPUS)))
    records = DEMO_LABELS if demo else json.loads(path.read_text(encoding="utf-8"))["results"]
    index = LabelIndex(LabelSnapshot(records, public=not demo), load_model(), load_reranker())
    index.prepare_vectors()
    return index


def create_app(index=None, legacy=None, agent=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.index = index or await run_in_threadpool(build_index)
        app.state.agent = agent or LabelAgent(app.state.index, summarize=gemini_summarize)
        if legacy is not None:
            app.state.legacy = legacy
        elif os.getenv("MEDTRACK_SYNTHETIC_LABELS") == "1":
            app.state.legacy = MedTrack(DemoLabels(), demo_select, "demo")
        else:
            load_local_config()
            app.state.legacy = live_service()
        try:
            yield
        finally:
            if index is None:
                app.state.index.db.close()

    app = FastAPI(title="MedTrack label search and question answering", version="1.0", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError):
        return JSONResponse(error.payload, status_code=error.status)

    @app.get("/health")
    def health(request: Request):
        index = request.app.state.index
        return {"status": "ok", "labels": len(index.snapshot.records), "passages": len(index.passages),
                "corpus": "openFDA snapshot" if index.snapshot.public else "fictional demo"}

    @app.get("/v1/labels")
    def labels(request: Request, q: Annotated[str, Query(min_length=1, max_length=80)]):
        return request.app.state.index.catalog.search(q)

    @app.post("/v1/answer")
    def answer(request: Request, question: LabelQuestion):
        return request.app.state.index.answer(**question.model_dump())

    @app.post("/v1/agent/chat")
    def agent_chat(request: Request, body: AgentMessage):
        """Server-sent events: session, tool_call, tool_result, then answer (or error)."""
        token = request.headers.get("authorization")
        steps = request.app.state.agent.run(body.message, body.session_id, token)

        def stream():
            try:
                for event, data in steps:
                    yield sse(event, data)
            except ApiError as error:
                yield sse("error", error.payload)
            yield sse("done", {})

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    @app.get("/labels", include_in_schema=False)
    def legacy_labels(request: Request, q: str = ""):
        return request.app.state.legacy.search(q)

    async def dispatch_legacy(request):
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Expected a JSON object.")
        return await run_in_threadpool(route, request.app.state.legacy, "POST", request.url.path, body)

    @app.post("/answer", include_in_schema=False)
    async def legacy_answer(request: Request):
        return await dispatch_legacy(request)

    @app.post("/clinician/insights", include_in_schema=False)
    async def clinician_insights(request: Request):
        return await dispatch_legacy(request)

    return app


app = create_app()
