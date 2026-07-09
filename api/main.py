import json
import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from routers.explorer import router as explorer_router
from routers.genes import router as genes_router
from routers.query import router as query_router

# Load environment variables from .env file early
load_dotenv()

logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    username: str
    password: str
    scopes: list[str] = []


class LoginResponse(BaseModel):
    access_token: str
    token_type: str


class GreetingsResponse(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    logger.info("RETICLE API starting")
    yield
    logger.info("RETICLE API shutting down")


app = FastAPI(
    title="RETICLE API",
    description="CRISPR screen analysis platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS. The webapp calls this API cross-origin (S3/CloudFront -> ECS) with a
# bearer token in the Authorization header, not cookies — so credentials are not
# needed, and disabling them keeps the wildcard-origin default valid and safe
# (allow_origins=["*"] WITH allow_credentials=True is the OWASP misconfiguration
# browsers reject). Lock origins down per environment via CORS_ALLOW_ORIGINS
# (comma-separated) once the CloudFront domain is known.
_cors_origins = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query_router)
app.include_router(genes_router)
app.include_router(explorer_router)


@app.get("/api/health", response_model=HealthResponse)
@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        service="reticle-api-server",
        version="0.1.0",
    )


@app.get("/api/greetings", response_model=GreetingsResponse)
async def get_greetings() -> GreetingsResponse:
    logger.info("GET /api/greetings called")
    return GreetingsResponse(message="Welcome to RETICLE")


@app.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    logger.info(f"POST /api/login called by user: {request.username}")

    if not request.username or not request.password:
        logger.warning(f"Login attempt with empty credentials from {request.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    placeholder_token = f"placeholder_token_for_{request.username}"
    logger.info(f"Login successful for user: {request.username}")

    return LoginResponse(
        access_token=placeholder_token,
        token_type="Bearer",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",  # nosec B104 — intentional for containerized deployment
        port=8000,
    )



