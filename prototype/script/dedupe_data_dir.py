"""
dedupe_data_dir.py — find (and optionally remove) exact-duplicate files
under a directory tree, by CONTENT not by name.
========================================================================
Matches files by sha256, not filename/case — this is what actually caught
the false alarm on this project: data/STRING/ and data/string/ looked like
two copies in a directory listing, but turned out to be the SAME inode
(case-insensitive SMB mount folding the two paths together). A name-based
dedupe would have "fixed" a problem that didn't exist; a content-hash
dedupe correctly finds nothing to do in that case and only flags files
that are genuinely separate copies on disk.

Safe by default: dry run only, prints what it WOULD delete. Nothing is
removed unless you pass --apply.

  # dry run — just report
  python3 script/dedupe_data_dir.py /storage3/fs1/aorvedahl-RETICLE/Active/data

  # actually delete duplicates, keeping one file per group
  python3 script/dedupe_data_dir.py /storage3/fs1/aorvedahl-RETICLE/Active/data --apply

Run this FROM the RIS shell (ssh/tmux) when checking RIS storage, not
through a macOS SMB mount — SMB can fold case and confuse inode-level
comparisons; the Linux filesystem underneath is the source of truth.
"""
import argparse
import hashlib
from collections import defaultdict
from pathlib import Path


def file_hash(path, chunk_size=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def find_duplicate_groups(root):
    """Two passes: group by size first (cheap), only hash within a size
    bucket that has >1 file (avoids hashing the whole tree)."""
    by_size = defaultdict(list)
    seen_inodes = set()
    for p in Path(root).rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_ino in seen_inodes:
            continue                      # same inode reached via another path (e.g. case-folded mount) — not a real duplicate
        seen_inodes.add(st.st_ino)
        if st.st_size == 0:
            continue
        by_size[st.st_size].append(p)

    groups = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash = defaultdict(list)
        for p in paths:
            try:
                by_hash[file_hash(p)].append(p)
            except OSError:
                continue
        for plist in by_hash.values():
            if len(plist) > 1:
                groups.append(plist)
    return groups


def choose_keeper(paths):
    """Prefer the fully-lowercase path (this project's naming convention);
    fall back to the shortest, then alphabetically-first path."""
    lowercase = [p for p in paths if str(p) == str(p).lower()]
    candidates = lowercase if len(lowercase) == 1 else (lowercase or paths)
    return sorted(candidates, key=lambda p: (len(str(p)), str(p)))[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="directory to scan")
    ap.add_argument("--apply", action="store_true",
                     help="actually delete duplicates (default: dry run, deletes nothing)")
    args = ap.parse_args()

    groups = find_duplicate_groups(args.root)
    if not groups:
        print("no exact-duplicate files found (checked by content hash, not name)")
        return

    total = 0
    for g in groups:
        keep = choose_keeper(g)
        dupes = [p for p in g if p != keep]
        size = keep.stat().st_size
        print(f"\nKEEP  {keep}  ({size / 1e6:.1f} MB)")
        for d in dupes:
            print(f"  DUP -> {d}")
            total += size
            if args.apply:
                d.unlink()
                try:
                    d.parent.rmdir()      # only succeeds if now empty
                except OSError:
                    pass

    verb = "reclaimed" if args.apply else "would reclaim"
    print(f"\n{verb}: {total / 1e6:.0f} MB across {len(groups)} duplicate group(s)")
    if not args.apply:
        print("(dry run — re-run with --apply to actually delete)")


if __name__ == "__main__":
    main()
