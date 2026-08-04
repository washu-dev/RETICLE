# Running RETICLE's three data jobs on WashU RIS (Compute2 / SLURM)

RIS **Compute2** is a **SLURM** cluster that runs jobs in a Python **venv** (not
Docker). These three jobs reuse the same pattern as the existing `slurm/`
scripts (`reticle-staging.sh`, `reticle-etl.sh`).

| Job | Cadence | Script | Database? |
|---|---|---|---|
| PubMed / NCBI literature refresh | **recurring** | `reticle-pubmed-download.sh` | no |
| BioGRID ORCS download | infrequent | `reticle-biogrid-download.sh` | no (then hand off to staging/ETL) |
| Score harmonization | infrequent | `reticle-harmonization.sh` | only if `MIGRATE=1` |

The Python pipelines under `scripts/` and `prototype/script/` are reused as-is;
the only new Python is `scripts/download_ncbi_bulk.py` and
`scripts/download_biogrid_orcs.py`.

---

## 0. Log in and get these scripts onto RIS

```bash
ssh <wustlkey>@c2-login-001.ris.wustl.edu     # WashU VPN + Duo required
```
The repo is already cloned at `/storage3/fs1/aorvedahl-RETICLE/Active/RETICLE`.
Get this branch's new scripts there (after it's pushed to GitHub):
```bash
cd /storage3/fs1/aorvedahl-RETICLE/Active/RETICLE
git config --global --add safe.directory "$PWD"   # clears the "dubious ownership" warning
git fetch origin && git checkout feature/ris-scripts && git pull
```
(Or clone your own copy in `$HOME` if you prefer not to touch the shared clone.)

`RETICLE_DATA` defaults to `/storage3/fs1/aorvedahl-RETICLE/Active/data`, which
already holds `ncbi/`, `kb/`, `BIOGRID-ORCS-2.0.18/`, `processed_data/`, etc.

**Confirm the partition name once** (scripts default to `general-cpu`):
```bash
sinfo -o "%P"     # lists partitions; if general-cpu isn't there, pass --partition=<name>
```

`.pgpass` is only needed for database work (harmonization `MIGRATE=1`, and the
existing staging/ETL scripts):
```
your.rds.host:5432:reticle_biogrid:reticle_admin:YOUR_PASSWORD   # then chmod 600 ~/.pgpass
```

---

## 1. PubMed refresh (recurring — do this first)

No database, safest job. Downloads NCBI files → rebuilds `kb_gene` → rebuilds
`kb_gene_pubmed`.
```bash
sbatch slurm/reticle-pubmed-download.sh
TAXIDS=9606 sbatch slurm/reticle-pubmed-download.sh     # human only
```

### Make it recurring (cron on a WashU-network host)
RIS has no built-in scheduler. Put one line on an always-on machine inside the
WashU network that can `ssh` to RIS, e.g. monthly:
```cron
0 3 1 * *  ssh <wustlkey>@c2-login-001.ris.wustl.edu \
             'cd /storage3/fs1/aorvedahl-RETICLE/Active/RETICLE && sbatch slurm/reticle-pubmed-download.sh'
```
It's idempotent — `download_ncbi_bulk.py` skips files that haven't changed.

---

## 2. BioGRID upload (infrequent)

Step A — download the dumps (this script):
```bash
sbatch slurm/reticle-biogrid-download.sh                                # latest, human+mouse
RELEASE=2.0.18 ORGANISMS="homo_sapiens" sbatch slurm/reticle-biogrid-download.sh
```
Step B — stage + ETL with the **existing** scripts (the download script prints
the exact commands, including the `version_id`):
```bash
DATA_DIR=$RETICLE_DATA/BIOGRID-ORCS-2.0.18 sbatch slurm/reticle-staging.sh homo_sapiens
VERSION_ID=<id from staging log> sbatch slurm/reticle-etl.sh
```
Notes:
- `screen_metadata_<organism>.json` (ORCS webservice + access key) is **not**
  auto-downloaded — put it in the `DATA_DIR` before staging.
- First run: `python3 scripts/download_biogrid_orcs.py --list` to confirm the
  live ORCS release layout.

---

## 3. Harmonization (infrequent, heaviest)

```bash
sbatch slurm/reticle-harmonization.sh                       # harmonize + validate
WITH_LLM=1 sbatch slurm/reticle-harmonization.sh            # include LLM directionality (needs WashU gateway)
MIGRATE=1 META_ONLY=1 sbatch slurm/reticle-harmonization.sh # also promote small tables to RDS
```
- Without `WITH_LLM=1`, uses the frozen
  `$RETICLE_DATA/processed_data/directionality_overrides.json`.
- `MIGRATE=1` needs `AWS_DB_HOST/PORT/USER/NAME/PASSWORD` exported before submit.
- `validate_harmonization.py` aborts the job if any method's sign is inverted,
  so a bad run never reaches the migrate step.

---

## 4. Monitor jobs

```bash
squeue -u $USER                              # your queued/running jobs
squeue --name=reticle-pubmed                 # by name
scancel <job_id>                             # cancel
tail -f logs/reticle-pubmed-<job_id>.out     # live output ($RETICLE_DIR/logs)
```

---

## Files (this branch)

```
slurm/reticle-pubmed-download.sh    recurring NCBI/PubMed refresh (no DB)
slurm/reticle-biogrid-download.sh   ORCS download; hands off to reticle-staging.sh + reticle-etl.sh
slurm/reticle-harmonization.sh      harmonize + directionality + validate (+ optional RDS migrate)
scripts/download_ncbi_bulk.py       fetch gene2pubmed.gz, gene_history.gz, *.gene_info.gz
scripts/download_biogrid_orcs.py    discover + fetch ORCS release ZIPs into the loader layout
```

Still to confirm: exact partition name (`sinfo`), whether Compute2 reaches the
WashU LLM gateway (for `WITH_LLM=1`), and which WashU host runs the PubMed cron.
```
