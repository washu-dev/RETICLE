# RETICLE

**Rationale Engine To Inform CRISPR List Entities** — one calibrated lens over 2,157 published CRISPR screens.

📄 **[Project page →](https://washu-dev.github.io/RETICLE/)** · [final presentation](https://washu-dev.github.io/RETICLE/RETICLE_FINAL.html)

2,157 published CRISPR screens hold the causal evidence for what human genes do, and no two of them
are scored the same way — we found about 58 distinct score types, and the deposited files do not record
whether a larger number means a stronger effect or a weaker one. RETICLE harmonizes those screens onto a
single directionally consistent loss-of-function axis spanning 28.2M gene-level measurements, then ranks
which published screens probe biology like yours, builds a gene–gene co-essentiality network from screen
behaviour alone, and assembles a per-gene page from ten annotation sources with a grounded LLM reading.

Built in the Orvedahl Lab with DI2 Summer Corps, Washington University in St. Louis.

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
