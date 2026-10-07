from contextlib import asynccontextmanager
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from cryptography.fernet import Fernet
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from app.clients.llm import LLMClient
from app.clients.obp import OBPClient
from app.clients.tavily import TavilyClient
from app.core.config import Settings, get_settings
from app.core.db import initialize_database
from app.core.errors import AppError, app_error_handler, error_body, http_error_handler, validation_error_handler
from app.core.logging import configure_logging, make_request_id, request_id_var
from app.core.limits import limiter
from app.routers import account, alerts, ai, auth, baseline, health, payments, transactions, users

logger = logging.getLogger(__name__)


async def rate_limit_handler(request: Request, _: RateLimitExceeded):
    return JSONResponse(error_body("RATE_LIMITED", "Too many requests. Please try again shortly.", 429), status_code=429, headers={"X-Request-ID": getattr(request.state, "request_id", "")})


def create_app(settings: Settings | None = None, *, db_override=None, http_override=None, llm_override=None) -> FastAPI:
    configured = settings or get_settings()
    upload_dir = Path(__file__).resolve().parents[1] / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        missing = configured.missing_required()
        if missing:
            raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
        if len(configured.jwt_secret.encode()) < 32:
            raise RuntimeError("JWT_SECRET must contain at least 32 bytes.")
        try:
            Fernet(configured.encryption_key.encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError("ENCRYPTION_KEY must be a valid Fernet key. Generate one with cryptography.fernet.Fernet.generate_key().") from exc
        db_client = None
        http = http_override or httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5))
        try:
            if db_override is not None:
                app.state.db = db_override
            else:
                db_client, app.state.db = await initialize_database(configured.mongo_uri, configured.mongo_db)
            app.state.db_client = db_client
            app.state.obp_http = http
            app.state.obp = OBPClient(http, configured)
            app.state.llm = llm_override or LLMClient(configured)
            app.state.tavily = TavilyClient(configured)
            yield
        finally:
            if db_client: db_client.close()
            if http_override is None: await http.aclose()

    app = FastAPI(title="Clari-Fi Backend", version="1.0.0", lifespan=lifespan)
    app.state.settings = configured
    app.state.upload_dir = str(upload_dir)
    app.state.limiter = limiter
    app.add_middleware(CORSMiddleware, allow_origins=configured.cors_origin_list, allow_credentials="*" not in configured.cors_origin_list, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"])
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    @app.middleware("http")
    async def request_security(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "")[:100] or make_request_id()
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        if int(request.headers.get("content-length", "0") or 0) > configured.request_body_limit:
            response = JSONResponse(error_body("REQUEST_TOO_LARGE", "Request body is too large.", 413), status_code=413)
        else:
            try: response = await call_next(request)
            except Exception:
                logger.exception("Unhandled request error")
                response = JSONResponse(error_body("INTERNAL_ERROR", "An unexpected error occurred.", 500), status_code=500)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        request_id_var.reset(token)
        return response

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(account.router)
    app.include_router(transactions.router)
    app.include_router(payments.router)
    app.include_router(baseline.router)
    app.include_router(alerts.router)
    app.include_router(ai.router)
    app.include_router(health.router)
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")
    return app


from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

app = create_app()
