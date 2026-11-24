"""The read-path API (specification §7.5).

    uvicorn backend.app:app --host 127.0.0.1 --port 8000        # then http://127.0.0.1:8000/docs

`create_app(service)` builds the application around a `Service`, so tests pass one with a small engine and stand-in
models. `app` is the real one: the engine loaded from this machine's files, the models of the roles file, and the
question log under ignored `data/interim/backend/`.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import os
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Path as PathParam, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import schemas
from .questions import Filters
from .service import NotFound, Service

ROOT = Path(__file__).resolve().parents[1]
QUESTION_LOG = ROOT / "data/interim/backend/questions.jsonl"
# The frontend's development server; the deployed frontend is served from the same origin behind the proxy.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app(service: Service | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # A deployment on the stores must not start half-working: build the service now, so a wrong address or
        # password stops the server with its error. On files the service is still built at the first request.
        if os.environ.get("BACKEND_SOURCE") == "stores" or os.environ.get("BACKEND_DSN"):
            current()
        yield

    app = FastAPI(lifespan=lifespan, title="Drilling reports GraphRAG: read path", version="0.1.0",
                  description="Ask a question about the loaded drilling reports and see the answer, the lanes that "
                              "gave its evidence, its citations and how it was reached. Specification §7.5.")
    app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("BACKEND_CORS_ORIGINS", ",".join(DEV_ORIGINS)).split(","),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    # An answer with its evidence is tens of kilobytes of JSON; compressed it is a fifth of that.
    app.add_middleware(GZipMiddleware, minimum_size=2048)

    @app.middleware("http")
    async def caching(request, call_next):
        """Reads change only when a release is loaded, so a browser may keep them for a minute. Answers, feedback,
        health and the question log are never kept."""
        response = await call_next(request)
        if request.url.path.endswith("/image") and response.status_code == 200:
            # A page image changes only when its report is rendered again.
            response.headers["Cache-Control"] = "private, max-age=86400"
            return response
        kept = request.method == "GET" and response.status_code == 200 and request.url.path != "/v1/health" \
            and request.url.path.startswith("/v1/") and not request.url.path.startswith("/v1/admin/")
        response.headers["Cache-Control"] = "private, max-age=60" if kept else "no-store"
        return response

    state: dict[str, Service] = {"service": service} if service else {}

    def current() -> Service:
        if "service" not in state:
            state["service"] = default_service()
        return state["service"]

    def found(call):
        try:
            return call()
        except NotFound as missing:
            raise HTTPException(404, f"not found: {missing}") from None

    @app.post("/v1/questions", response_model=schemas.AnswerOut, summary="Ask a question")
    def ask(body: schemas.QuestionIn):
        try:
            return current().ask(body.question.strip(), body.mode, body.lane)
        except httpx.HTTPError as error:
            raise HTTPException(503, f"the model endpoint did not answer ({type(error).__name__}); check GET /v1/health "
                                     f"and the model server") from None
        except Exception as error:
            # A store that drops while a question is being answered is the same kind of trouble: try again later.
            if type(error).__module__.split(".")[0] in ("psycopg", "neo4j"):
                raise HTTPException(503, f"a store did not answer ({type(error).__name__}); check GET /v1/health") from None
            raise

    @app.post("/v1/questions/{question_id}/feedback", response_model=schemas.FeedbackOut, summary="Mark an answer right or wrong")
    def feedback(question_id: str, body: schemas.FeedbackIn):
        return found(lambda: current().feedback(question_id, body.verdict, body.comment))

    # Chunk and file IDs contain "#" (K1 version 0) or ":" (version 1); a client percent-encodes them in the path.
    @app.get("/v1/chunks/{chunk_id:path}", response_model=schemas.ChunkOut, summary="One chunk")
    def chunk(chunk_id: str):
        return found(lambda: current().chunk(chunk_id))

    @app.get("/v1/files", response_model=list[schemas.FileOut], summary="The loaded reports")
    def files():
        return current().files()

    @app.get("/v1/files/{file_id}/pages/{page}", response_model=schemas.PageOut, summary="One page of a report, as its chunks")
    def page(file_id: str, page: int):
        return found(lambda: current().page(file_id, page))

    @app.get("/v1/files/{file_id}/pages/{page}/image", response_class=FileResponse, summary="One page of a report, as an image",
             responses={200: {"content": {"image/png": {}}}})
    def page_image(file_id: str, page: int = PathParam(ge=1)):
        return FileResponse(found(lambda: current().page_image(file_id, page)), media_type="image/png")

    @app.get("/v1/wells", response_model=list[schemas.WellSummary], summary="The wells")
    def wells():
        return current().wells()

    @app.get("/v1/wells/{well_id}", response_model=schemas.WellOut,
             summary="One well's facts in groups, its documents, report days and totals")
    def well(well_id: str):
        return found(lambda: current().well(well_id))

    @app.get("/v1/wells/{well_id}/events", response_model=list[schemas.EventOut], summary="A well's events between two dates")
    def events(well_id: str, date_from: date | None = Query(None), date_to: date | None = Query(None)):
        return found(lambda: current().events(well_id, date_from and date_from.isoformat(), date_to and date_to.isoformat()))

    @app.get("/v1/health", response_model=schemas.Health, summary="What is loaded and which models serve")
    def health():
        return current().health()

    # ---- the question log, read side (D-65). Read-only. There is no login yet: the whole application sits behind
    # one shared password at the proxy, so anyone past it can read what every user typed.

    def filters(kind: str | None = Query(None, max_length=40, description="The frame's kind, e.g. lookup or cause"),
                status: schemas.Status | None = Query(None), mode: schemas.Mode | None = Query(None),
                verdict: Literal["right", "wrong", "none"] | None = Query(
                    None, description="The latest mark; none: not marked"),
                date_from: date | None = Query(None, description="Asked on or after this day (UTC)"),
                date_to: date | None = Query(None, description="Asked on or before this day (UTC)"),
                q: str | None = Query(None, max_length=200, description="Text in the question, ignoring case"),
                ids: list[str] = Query([], max_length=500, description="Only these question IDs")) -> Filters:
        return Filters(kind=kind or None, status=status, mode=mode, verdict=verdict,
                       date_from=date_from and date_from.isoformat(), date_to=date_to and date_to.isoformat(),
                       text=(q or "").strip() or None, ids=tuple(ids))

    ADMIN = "No login yet: the application sits behind one shared password at the proxy. Read-only."

    @app.get("/v1/admin/questions", response_model=schemas.QuestionPage, tags=["admin"],
             summary="Logged questions, newest first, with their feedback", description=ADMIN)
    def logged_questions(chosen: Filters = Depends(filters), limit: int = Query(50, ge=1, le=200),
                         offset: int = Query(0, ge=0)):
        return current().logged_questions(chosen, limit, offset)

    @app.get("/v1/admin/questions/counts", response_model=schemas.QuestionCounts, tags=["admin"],
             summary="Logged questions counted by kind, status and verdict", description=ADMIN)
    def question_counts(chosen: Filters = Depends(filters)):
        return current().question_counts(chosen)

    @app.get("/v1/admin/questions/export", response_model=schemas.QuestionSetFile, tags=["admin"],
             summary="Selected questions as a question file for graphrag.coordinator, gold left empty",
             description=f"{ADMIN} Selects by `ids` or by the filters; every matching question, oldest first.")
    def export_questions(chosen: Filters = Depends(filters),
                         expected_lane: Literal["end_of_well", "daily", "events", "reasoning"] | None = Query(
                             None, description="Written into the file only when given")):
        body = current().export_questions(chosen, expected_lane)
        # Returned as it is: a null expected_lane must be absent from the file, not null (graphrag.coordinator).
        return JSONResponse(body, headers={
            "Content-Disposition": f'attachment; filename="collected_{body["collected"]["on"]}.json"'})

    @app.get("/v1/admin/questions/{question_id}", response_model=schemas.LoggedQuestionDetail, tags=["admin"],
             summary="One logged question with its full stored record", description=ADMIN)
    def logged_question(question_id: str):
        return found(lambda: current().logged_question(question_id))

    return app


def default_service() -> Service:
    """The service, configured by the environment (backend/README.md):

    - `BACKEND_SOURCE=stores`: the engine reads the K1 release in PostgreSQL (`BACKEND_DSN`, and `BACKEND_RELEASE`
      when the store holds several) and the graph in Neo4j (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`).
      Unset or `files`: this machine's files.
    - `BACKEND_DSN` set: the question log is PostgreSQL's; unset: a file under ignored `data/interim/backend/`.

    A store that is configured but does not answer raises here; nothing falls back to files. Questions naming several
    wells are searched per well: with BM25 alone when the embedding server does not answer at start; else fused with
    the vectors, searched in memory on files and in PostgreSQL on the stores, where the release must have all its
    vectors (graphrag.stores.choose_multi_well_retriever). The choice is made here once (`Engine.retrieval`)."""
    from graphrag.client import client_for, load_endpoints, load_roles
    from graphrag.lanes import Engine

    from .questions import JsonlQuestionLog, PostgresQuestionLog
    source, dsn = os.environ.get("BACKEND_SOURCE") or "files", os.environ.get("BACKEND_DSN")
    if source not in ("files", "stores"):
        raise ValueError(f"BACKEND_SOURCE is {source!r}; use 'files' or 'stores'")
    roles = load_roles()
    embed = load_endpoints()[roles["embed"]["endpoint"]]
    try:
        httpx.get(f"{embed.base_url}/models", timeout=2.0).raise_for_status()
        embedding_answers = True
    except httpx.HTTPError:
        embedding_answers = False
    if source == "stores":
        from graphrag.stores import engine_from_stores
        if not dsn:
            raise ValueError("BACKEND_SOURCE=stores needs BACKEND_DSN, the PostgreSQL holding the K1 release")
        # The local stores' defaults (platform/docker-compose.yml); a server sets its own.
        engine = engine_from_stores(dsn, os.environ.get("NEO4J_URI") or "bolt://127.0.0.1:7687",
                                    os.environ.get("NEO4J_USER") or "neo4j", os.environ.get("NEO4J_PASSWORD") or "platform-dev",
                                    release=os.environ.get("BACKEND_RELEASE") or None, embed_model=roles["embed"]["model"],
                                    embedding_answers=embedding_answers)
    else:
        engine = Engine.load(**({} if embedding_answers else {"multi_well_retriever": "perwell:bm25"}))
    log = PostgresQuestionLog(dsn) if dsn else JsonlQuestionLog(QUESTION_LOG)
    return Service(engine, client_for("frame", roles), client_for("answer", roles), log,
                   {role: roles[role] for role in ("frame", "answer")},
                   page_images=Path(os.environ["BACKEND_PAGE_IMAGES"]) if os.environ.get("BACKEND_PAGE_IMAGES") else None)


app = create_app()
