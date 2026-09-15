from contextlib import asynccontextmanager
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .routes import router, seed_database

settings = get_settings()
settings.validate_runtime()
logger = logging.getLogger("vahana.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.environment.lower() == "development":
        seed_database()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed"})
    request_id = request.headers.get("x-request-id", str(uuid4()))
    started = perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    logger.info(
        "request_completed request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (perf_counter() - started) * 1000,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, __: Exception):
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> dict[str, str | bool]:
    object_storage_configured = (
        bool(settings.object_storage_bucket)
        or (
            settings.storage_backend == "supabase"
            and bool(
                settings.supabase_url
                and settings.supabase_service_role_key
                and settings.supabase_storage_bucket
            )
        )
    )
    return {
        "status": "ok",
        "service": "vahana-api",
        "environment": settings.environment,
        "database_configured": bool(settings.database_url),
        "storage_backend": settings.storage_backend,
        "object_storage_configured": object_storage_configured,
    }


app.include_router(router)
