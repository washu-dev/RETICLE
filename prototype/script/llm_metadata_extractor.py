"""
RETICLE — Rule-based Metadata Curation (Phase 2)
================================================
Extracts normalised metadata from BioGRID's structured fields into the screen_metadata_curated
table. FULLY AUTOMATED, PURELY RULE-BASED, NO LLM CALL.

HISTORY -- why the filename says LLM and the code does not
----------------------------------------------------------
  An early version used an LLM to extract control_comparison. That field had no downstream
  consumer, so it was dropped in a scope revision (along with the control_comparison and
  confidence_control columns). The LLM's job in this project was re-scoped to ruling on
  DIRECTIONALITY instead -- see directionality_mapper.py. The filename is kept because other
  scripts and the pipeline log refer to it.

  What remains here is three deterministic decisions (confidence 1.0 = the rule is certain;
  < 1.0 = a heuristic):
    screen_type      -- METHODOLOGY + LIBRARY_TYPE + ENZYME
    selection_method -- SCREEN_TYPE
    coverage_type    -- FULL_SIZE + FULL_SIZE_AVAILABLE
  Phase 3 downstream stratifies on screen_type / selection_method using these three labels.

RUN
---
  python3 script/llm_metadata_extractor.py --dry-run --limit 5
  python3 script/llm_metadata_extractor.py            # everything (makes no network request)
  python3 script/llm_metadata_extractor.py --screen-ids 89,381 --rerun
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

DB = paths.DB
BIOGRID_JSON = paths.BIOGRID_METADATA

PROMPT_VERSION = "v4.1-assay-domain"   # v4.1: added assay_domain (fitness/stress/reporter)

# --------------------------------------------------------------------------
# DB schema -- rule-only; no control_comparison / confidence_control
# --------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS screen_metadata_curated (
    screen_id              TEXT PRIMARY KEY,
    pmid                   TEXT,

    screen_type            TEXT,   -- KO | CRISPRi | CRISPRa | RNAi | Other
    selection_method       TEXT,   -- Negative | Positive | Bidirectional | Phenotype | Unknown
    coverage_type          TEXT,   -- Genome-wide | Focused | Unknown  (library SCOPE; distinct from screen_metadata.COVERAGE_TYPE, which is data AVAILABILITY)
    assay_domain           TEXT,   -- fitness | stress | reporter | other  (the class that governs cross-screen comparability)

    confidence_screen_type    REAL,  -- 1.0 = the rule is certain; <1.0 = heuristic or ambiguous
    confidence_selection      REAL,
    confidence_coverage       REAL,
    confidence_domain         REAL,

    notes                  TEXT,   -- machine notes (base-edited flags and the like)

    -- provenance
    llm_model              TEXT,   -- always 'rule-only'
    prompt_version         TEXT,
    extraction_timestamp   TEXT
)
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_curated_type ON screen_metadata_curated(screen_type)",
    "CREATE INDEX IF NOT EXISTS idx_curated_sel  ON screen_metadata_curated(selection_method)",
]

_COLUMNS = [
    "screen_id", "pmid",
    "screen_type", "selection_method", "coverage_type", "assay_domain",
    "confidence_screen_type", "confidence_selection", "confidence_coverage",
    "confidence_domain",
    "notes",
    "llm_model", "prompt_version", "extraction_timestamp",
]

# --------------------------------------------------------------------------
# Load the BioGRID JSON
# --------------------------------------------------------------------------

_biogrid_index: dict[str, dict] = {}


def _load_biogrid():
    if _biogrid_index:
        return
    for _, path in BIOGRID_JSON.items():
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for sid, entries in data.items():
            if entries:
                _biogrid_index[str(sid)] = entries[0]


def get_bio(screen_id: str) -> dict:
    _load_biogrid()
    return _biogrid_index.get(str(screen_id), {})


# --------------------------------------------------------------------------
# Rule extraction (deterministic, no LLM)
# --------------------------------------------------------------------------

def rule_screen_type(bio: dict, db_row: dict) -> tuple[str, float]:
    """Decide screen_type from METHODOLOGY / LIBRARY_TYPE / ENZYME.

    BioGRID's METHODOLOGY takes only three values -- Knockout / Activation / Inhibition (plus
    Cytosine Base Editing and friends); LIBRARY_TYPE is CRISPRn / CRISPRa / CRISPRi.
    """
    methodology  = (bio.get("METHODOLOGY") or db_row.get("METHODOLOGY") or "").lower()
    library_type = (bio.get("LIBRARY_TYPE") or "").lower()
    enzyme       = (bio.get("ENZYME") or "").lower()

    # Base editing -> a functional knockout. RETICLE classification decision: base editing that
    # introduces a stop codon is loss-of-function, i.e. KO.
    if "base editing" in library_type:
        return "KO", 1.0
    # CRISPRi (transcriptional repression)
    if "crispri" in library_type or "inhibition" in methodology or "krab" in enzyme:
        return "CRISPRi", 1.0
    # CRISPRa (transcriptional activation)
    if "crispra" in library_type or "activation" in methodology:
        return "CRISPRa", 1.0
    if "dcas9" in enzyme and "krab" not in enzyme:
        return "CRISPRa", 0.7   # heuristic: dCas9 without KRAB is usually activation, but not
                                # certain -> low confidence
    # RNAi
    if any(k in methodology for k in ("rnai", "shrna", "sirna")):
        return "RNAi", 1.0
    # KO (CRISPRn / nuclease-active Cas9). Note the spelling is "crisprn", not "crispn".
    if "crisprn" in library_type or "knockout" in methodology:
        return "KO", 1.0
    if "cas9" in enzyme and "dcas9" not in enzyme:
        return "KO", 0.9
    return "Other", 0.5


def rule_selection_method(bio: dict, db_row: dict) -> tuple[str, float]:
    """Decide selection_method from SCREEN_TYPE."""
    screen_type = (bio.get("SCREEN_TYPE") or db_row.get("SCREEN_TYPE") or "").strip()
    st = screen_type.lower()

    if st == "negative selection":
        return "Negative", 1.0
    if st == "positive selection":
        return "Positive", 1.0
    if st == "positive and negative selection":
        return "Bidirectional", 1.0
    if st == "phenotype screen":
        return "Phenotype", 1.0
    # fuzzy-match fallback
    if "negative" in st and "positive" not in st:
        return "Negative", 0.9
    if "positive" in st and "negative" not in st:
        return "Positive", 0.9
    if "phenotype" in st or "sort" in st or "facs" in st:
        return "Phenotype", 0.9
    return "Unknown", 0.5


def rule_assay_domain(bio: dict, db_row: dict) -> tuple[str, float]:
    """Coarse assay class that controls cross-screen comparability.

      fitness  — baseline survival/growth; the essentiality axis applies, and
                 these screens form the clean continuous-correlation pool.
      stress   — survival under an APPLIED pressure (drug/virus/toxin/radiation…);
                 "conditional fitness". Comparable mainly within the same pressure.
      reporter — cells are sorted by a measured MARKER (FACS/level/localization),
                 not by survival. Each marker is its own axis -> excluded from the
                 correlation network and the essentiality stats; kept only for the
                 per-gene functional read-out.
      other    — fallback for phenotypes that fit none cleanly (excluded from the
                 quantitative axes, like reporter).

    Derived from PHENOTYPE (BioGRID's semi-controlled field). The percentile math
    is identical across classes; this tag only governs how screens are POOLED and
    CORRELATED downstream.
    """
    ph = (bio.get("PHENOTYPE") or db_row.get("PHENOTYPE") or "").strip().lower()
    if not ph:
        return "other", 0.5
    # stress: survival under an applied pressure
    if ph.startswith("response to") or "resistance" in ph:
        return "stress", 1.0
    # fitness: baseline growth / viability / essentiality
    if any(k in ph for k in ("prolifer", "viab", "fitness", "growth", "essential", "tumor")):
        return "fitness", 1.0
    # reporter / marker: sorted by a measured trait, not by survival
    if any(k in ph for k in (
            "protein", "peptide", "rna", "accumulation", "distribution", "transport",
            "localization", "signal transduction", "phagocyt", "autophag", "mitophag",
            "lysosome", "vesicle", "frameshift", "nonsense-mediated", "binding",
            "secretion", "differentiation", "reprogram", "migration", "cell cycle",
            "senescen", "syncytium", "pyroptosis", "lipid")):
        return "reporter", 1.0
    return "other", 0.5


def rule_coverage_type(bio: dict) -> tuple[str, float]:
    """Decide coverage_type (library scope) from FULL_SIZE and FULL_SIZE_AVAILABLE."""
    available = (bio.get("FULL_SIZE_AVAILABLE") or "").strip().lower()
    full_size_str = bio.get("FULL_SIZE") or ""
    try:
        full_size = int(str(full_size_str).replace(",", ""))
    except ValueError:
        full_size = 0

    if available == "yes" and full_size >= 10000:
        return "Genome-wide", 1.0
    if available == "no":
        # Only hits were deposited, but the screen itself may still be genome-wide -- FULL_SIZE says
        if full_size >= 10000:
            return "Genome-wide", 0.8
        return "Unknown", 0.6
    if 0 < full_size < 5000:
        return "Focused", 1.0
    if full_size >= 10000:
        return "Genome-wide", 0.9
    return "Unknown", 0.5


# --------------------------------------------------------------------------
# DB write
# --------------------------------------------------------------------------

def insert_row(db: sqlite3.Connection, record: dict, dry_run: bool):
    if dry_run:
        print(f"  [dry-run] screen {record['screen_id']}: "
              f"type={record['screen_type']}({record['confidence_screen_type']:.2f}) "
              f"sel={record['selection_method']}({record['confidence_selection']:.2f}) "
              f"cov={record['coverage_type']}({record['confidence_coverage']:.2f})")
        return
    cols = ", ".join(_COLUMNS)
    placeholders = ", ".join(f":{c}" for c in _COLUMNS)
    db.execute(
        f"INSERT OR REPLACE INTO screen_metadata_curated ({cols}) VALUES ({placeholders})",
        record,
    )
    db.commit()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",      type=int, default=0)
    parser.add_argument("--screen-ids", type=str, default="")
    parser.add_argument("--rerun",      action="store_true")
    parser.add_argument("--dry-run",    action="store_true",
                        help="print only; write nothing to the database")
    args = parser.parse_args()

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute(DDL)
    for stmt in INDEXES:
        db.execute(stmt)
    db.commit()

    if args.screen_ids:
        ids = [s.strip() for s in args.screen_ids.split(",") if s.strip()]
        rows = db.execute(
            f"SELECT * FROM screen_metadata WHERE SCREEN_ID IN ({','.join('?'*len(ids))})",
            ids,
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM screen_metadata ORDER BY CAST(SCREEN_ID AS INTEGER)"
        ).fetchall()

    if not args.rerun:
        done = {r[0] for r in db.execute("SELECT screen_id FROM screen_metadata_curated")}
        rows = [r for r in rows if r["SCREEN_ID"] not in done]

    if args.limit:
        rows = rows[:args.limit]

    log(f"Screens to process: {len(rows)}")
    if not rows:
        log("Nothing to do.")
        db.close()
        return

    _load_biogrid()
    now_iso = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0

    for i, row in enumerate(rows, 1):
        sid    = row["SCREEN_ID"]
        pmid   = row["SOURCE_ID"] or ""
        db_row = dict(row)
        bio    = get_bio(sid)

        screen_type, conf_type = rule_screen_type(bio, db_row)
        selection,   conf_sel  = rule_selection_method(bio, db_row)
        coverage,    conf_cov  = rule_coverage_type(bio)
        domain,      conf_dom  = rule_assay_domain(bio, db_row)

        notes = ""
        if "base editing" in (bio.get("LIBRARY_TYPE") or "").lower():
            notes = ("Base-edited knockout (cytosine base editing); "
                     "classified as KO for cross-screen comparison.")

        record = {
            "screen_id": sid, "pmid": pmid,
            "screen_type": screen_type, "selection_method": selection,
            "coverage_type": coverage, "assay_domain": domain,
            "confidence_screen_type": round(conf_type, 3),
            "confidence_selection":   round(conf_sel, 3),
            "confidence_coverage":    round(conf_cov, 3),
            "confidence_domain":      round(conf_dom, 3),
            "notes": notes,
            "llm_model": "rule-only",
            "prompt_version": PROMPT_VERSION,
            "extraction_timestamp": now_iso(),
        }
        insert_row(db, record, args.dry_run)
        written += 1

    print()
    log(f"Done. rows written={written}")
    if not args.dry_run:
        total = db.execute("SELECT COUNT(*) FROM screen_metadata_curated").fetchone()[0]
        log(f"Total rows in screen_metadata_curated: {total}")
    db.close()


if __name__ == "__main__":
    main()
