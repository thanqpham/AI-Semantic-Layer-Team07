import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from src.api.auth import auth_router
from src.api.dashboard_routes import router as dashboard_router
from src.api.llm_settings_routes import router as llm_settings_router
from src.api.llm_settings_routes import use_account_llm
from src.api.organization_routes import router as organization_router
from src.api.relationship_review_routes import relationship_router
from src.api.review_routes import review_router
from src.api.routes import router
from src.api.sync_routes import sync_router
from src.config import get_settings
from src.observability.langfuse_tracing import shutdown_tracing
from src.services.rate_limiter import RateLimitMiddleware
from src.services.schema_cron_service import start_schema_cron_scheduler, stop_schema_cron_scheduler

# Configure application-wide logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)
    if settings.app_env != "test":
        start_schema_cron_scheduler()
    try:
        yield
    finally:
        stop_schema_cron_scheduler()
        await asyncio.to_thread(shutdown_tracing)
        logger.info("Shutting down %s...", settings.app_name)


app = FastAPI(
    title="AI Semantic Layer Agent",
    description="AI Agent xây dựng Semantic Layer & định nghĩa chỉ số thống nhất cho doanh nghiệp.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> Response:
    """Keep API keys out of settings validation responses."""
    if request.url.path.startswith("/api/v1/settings/llm"):
        errors = [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})
    return await request_validation_exception_handler(request, exc)


settings = get_settings()
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=86400,
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(organization_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(llm_settings_router, prefix="/api/v1")
app.include_router(router, prefix="/api/v1", dependencies=[Depends(use_account_llm)])
app.include_router(review_router, prefix="/api/v1", dependencies=[Depends(use_account_llm)])
app.include_router(relationship_router, prefix="/api/v1")
app.include_router(sync_router, prefix="/api/v1", dependencies=[Depends(use_account_llm)])


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
