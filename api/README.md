# RETICLE API

FastAPI backend for the RETICLE web application. Exposes endpoints for multi-gene CRISPR screen queries and dark-gene detail lookups. Runs on a **dual backend**: mock data when `AWS_DB_HOST` is unset, and live queries against the team's AWS RDS (`reticle` schema) when it is set. The switch is a clean seam — neither the routers nor the frontend change between modes.

---

## Status

| Area | State | Notes |
|---|---|---|
| Mock-data API | ✅ Working | 5 endpoints, 26/26 unit tests pass (`test_main.py`) |
| Live RDS backend | ✅ **Validated** | `.env` loads via `load_dotenv()`, `psycopg2-binary` installed; **27/27 live integration tests pass** against real RDS (`test_db_live.py`) |
| `POST /api/login` | ⚠️ Placeholder | Returns a fake bearer token; no real auth/JWT/scope enforcement |
| `POST /api/query` options | ⚠️ Ignored | `organism`, `modalities`, `algorithm`, `pathway_analysis` are accepted but not yet applied |
| Gene hypotheses | ⚠️ Partial | Curated for CCDC6 & FAM114A1; other genes get an auto-generated fallback |

**Performance note:** the live RDS integration suite takes ~9.5 min for 27 tests (~20s/query). The same queries back `/api/query`, so real endpoint latency against RDS is a known watch-item — likely large tables / missing indexes on `harmonized_scores`.

---

## Setup

**Requirements:** Python 3.11+

```bash
cd api

# Runtime only (what the Docker container installs)
pip install -r requirements.txt

# Dev tools — includes pytest, ruff, mypy on top of runtime deps
pip install -r requirements-dev.txt
```

### Environment (optional)

To connect to the team's AWS RDS instead of returning mock data, copy `.env.example` to `.env` and fill in the RDS credentials:

```bash
cp .env.example .env
# edit .env with AWS_DB_HOST, AWS_DB_PORT, AWS_DB_USER, AWS_DB_PASSWORD, AWS_DB_NAME
```

Leave `AWS_DB_HOST` blank to run fully on mock data (no DB needed).

---

## Running the server

```bash
uvicorn main:app --reload
```

Server starts at `http://localhost:8000`. The `--reload` flag hot-reloads on file changes.

Interactive API docs (Swagger UI): **`http://localhost:8000/api/docs`**

---

## Endpoints

### `GET /api/health`
Health check. Returns server status and version.

```json
{ "status": "healthy", "service": "reticle-api-server", "version": "0.1.0" }
```

---

### `GET /api/greetings`
Basic greeting. Used to verify the server is reachable from the frontend.

```json
{ "message": "Welcome to RETICLE" }
```

---

### `POST /api/login`
Placeholder auth endpoint. Returns a token for the given username.

**Request body:**
```json
{ "username": "string", "password": "string", "scopes": [] }
```

**Response:**
```json
{ "access_token": "placeholder_token_for_<username>", "token_type": "Bearer" }
```

Returns `401` if username or password is empty.

---

### `POST /api/query`
Core endpoint. Takes a list of genes from the user's CRISPR screen and returns matched screens, dark-gene candidates, and a graph structure for the explorer tab.

**Request body:**
```json
{
  "genes": [
    { "symbol": "TP53", "score": -1.2 },
    { "symbol": "ATG5", "score": -0.8 }
  ],
  "options": {}
}
```

**Response fields (all camelCase):**

| Field | Type | Description |
|---|---|---|
| `matchedScreens` | array | Top BioGRID screens ranked by Spearman ρ |
| `darkGenes` | array | Dark-matter gene candidates with darkness + correlation scores |
| `graphElements` | object | Cytoscape-ready `{ nodes, edges }` for the graph explorer |
| `stats` | object | Summary counts (screens compared, significant matches, query gene count) |

Each `matchedScreen` includes: `biogridId`, `name`, `citation`, `pmid`, `organism`, `modality`, `cellType`, `rho`, `fdr`, `directionality`, `sharedGenes`, `totalGenes`.

