import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from billproof.config import get_settings
from billproof.db import init_db
from billproof.errors import AppError, get_request_id, set_request_id
from billproof.logging_config import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="BillProof API", version="0.1.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def assign_request_id(request: Request, call_next):
    set_request_id(uuid.uuid4().hex)
    response = await call_next(request)
    response.headers["X-Request-Id"] = get_request_id()
    # Every response here is per-case or live state. A CDN in front of this API
    # (Vercel's, in the hosted setup) will otherwise serve a stale bill to the
    # presentation screen, or replay a bill that was just cleared.
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=exc.envelope())


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])) or None
    err = AppError(
        "VALIDATION_ERROR",
        first.get("msg", "Invalid request"),
        status_code=422,
        field=field,
    )
    return JSONResponse(status_code=422, content=err.envelope())


from billproof.api.routes import (
    activity,
    analysis,
    bills,
    cases,
    health,
    hospitals,
    packets,
    screens,
)
from billproof.api.routes import (
    map as map_routes,
)

app.include_router(health.router)
app.include_router(hospitals.router)
app.include_router(cases.router)
app.include_router(bills.router)
app.include_router(analysis.router)
app.include_router(activity.router)
app.include_router(packets.router)
app.include_router(map_routes.router)
app.include_router(screens.router)
