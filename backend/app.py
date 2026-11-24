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
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import schemas
from .questions import Filters
from .service import Busy, NotFound, Service

import logging

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("backend")


class Problem(HTTPException):
    """An error with a `code` a program can read beside the sentence a person reads (backend/README.md, "Errors")."""

    def __init__(self, status: int, code: str, detail: str, question_id: str | None = None, retry_after: int | None = None):
        super().__init__(status, detail, headers={"Retry-After": str(retry_after)} if retry_after else None)
        self.code, self.question_id = code, question_id


CODES = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 422: "invalid_request", 503: "unavailable"}
QUESTION_LOG = ROOT / "data/interim/backend/questions.jsonl"
# The frontend's development server; the deployed frontend is served from the same origin behind the proxy.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def log_to_the_console() -> None:
    """The service's own lines (one per question, and failures) go to the console at INFO, where `docker compose
    logs backend` shows them. Without this they are dropped: uvicorn configures only its own loggers."""
    ours = logging.getLogger("backend")
    if not ours.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        ours.addHandler(handler)
    ours.setLevel(logging.INFO)


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
        kept = request.method == "GET" and response.status_code == 200 and request.url.path not in ("/v1/health", "/v1/ready") \
            and request.url.path.startswith("/v1/") and not request.url.path.startswith("/v1/admin/")
        response.headers["Cache-Control"] = "private, max-age=60" if kept else "no-store"
        return response

    # Every error has one shape: {"detail": a sentence, "code": a word, "question_id": when a question was logged}.
    # Registered on Starlette's class, which FastAPI's extends: the router's own 404 and 405 get the shape too.
    @app.exception_handler(StarletteHTTPException)
    async def problem(_request, error: StarletteHTTPException):
        body = {"detail": str(error.detail), "code": getattr(error, "code", None) or CODES.get(error.status_code, "error")}
        if getattr(error, "question_id", None):
            body["question_id"] = error.question_id
        return JSONResponse(body, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, error: RequestValidationError):
        first = error.errors()[0] if error.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        return JSONResponse({"detail": f"the request is not valid: {where}: {first.get('msg', '')}".strip(),
                             "code": "invalid_request",
                             "errors": [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
                                        for e in error.errors()]}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(_request, error: Exception):
        log.exception("unexpected error")
        body = {"detail": "something went wrong on the server; the team can find it in the server log", "code": "internal"}
        if getattr(error, "question_id", None):
            body["question_id"] = error.question_id
        return JSONResponse(body, status_code=500)

    @app.middleware("http")
    async def no_nul_bytes(request, call_next):
        """PostgreSQL text cannot hold a NUL byte: in a path or a filter it would end as a 500 from the store."""
        if "\x00" in request.url.path or "%00" in (request.url.query or ""):
            return JSONResponse({"detail": "the request holds a NUL character", "code": "invalid_request"}, status_code=422)
        return await call_next(request)

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

    @app.post("/v1/questions", response_model=schemas.AnswerOut, summary="Ask a question",
              responses={503: {"model": schemas.ProblemOut, "description": "`busy`: too many questions are waiting; "
                               "`model_unavailable`; `store_unavailable`. The question is logged with status `error`."}})
    def ask(body: schemas.QuestionIn):
        try:
            return current().ask(body.question.strip(), body.mode, body.lane)
        except Busy as busy:
            raise Problem(503, "busy", f"other questions are being answered ({busy}); try again in a moment",
                          busy.question_id, busy.retry_after) from None
        except httpx.HTTPError as error:
            raise Problem(503, "model_unavailable", f"the model endpoint did not answer ({type(error).__name__}); check "
                          f"GET /v1/ready and the model server", getattr(error, "question_id", None)) from None
        except Exception as error:
            # A store that drops while a question is being answered is the same kind of trouble: try again later.
            if type(error).__module__.split(".")[0] in ("psycopg", "neo4j"):
                raise Problem(503, "store_unavailable", f"a store did not answer ({type(error).__name__}); check "
                              f"GET /v1/ready", getattr(error, "question_id", None)) from None
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
        """Liveness: the process is up and its engine is loaded. It asks nothing of the stores or the model."""
        return current().health()

    @app.get("/v1/ready", response_model=schemas.Ready, summary="Whether a question could be answered now",
             responses={503: {"model": schemas.Ready}})
    def ready():
        """Readiness: asks the model endpoint and the question log, at most once every 15 seconds. 503 when either
        does not answer. This is what a monitor and the smoke test watch."""
        state_now = current().ready()
        return JSONResponse(state_now, status_code=200 if state_now["ready"] else 503)

    # ---- the question log, read side (D-65). Read-only. There is no login yet: the whole application sits behind
    # one shared password at the proxy, so anyone past it can read what every user typed.

    def filters(kind: str | None = Query(None, max_length=40, description="The frame's kind, e.g. lookup or cause"),
                status: schemas.LoggedStatus | None = Query(None), mode: schemas.Mode | None = Query(None),
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
                         offset: int = Query(0, ge=0, le=1_000_000)):
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

    log_to_the_console()

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
    question_log = PostgresQuestionLog(dsn) if dsn else JsonlQuestionLog(QUESTION_LOG)
    # A model call that hangs must not hold the one slot for long: the order is model call < wait for a turn <
    # the browser's own limit (frontend/src/api/client.ts). A slow machine raises all three.
    timeout = float(os.environ.get("BACKEND_MODEL_TIMEOUT") or 75)
    clients = {role: client_for(role, roles, timeout=timeout, cache_unparsed=False) for role in ("frame", "answer")}
    used = [c.endpoint for c in clients.values()] + ([embed] if embedding_answers else [])
    hosted = sorted({e.name for e in used if e.hosted or not on_our_network(e.base_url)})
    refuse_private_release(hosted, source, getattr(engine, "release", None))
    engine.warm()
    return Service(engine, clients["frame"], clients["answer"], question_log,
                   {role: roles[role] for role in ("frame", "answer")},
                   page_images=Path(os.environ["BACKEND_PAGE_IMAGES"]) if os.environ.get("BACKEND_PAGE_IMAGES") else None,
                   queue_seconds=float(os.environ.get("BACKEND_QUEUE_SECONDS") or 60),
                   max_waiting=int(os.environ.get("BACKEND_MAX_WAITING") or 8))


def on_our_network(url: str) -> bool:
    """Whether a model address is this machine or its private network: loopback, a private or carrier-grade address,
    or a bare name such as a compose service. Anything else is someone else's machine and counts as hosted, whatever
    the endpoints file says: `"hosted": false` on a public address must not get private text out (D-68)."""
    import ipaddress
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host.isdigit() or host.startswith("0x"):
            return False  # a public address written as one number is not a service name
        return host == "localhost" or "." not in host or host.endswith((".internal", ".local"))
    ours = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
    return address.is_loopback or any(address in ipaddress.ip_network(net) for net in ours
                                      if ipaddress.ip_network(net).version == address.version)


def refuse_private_release(hosted: list[str], source: str, release: str | None) -> None:
    """The hosted-endpoint boundary (specification §10.1, D-68), checked once at start: a hosted model may only be
    sent report packages someone has declared public, by name, in `BACKEND_PUBLIC_RELEASES`. The committed bundle
    that `BACKEND_SOURCE=files` reads is public data (docs/DATA_SOURCES.md). Raises when the loaded package is not
    on the list, so the service does not start."""
    if not hosted or source == "files":
        return
    public = {name.strip() for name in (os.environ.get("BACKEND_PUBLIC_RELEASES") or "").split(",") if name.strip()}
    if release not in public:
        raise PermissionError(
            f"the roles file sends questions and report text to hosted endpoint(s) {', '.join(hosted)}, and the loaded "
            f"package {release!r} is not declared public. If every report in it is public, name it in "
            f"BACKEND_PUBLIC_RELEASES (comma-separated); otherwise point the roles at a local model")


app = create_app()