Each `darkGene` includes: `symbol`, `darkScore`, `correlation`, `pubs`, `screens`, `isBright`.

Returns `422` if the request body is malformed.

---

### `GET /api/genes/{symbol}`
Returns detailed information for a single gene — used to populate the slide-over panel when a user clicks a gene in the dark-gene scatter plot.

Symbol lookup is case-insensitive (`ccdc6` and `CCDC6` return the same result).

**Response fields (all camelCase):**

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Canonical gene symbol |
| `darkScore` | number | Darkness score 0–10 |
| `hypothesis` | string | AI-generated hypothesis (null if not curated) |
| `mechanisticContext` | string | Mechanistic context paragraph |
| `citations` | array | Supporting publications `{ pmid, text }` |
| `suggestedValidation` | string | Recommended next experimental step |
| `stringInteractors` | array | STRING protein interactions `{ symbol, combinedScore, direction }` |
| `combinedScore` | number | Aggregate STRING combined score |

Returns `404` if the gene symbol is not in the reference set.

---

## Architecture

```
api/
├── main.py                  # FastAPI app, CORS, router registration
├── routers/
│   ├── query.py             # POST /api/query
│   └── genes.py             # GET /api/genes/{symbol}
├── models/
│   ├── base.py              # CamelModel base (camelCase JSON serialization)
│   ├── query.py             # QueryRequest, QueryResponse, MatchedScreen, DarkGene, ...
│   └── gene.py              # GeneDetail, Citation, StringInteractor
└── services/
    ├── mock_data_service.py # run_query / get_gene_detail — mock data or live RDS SQL by backend
    └── db_service.py        # DB access layer; load_dotenv() + env-based SQLite / AWS RDS switching
```

**Replacing mock data with real DB queries:** edit `services/mock_data_service.py`. The two async functions `run_query(request)` and `get_gene_detail(symbol)` are the seam — swap their bodies to call `db_service.db_fetchall()` against the `reticle` schema on RDS. The routers and frontend do not need to change.

All response models use camelCase aliases (`alias_generator=to_camel`) so the JSON matches what the React frontend expects.

---

## Testing

Tests use `pytest` with FastAPI's `TestClient` — no running server needed.

```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=. --cov-report=term-missing

# Run a specific test class
pytest tests/test_main.py::TestQuery -v
pytest tests/test_main.py::TestGenes -v
```

### Test coverage

| Class | What it checks |
|---|---|
| `TestHealth` | `/api/health` status and fields |
| `TestGreetings` | `/api/greetings` response |
| `TestLogin` | Success, scopes, empty credentials (401), missing field (422) |
| `TestQuery` | 200 status, response shape, camelCase fields, matched screens/dark genes/graph structure, stats, empty gene list, malformed body (422) |
| `TestGenes` | Known gene (200), response fields, citations, STRING interactors, second rationale gene, gene without rationale, case-insensitive lookup, unknown gene (404), camelCase fields |

### Live DB integration tests

`tests/test_db_live.py` exercises the real RDS backend. It **auto-skips** when `AWS_DB_HOST` is unset (so CI stays green without DB access) and runs when `api/.env` is filled in.

```bash
# From api/ so load_dotenv() finds api/.env
pytest tests/test_db_live.py -v
```

**Last validated:** 2026-07-02 — **27/27 passing** against live RDS in 562s (~9m22s).

| Class | What it checks (against live `reticle` schema) |
|---|---|
| `TestConnection` | DB reachable, expected schemas present |
| `TestRunQuery` | Matched screens, dark genes, dark-score formula, graph node/edge integrity, query-gene exclusion, unknown-gene handling, screen ordering, UUID query IDs |
| `TestGetGeneDetail` | Known/unknown lookups, case-insensitivity, citations, bright-vs-dark classification |
| `TestDbFetchall` | Row access, case-insensitive keys, parameterized queries, empty results |

Requires `psycopg2-binary` (declared in `pyproject.toml`) and valid RDS credentials in `api/.env`.

---

## Code quality

```bash
ruff check .       # lint
mypy main.py       # type check entry point
```
