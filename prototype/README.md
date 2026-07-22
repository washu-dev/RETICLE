# RETICLE — Harmonization + Gene-Explorer Prototype

A self-contained **prototype** of the RETICLE pipeline and a local gene-explorer
web demo. It turns the BioGRID ORCS CRISPR screens into a single, directionally
consistent score axis, tags each screen by assay domain, and serves a website
that — for any gene — shows its fitness/stress behavior, a darkness rating, a
STRING interaction network colored by CRISPR behavior, and a RAG-grounded AI
reading.

> **This is a reference prototype, not the production system.** It runs on
> **SQLite + a stdlib Python web server + vanilla HTML/JS**, separate from the
> team's production stack (PostgreSQL warehouse + FastAPI + React webapp). The
> value here is the **science/logic** — harmonization rules, the directionality
> fixes, assay-domain stratification, darkness scoring, and the RAG — which can
> be ported into the production data layer.

## Layout

```
script/                 the pipeline (run in order, see below)
  paths.py              central path config (everything imports this)
  harmonize_scores.py   Phase 1: raw scores -> one loss-of-function axis + percentiles
  llm_metadata_extractor.py   rule-based screen labels incl. assay_domain (no LLM)
  directionality_mapper.py    LLM sign for genuinely ambiguous screens (needs WashU VPN)
  apply_directionality.py     apply the frozen LLM/anchor directions in place
  fix_directionality.py       registry fixes + essential-gene anchor (sign-inversion repair)
  validate_harmonization.py   sanity check (core-essential genes must be negative)
  compute_correlations.py     Phase 3: cross-screen correlation network (optional, heavy)
  external_sources.py   NCBI/PubMed + GO (MyGene) + STRING + darkness rating
web/
  app.py                local web server (queries the DB, calls the gateway)
  index.html            the gene-explorer UI
processed_data/
  directionality_overrides.json   frozen LLM directionality decisions (committed; small)
  reticle_master.db     the 2.1 GB SQLite DB — NOT committed; regenerate (below)
documentation/          full pipeline doc (index.html), process log, data-source map
```

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then fill in your WashU gateway secret (+ optional NCBI key)
```

The 2.1 GB database is **not** in git. Put the raw BioGRID ORCS screen files
under `raw_data/BIOGRID/` (human + mouse `.screen.tab.txt` + the metadata JSONs;
download from https://orcs.thebiogrid.org), then build it:

```bash
python3 script/harmonize_scores.py                          # build reticle_master.db
python3 script/llm_metadata_extractor.py                    # screen_metadata_curated (+ assay_domain)
python3 script/apply_directionality.py --anchor-resolve-conflicts   # apply frozen directions
python3 script/fix_directionality.py                        # registry + essential-gene sign repair
python3 script/validate_harmonization.py                    # should print PASS
```

Then run the site:

```bash
python3 web/app.py            # -> http://localhost:8000
```

## Notes on the external services

- **WashU AI gateway** (the "AI reading"): OAuth2 -> OpenAI-compatible gpt-5.
  WashU-only — you must be **on campus or the WashU VPN**, else every call is a
  403. The gene stats/charts and darkness work without it.
- **NCBI / GO / STRING**: public APIs, no VPN. Results are cached in
  `processed_data/external_cache.db` (regenerable). An `NCBI_API_KEY` is optional
  (3 req/s without, 10 with).
- The **frozen `directionality_overrides.json`** lets you reproduce the LLM sign
  decisions deterministically — you only need `directionality_mapper.py` (and the
  VPN) if you want to regenerate them.

## What can't be committed

`.env` (secrets), `reticle_master.db` (2.1 GB), `external_cache.db`, `raw_data/`,
and the bulk `processed_data/BIOGRID/` are all git-ignored. Regenerate the DB from
the raw data with the steps above, or host it in cloud storage (S3).

See `documentation/` for the full pipeline writeup, the data-source map, and the
process log (including the directionality sign-inversion audit & fix).
