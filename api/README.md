# RETICLE API

FastAPI backend for the RETICLE web application. Exposes endpoints for multi-gene CRISPR screen queries and dark-gene detail lookups. Currently backed by a mock data service; designed as a clean seam so real AWS RDS queries can be swapped in without touching any router or frontend code.

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
    ├── mock_data_service.py # Current implementation — returns static mock data
    └── db_service.py        # DB access layer (env-based SQLite / AWS RDS switching)
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

---

## Code quality

```bash
ruff check .       # lint
mypy main.py       # type check entry point
```
