#!/usr/bin/env python3
"""
download_biogrid_orcs.py — fetch BioGRID ORCS bulk screen dumps into the on-disk
layout the RETICLE loaders expect, so `staging_loader.py` / `hpc_staging_loader.py`
can ingest them.

This is the missing "infrequent BioGRID upload" fetch step. It is DISCOVERY-BASED:
rather than hardcode file names (which vary by release), it scrapes the BioGRID
downloads archive index to find the release directory and the per-organism ZIP,
using requests + BeautifulSoup/lxml (already in scripts/requirements.txt).

Output layout (matches scripts/config.py Config.ORGANISMS and prototype/script/paths.py):
    <out-dir>/BIOGRID-ORCS-<release>/<organism>/BIOGRID-ORCS-SCREEN_*.screen.tab.txt

⚠ VERIFY-AND-ADJUST on first run against the live site:
  * The archive host/path may differ from the default below.
  * Per-screen metadata JSON (screen_metadata_<organism>.json) is served by the
    ORCS webservice (https://orcs.thebiogrid.org) and needs an ACCESS KEY; that
    is NOT fetched here. Provide those JSONs separately (or extend this script
    with --access-key once the webservice contract is confirmed).

Usage:
    python3 download_biogrid_orcs.py --list                     # show releases
    python3 download_biogrid_orcs.py --organism homo_sapiens    # latest release
    python3 download_biogrid_orcs.py --release 2.0.18 --organism homo_sapiens --organism mus_musculus
    python3 download_biogrid_orcs.py --organism homo_sapiens --dry-run
"""
# `str | None` annotations require Python 3.10+; RIS Compute2's venv is 3.9, so
# defer annotation evaluation to keep this importable there.
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Bulk files live on the downloads host; the REST/webservice host (used by
# scripts/config.py BIOGRID_BASE_URL) is orcs.thebiogrid.org — different server.
DEFAULT_ARCHIVE = os.environ.get(
    "BIOGRID_DOWNLOADS_URL",
    "https://downloads.thebiogrid.org/BioGRID-ORCS/Release-Archive/",
)
TIMEOUT = 120
CHUNK = 1 << 20
USER_AGENT = "RETICLE-biogrid-downloader/1.0 (WashU; +https://ris.wustl.edu)"

RELEASE_RE = re.compile(r"BIOGRID-ORCS-(\d+\.\d+\.\d+)", re.IGNORECASE)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _links(session: requests.Session, url: str) -> list[str]:
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    return [a.get("href") for a in soup.find_all("a") if a.get("href")]


def discover_releases(session: requests.Session, archive_url: str) -> list[str]:
    """Return release version strings (e.g. '2.0.18') found in the archive index."""
    versions = set()
    for href in _links(session, archive_url):
        m = RELEASE_RE.search(href)
        if m:
            versions.add(m.group(1))
    # Sort semver-ish, newest last.
    return sorted(versions, key=lambda v: [int(x) for x in v.split(".")])


def _release_dir_url(archive_url: str, release: str) -> str:
    return urljoin(archive_url.rstrip("/") + "/", f"BIOGRID-ORCS-{release}/")


def find_organism_archive(session, release_url: str, organism: str) -> str | None:
    """Find the per-organism .zip in a release dir (matches organism token + .zip)."""
    token = organism.lower()
    for href in _links(session, release_url):
        low = href.lower()
        if token in low and low.endswith(".zip"):
            return urljoin(release_url, href)
    return None


def download_and_extract(session, url: str, dest_dir: Path, dry_run: bool) -> int:
    """Download a ZIP and extract its *.screen.tab.txt into dest_dir. Returns file count."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"    GET {url}", flush=True)
    if dry_run:
        return 0
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    extracted = 0
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for member in zf.namelist():
            name = os.path.basename(member)
            if not name.endswith(".screen.tab.txt"):
                continue
            with zf.open(member) as src:
                data = src.read()
            tmp = dest_dir / (name + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, dest_dir / name)  # atomic
            extracted += 1
    return extracted


def _default_out_dir() -> Path:
    data = os.environ.get("RETICLE_DATA")
    if data:
        return Path(data)
    return Path(__file__).resolve().parent.parent / "raw_data" / "BIOGRID"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--archive-url", default=DEFAULT_ARCHIVE,
                    help=f"BioGRID ORCS release archive index (default: {DEFAULT_ARCHIVE})")
    ap.add_argument("--release", default=None,
                    help="Release version, e.g. 2.0.18 (default: latest discovered).")
    ap.add_argument("--organism", action="append", default=None,
                    help="Organism token as used by ORCS filenames (repeatable). "
                         "Default: homo_sapiens mus_musculus.")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Root output dir (default: $RETICLE_DATA or ./raw_data/BIOGRID).")
    ap.add_argument("--list", action="store_true", help="List available releases and exit.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Resolve URLs and report, but download nothing.")
    args = ap.parse_args()

    organisms = args.organism or ["homo_sapiens", "mus_musculus"]
    out_root = args.out_dir or _default_out_dir()
    session = _session()

    try:
        releases = discover_releases(session, args.archive_url)
    except requests.RequestException as exc:
        print(f"ERROR: could not read archive index {args.archive_url}: {exc}", file=sys.stderr)
        return 1

    if args.list:
        print("Available BioGRID ORCS releases:")
        for r in releases:
            print(f"  {r}")
        return 0

    release = args.release or (releases[-1] if releases else None)
    if not release:
        print("ERROR: no release specified and none discovered.", file=sys.stderr)
        return 1
    print(f"BioGRID ORCS release {release} -> {out_root}", flush=True)

    release_url = _release_dir_url(args.archive_url, release)
    failed = False
    for organism in organisms:
        print(f"  organism: {organism}", flush=True)
        try:
            zip_url = find_organism_archive(session, release_url, organism)
        except requests.RequestException as exc:
            print(f"    [FAIL] listing {release_url}: {exc}", flush=True)
            failed = True
            continue
        if not zip_url:
            print(f"    [FAIL] no .zip matching '{organism}' under {release_url}", flush=True)
            failed = True
            continue
        dest = out_root / f"BIOGRID-ORCS-{release}" / organism
        try:
            n = download_and_extract(session, zip_url, dest, args.dry_run)
        except (requests.RequestException, zipfile.BadZipFile, OSError) as exc:
            print(f"    [FAIL] {organism}: {exc}", flush=True)
            failed = True
            continue
        if args.dry_run:
            print(f"    [dry-run] would extract screens into {dest}", flush=True)
        else:
            print(f"    [ok] {n} screen files -> {dest}", flush=True)

    print("\nReminder: screen_metadata_<organism>.json (ORCS webservice, access key) "
          "is NOT fetched by this script; provide it separately before loading.",
          flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
