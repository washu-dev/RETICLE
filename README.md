# RETICLE
Rationale Engine To Inform CRISPR List Entities — AI-powered platform for analyzing CRISPR screen results and discovering novel gene targets.

## Local development

Starts the FastAPI backend (`api/`, http://127.0.0.1:8000) and the React Native Web webapp (`webapp/`, http://localhost:3001) together. The webapp calls the API at `localhost:8000`.

### First-time setup

Requires **Python 3.11** (the API targets 3.11, matching the Docker image) and **Node.js**.

```bash
py -3.11 -m venv .venv   # if .venv doesn't exist yet
npm install              # installs the launcher (concurrently)
npm run setup            # installs API deps into .venv + webapp deps
```

### Run

```bash
npm run dev:all
```

On Windows you can instead **double-click `start-dev.bat`** in Explorer.

Both services run in one terminal with color-coded logs (`[api]`, `[webapp]`); the webapp opens in your browser automatically. If either service exits, the other is shut down too.

| Script | Does |
| --- | --- |
| `npm run dev:all` | Start API + webapp together |
| `npm run dev:api` | Start just the API |
| `npm run dev:webapp` | Start just the webapp |
| `npm run setup` | Install all dependencies |
