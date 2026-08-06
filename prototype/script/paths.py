"""
RETICLE — one place that resolves paths
=======================================

Every script imports its paths from here rather than hard-coding an absolute path of its own.

The same code runs in two environments:
  * local Mac       -- no environment variable set; paths are relative to this project
                       directory (processed_data/, raw_data/).
  * Compute2 (RIS)  -- RETICLE_DATA=/storage3/fs1/aorvedahl-RETICLE/Active/data is set, and both
                       processed_data and the raw BioGRID tree point at RIS storage.

The raw-data layout on RIS differs from local: BIOGRID-ORCS-2.0.18/ holds the per-species
directories and the metadata JSON side by side, with no metadata/ or screenings/ level. The
helpers below therefore PROBE for both layouts rather than assuming either.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# RETICLE_DATA points at the data root on RIS storage when running on the cluster; unset
# locally, in which case everything falls back inside the project directory.
_DATA_ENV = os.environ.get("RETICLE_DATA")
DATA_ROOT = Path(_DATA_ENV).resolve() if _DATA_ENV else PROJECT_ROOT

# ---- outputs / derived data ------------------------------------------------
PROCESSED_DATA = (DATA_ROOT / "processed_data") if _DATA_ENV else (PROJECT_ROOT / "processed_data")
try:                                    # only create processed_data if the data root is there
    PROCESSED_DATA.mkdir(exist_ok=True)
except OSError:
    pass                                # no data root (e.g. imported on another machine) - not an error
DB = PROCESSED_DATA / "reticle_master.db"


# ---- raw BioGRID (both layouts probed) -------------------------------------
def _first_existing(cands):
    for c in cands:
        if c.exists():
            return c
    return cands[0]


# Root of the raw screen files: RIS = .../BIOGRID-ORCS-2.0.18 ; local = raw_data/BIOGRID
RAW_BIOGRID = _first_existing([
    DATA_ROOT / "BIOGRID-ORCS-2.0.18",     # RIS layout
    DATA_ROOT / "raw_data" / "BIOGRID",    # if RETICLE_DATA points at the project root
    PROJECT_ROOT / "raw_data" / "BIOGRID", # local
])
RAW_DATA = RAW_BIOGRID.parent
PROC_BIOGRID = PROCESSED_DATA / "BIOGRID"


def _biogrid_metadata(species_file):
    """On RIS the metadata JSON sits directly under BIOGRID-ORCS-2.0.18/; locally it is one
    level down, in metadata/."""
    return _first_existing([
        RAW_BIOGRID / species_file,                 # RIS layout
        RAW_BIOGRID / "metadata" / species_file,    # local layout
    ])


BIOGRID_METADATA = {
    "Homo sapiens": _biogrid_metadata("screen_metadata_homo_sapiens.json"),
    "Mus musculus": _biogrid_metadata("screen_metadata_musculus.json"),
}


def _biogrid_screens(species):
    """Per-species raw screen dir. RIS = BIOGRID-ORCS-2.0.18/<species>/ ;
    local = raw_data/BIOGRID/screenings/<species>/."""
    return _first_existing([
        RAW_BIOGRID / species,                 # RIS layout
        RAW_BIOGRID / "screenings" / species,  # local layout
    ])


BIOGRID_SCREENS = {
    "Homo sapiens": _biogrid_screens("homo_sapiens"),
    "Mus musculus": _biogrid_screens("mus_musculus"),
}
