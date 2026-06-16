# RETICLE Task #24 — FastAPI API Placeholder

Technical specification and application architecture.
Companion diagram: `architecture/24-fastapi-api.drawio`.

## 1. Scope

A minimal, production-shaped FastAPI service that stands up the `/api` surface on
AWS ECS Fargate so the webapp (Task #25) and CI/CD pipeline have a real target.
Two business endpoints plus an ECS health check. No database access in this task.

### Route reconciliation (decision)

Task #24 names `GET /greetings`; Task #25 calls `GET /api/greetings`. The webapp is
the consumer of record, and the CI/CD env (`ECS_*`, ALB health check) assumes the
service owns the `/api` surface. **All business routes are mounted under the `/api`
prefix.** Final contract:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | ECS/ALB liveness + readiness probe |
| GET | `/api/greetings` | Returns the welcome message |
| POST | `/api/login` | SSO placeholder (501 Not Implemented) |
| GET | `/api/docs`, `/api/openapi.json` | Swagger UI + schema |

If a bare `/greetings` is also desired, add a thin redirect later; do not duplicate
handlers. This is the single decision the developer must not re-derive.

## 2. Functional requirements (acceptance criteria)

- **FR-1 Greetings.** `GET /api/greetings` returns HTTP 200,
  `{"message": "Welcome to RETICLE"}`, `Content-Type: application/json`.
- **FR-2 Login placeholder.** `POST /api/login` accepts a JSON body and returns
  HTTP 501 with `{"detail": "SSO login not yet implemented", "code": "SSO_NOT_IMPLEMENTED"}`.
  The route, request model, and `AuthProvider` seam exist so SSO can be added without
  changing the route signature or the client contract.
- **FR-3 Health.** `GET /api/health` returns HTTP 200,
  `{"status": "ok", "service": "reticle-api", "version": "<git-sha or VERSION>"}`.
  Responds in under 100 ms with no external dependency calls (so a DB outage does
  not flap the ECS task).
- **FR-4 OpenAPI.** Swagger UI served at `/api/docs`; schema at `/api/openapi.json`.
  Every route is documented with summary, response model, and example.
- **FR-5 CORS.** Cross-origin `GET /api/greetings` from the configured webapp origin
  succeeds (preflight + actual). Unlisted origins are rejected.
- **FR-6 Errors.** Unhandled exceptions return a uniform JSON envelope (FR shape in §6),
  never a stack trace.

## 3. Non-functional requirements (measurable)

| ID | Category | Target |
|---|---|---|
| NFR-1 | Latency | p95 `/api/greetings` < 50 ms server time; `/api/health` < 20 ms |
| NFR-2 | Availability | Single Fargate task acceptable for placeholder; ALB health check fails task in ≤ 3 checks (30 s) and ECS replaces it |
| NFR-3 | Startup | Container ready (health 200) within 15 s of task start |
| NFR-4 | Security | No secrets in image/code; TLS terminated at ALB (ACM); bandit + Trivy HIGH/CRITICAL clean; CORS allowlist only |
| NFR-5 | Observability | One structured JSON log line per request (method, path, status, latency_ms, request_id) to stdout → CloudWatch `/ecs/reticle-api` |
| NFR-6 | Cost | Fargate 0.25 vCPU / 0.5 GB, 1 task ≈ low tens of USD/mo; ALB ≈ ~$16/mo; ECR/CloudWatch negligible at this volume. Order: **tens of USD/month** (ALB dominates) |
| NFR-7 | Image | Multi-stage build, non-root user, slim base; final image target < 200 MB |
| NFR-8 | Quality | ruff + mypy clean; pytest coverage ≥ 80% on `api/` |

> Cost note for the developer: the ALB is the cost floor. If a public endpoint is not
> required for the placeholder, a single Fargate task behind API Gateway HTTP API, or
> Fargate with a public IP, is cheaper. ALB is recommended only because the CI/CD
> already references an ECS service that conventionally sits behind one. Confirm with
> the user whether the ALB is wanted now or deferred.

## 4. Code layout (`/api`)

```
api/
  app/
    __init__.py
    main.py              # create_app() factory: app, middleware, router includes, exception handlers
    config.py            # Settings (pydantic-settings) — 12-factor env config
    logging_config.py    # structured JSON logging setup
    routers/
      health.py          # GET /api/health
      greetings.py       # GET /api/greetings
      auth.py            # POST /api/login -> AuthProvider
    schemas/
      greetings.py       # GreetingResponse
      auth.py            # LoginRequest, LoginResponse  (extra="forbid")
      errors.py          # ErrorResponse
    auth/
      provider.py        # AuthProvider ABC
      placeholder.py     # PlaceholderAuthProvider (raises NotImplemented -> 501)
      deps.py            # get_auth_provider() FastAPI dependency
  tests/
    test_health.py
    test_greetings.py
    test_login.py
    test_cors.py
  Dockerfile
  requirements.txt
  pyproject.toml         # ruff + mypy config
  .dockerignore
```

### SOLID mapping

- **SRP** — each router owns one resource; config, logging, auth live in their own modules.
- **OCP / DIP** — routes depend on the `AuthProvider` abstraction (`api/app/auth/provider.py`),
  injected via `Depends(get_auth_provider)`. Adding real SSO means writing a new
  `OidcAuthProvider` and swapping the binding in `deps.py` — no route edits.
- **ISP** — `AuthProvider` exposes only what auth needs (`authenticate(credentials)`),
  not a kitchen-sink interface.
- **LSP** — `PlaceholderAuthProvider` and the future real provider share the same
  contract; the placeholder satisfies it by raising a typed `NotImplementedAuthError`
  that the route maps to 501.

## 5. Authentication placeholder design

```python
# auth/provider.py
class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, credentials: LoginRequest) -> LoginResponse: ...

# auth/placeholder.py
class PlaceholderAuthProvider(AuthProvider):
    async def authenticate(self, credentials: LoginRequest) -> LoginResponse:
        raise NotImplementedAuthError("SSO login not yet implemented")
```

- `LoginRequest` is intentionally minimal and `extra="forbid"` so the eventual SSO
  shape (e.g. an OIDC authorization code / redirect) is an additive, reviewed change,
  not a silent one.
- Future SSO secrets (client ID/secret, issuer URL) come from **AWS Secrets Manager**,
  injected into the ECS task definition as environment variables — never baked into the
  image (12-factor III).
- The route returns a stable error `code` so the client can branch on it without
  parsing prose.

## 6. Error handling & logging

- Register exception handlers in `main.py`:
  - `RequestValidationError` → 422, `ErrorResponse{code:"VALIDATION_ERROR", detail, errors[]}`.
  - `NotImplementedAuthError` → 501, `code:"SSO_NOT_IMPLEMENTED"`.
  - `HTTPException` → its status, normalized to `ErrorResponse`.
  - `Exception` (catch-all) → 500, `code:"INTERNAL_ERROR"`, generic message; full
    traceback logged at ERROR, **never** returned to the client (OWASP A05/A09).
- `ErrorResponse` = `{ "code": str, "detail": str, "errors": list | null, "request_id": str }`.
- Logging: a middleware assigns/propagates an `X-Request-ID` (accept inbound or generate
  UUID4), emits one JSON line per request to stdout. ECS awslogs driver ships to
  CloudWatch `/ecs/reticle-api`. No request bodies or credentials are logged.

## 7. Dockerfile & requirements structure

`Dockerfile` (multi-stage, non-root, 12-factor IX disposability):

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
RUN useradd -m -u 10001 appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
ENV PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
USER appuser
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/api/health')" || exit 1
CMD ["sh","-c","uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
```

`requirements.txt` (pinned): `fastapi`, `uvicorn[standard]`, `pydantic`,
`pydantic-settings`, `python-json-logger`. Dev/CI tools (`ruff`, `mypy`, `pytest`,
`pytest-cov`, `httpx`, `bandit`) are installed by the workflow, not shipped in the image.

> Note the CI `build` job runs `mypy . --ignore-missing-imports` and `ruff check .`
> from `working-directory: api`, so `pyproject.toml` lives at `api/pyproject.toml`.
> The Dockerfile `HEALTHCHECK` is for local/`docker build` parity; in ECS the
> ALB target-group health check (`GET /api/health`) is authoritative.

## 8. OpenAPI / Swagger

- `FastAPI(title="RETICLE API", version=<VERSION>, docs_url="/api/docs", openapi_url="/api/openapi.json")`.
- Each route declares `response_model`, `status_code`, `summary`, and a `responses`
  example (including the 501/422/500 envelopes) so the generated schema is the contract
  the webapp codegen/devs read.

## 9. Config (12-factor)

`Settings` (pydantic-settings) reads from env only:

| Env var | Default | Purpose |
|---|---|---|
| `PORT` | `8080` | uvicorn bind port (matches Dockerfile/ECS task port mapping) |
| `CORS_ALLOWED_ORIGINS` | `""` | Comma-separated allowlist (webapp/CloudFront origin) |
| `LOG_LEVEL` | `INFO` | logging verbosity |
| `RETICLE_VERSION` | `dev` | surfaced in `/api/health` |

No config files in the image; all state externalized; process is stateless and
disposable (12-factor III, VI, IX).

## 10. OWASP Top 10 threat model

| Risk | Exposure here | Mitigation in this design |
|---|---|---|
| A01 Broken Access Control | `/api/login` stub; no authz yet | Placeholder returns 501; `AuthProvider` seam is the single point to add authz; no privileged routes exist yet |
| A02 Cryptographic Failures | Data in transit | TLS at ALB (ACM); CloudFront→ALB HTTPS; no secrets at rest in image |
| A03 Injection | JSON body on `/api/login` | Pydantic models with `extra="forbid"`; no SQL/shell in this task |
| A04 Insecure Design | Future SSO bolt-on | Explicit `AuthProvider` abstraction + forbid-extra request models prevent silent contract drift |
| A05 Security Misconfiguration | CORS, error verbosity, container user | CORS allowlist (no `*`); generic 500 body; non-root container; slim base; `docs` kept but no debug mode in prod |
| A06 Vulnerable Components | Python deps, base image | Pinned `requirements.txt`; Trivy fs scan + `bandit` gate HIGH/CRITICAL in CI |
| A07 Auth Failures | N/A yet | Deferred to SSO; placeholder cannot leak credentials |
| A08 Integrity Failures | Image supply chain | CI builds image, pushes immutable `:<git-sha>` tag to ECR; deploy only from `main` |
| A09 Logging/Monitoring Failures | Visibility | Structured per-request JSON logs + request_id to CloudWatch; no sensitive fields logged |
| A10 SSRF | None (no outbound fetch from user input) | No user-controlled URL fetching in scope |

## 11. Open questions for the user

1. **ALB now or later?** It is the dominant cost. Confirm whether the placeholder needs
   a public ALB or can run cheaper (API Gateway HTTP API / public-IP task) until real
   traffic arrives. The CI/CD already names an ECS service, so either works.
2. **Login request shape.** Any known SSO provider (WashU Shibboleth/OIDC?) so the
   placeholder `LoginRequest` can be shaped toward it now without over-committing.
