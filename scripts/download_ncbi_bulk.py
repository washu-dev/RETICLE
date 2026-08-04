#!/usr/bin/env python3
"""
download_ncbi_bulk.py — fetch the NCBI bulk files RETICLE's literature layer
needs, into <RETICLE_DATA>/ncbi (RIS: /storage3/fs1/aorvedahl-RETICLE/Active/data/ncbi).

This is the missing "recurring PubMed download" step. It feeds:
  * prototype/script/build_kb_gene.py         (reads *.gene_info.gz  -> kb_gene)
  * prototype/script/build_kb_pubmed_links.py (reads gene2pubmed.gz  -> kb_gene_pubmed)

Files fetched (over HTTPS from the NCBI FTP mirror):
  * gene/DATA/gene2pubmed.gz                              (gene <-> PMID links)
  * gene/DATA/gene_history.gz                             (retired/updated gene ids)
  * gene/DATA/GENE_INFO/Mammalia/Homo_sapiens.gene_info.gz
  * gene/DATA/GENE_INFO/Mammalia/Mus_musculus.gene_info.gz

Each download is atomic (temp file + rename) and skipped when the remote file is
unchanged, judged from a per-file ".meta.json" sidecar recording the server's
Content-Length + Last-Modified. Safe to run on a schedule (cron -> bsub).

NOTE: NCBI_API_KEY only affects the E-utilities REST API (esearch/efetch); it is
not used for these static bulk files and is intentionally ignored here.

Usage:
    python3 download_ncbi_bulk.py --out-dir /storage3/fs1/aorvedahl-RETICLE/Active/data/ncbi
    python3 download_ncbi_bulk.py                 # uses $RETICLE_DATA/ncbi
    python3 download_ncbi_bulk.py --force         # re-download even if unchanged
    python3 download_ncbi_bulk.py --check         # HEAD only; report what would change
    python3 download_ncbi_bulk.py --only gene2pubmed.gz
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import requests

NCBI_BASE = "https://ftp.ncbi.nlm.nih.gov"

# Logical name -> remote path under NCBI_BASE. Logical name == local filename.
FILES = {
    "gene2pubmed.gz": "gene/DATA/gene2pubmed.gz",
    "gene_history.gz": "gene/DATA/gene_history.gz",
    "Homo_sapiens.gene_info.gz": "gene/DATA/GENE_INFO/Mammalia/Homo_sapiens.gene_info.gz",
    "Mus_musculus.gene_info.gz": "gene/DATA/GENE_INFO/Mammalia/Mus_musculus.gene_info.gz",
}

CHUNK = 1 << 20  # 1 MiB
TIMEOUT = 60
USER_AGENT = "RETICLE-ncbi-downloader/1.0 (WashU; +https://ris.wustl.edu)"


def _default_out_dir() -> Path:
    data = os.environ.get("RETICLE_DATA")
    if data:
        return Path(data) / "ncbi"
    # Local fallback mirrors prototype/script/paths.py behavior.
    return Path(__file__).resolve().parent.parent / "raw_data" / "ncbi"


def _remote_meta(session: requests.Session, url: str) -> dict:
    """HEAD the URL; return {'size': int|None, 'last_modified': str|None}."""
    resp = session.head(url, timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    size = resp.headers.get("Content-Length")
    return {
        "size": int(size) if size and size.isdigit() else None,
        "last_modified": resp.headers.get("Last-Modified"),
    }


def _load_sidecar(meta_path: Path) -> dict:
    try:
        return json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return {}


def _unchanged(remote: dict, local: dict, local_file: Path) -> bool:
    """Consider unchanged when the file exists and both size + Last-Modified match."""
    if not local_file.exists() or not local:
        return False
    if remote.get("last_modified") and remote["last_modified"] != local.get("last_modified"):
        return False
    if remote.get("size") is not None and remote["size"] != local.get("size"):
        return False
    # Guard against a truncated prior download.
    if remote.get("size") is not None and local_file.stat().st_size != remote["size"]:
        return False
    return True


def _download(session: requests.Session, url: str, dest: Path) -> int:
    """Stream to a temp file in dest's dir, then atomically rename. Returns bytes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".part")
    tmp = Path(tmp_name)
    total = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            with session.get(url, stream=True, timeout=TIMEOUT) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=CHUNK):
                    if chunk:
                        fh.write(chunk)
                        total += len(chunk)
        os.replace(tmp, dest)  # atomic within same filesystem
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Destination dir (default: $RETICLE_DATA/ncbi or ./raw_data/ncbi)")
    ap.add_argument("--only", action="append", choices=sorted(FILES), default=None,
                    help="Download only these file(s); repeatable. Default: all.")
    ap.add_argument("--force", action="store_true", help="Re-download even if unchanged.")
    ap.add_argument("--check", action="store_true",
                    help="HEAD only: report which files would change, download nothing.")
    args = ap.parse_args()

    out_dir = args.out_dir or _default_out_dir()
    wanted = args.only or list(FILES)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    print(f"NCBI bulk download -> {out_dir}", flush=True)
    changed, skipped, failed = [], [], []

    for name in wanted:
        url = f"{NCBI_BASE}/{FILES[name]}"
        dest = out_dir / name
        meta_path = out_dir / (name + ".meta.json")
        try:
            remote = _remote_meta(session, url)
        except requests.RequestException as exc:
            print(f"  [FAIL] {name}: HEAD failed: {exc}", flush=True)
            failed.append(name)
            continue

        local = _load_sidecar(meta_path)
        if not args.force and _unchanged(remote, local, dest):
            sz = dest.stat().st_size
            print(f"  [skip] {name}: unchanged ({sz:,} bytes)", flush=True)
            skipped.append(name)
            continue

        if args.check:
            print(f"  [would update] {name} "
                  f"(remote size={remote.get('size')}, last_modified={remote.get('last_modified')})",
                  flush=True)
            changed.append(name)
            continue

        try:
            n = _download(session, url, dest)
        except (requests.RequestException, OSError) as exc:
            print(f"  [FAIL] {name}: download failed: {exc}", flush=True)
            failed.append(name)
            continue

        # Verify size when the server declared one.
        if remote.get("size") is not None and n != remote["size"]:
            print(f"  [FAIL] {name}: size mismatch (got {n:,}, expected {remote['size']:,})",
                  flush=True)
            failed.append(name)
            dest.unlink(missing_ok=True)
            continue

        meta_path.write_text(json.dumps({**remote, "downloaded_bytes": n}, indent=2))
        print(f"  [ok]   {name}: {n:,} bytes", flush=True)
        changed.append(name)

    print(
        f"\nSummary: {len(changed)} updated, {len(skipped)} unchanged, "
        f"{len(failed)} failed.",
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
