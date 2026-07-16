#!/usr/bin/env python3
"""Build per-gene Knowledge-base documents from BioGRID ORCS bulk screens.

Streams the human + mouse ORCS `.screens.tar.gz` archives (no disk extraction),
aggregates every gene's significant screen HITS across all screens, and emits
compact, self-contained per-gene text sections (symbol, IDs, aliases, hit screens
with cell line / phenotype / library / scores / PubMed link). Sections are packed
into <=MAX_FILES files so the corpus fits the Gateway AI Knowledge base 500-file cap.
"""
import os, io, glob, math, tarfile
from collections import defaultdict

WD = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(WD, "raw")
OUT = os.path.join(WD, "kb_gene_docs_10_lean")
MAX_FILES = 10           # consolidated: fewer, larger files (easier to upload/manage)
MAX_HITS_LISTED = 20     # lean: cap detailed hit lines per gene (hub/essential genes)
MAX_ALIASES = 8
PUBMED = "https://pubmed.ncbi.nlm.nih.gov/{}"

ARCHIVES = [
    ("human.tar.gz", "Homo sapiens", "human"),
    ("mouse.tar.gz", "Mus musculus", "mouse"),
]

def read_header(line):
    return [c.lstrip("#").strip() for c in line.rstrip("\n").split("\t")]

def clean(v):
    return "" if v in ("-", "", "N/A") else v.strip()

def score_types(meta):
    return [clean(meta.get(f"SCORE.{n}_TYPE", "")) for n in range(1, 6)]

def parse_index_stream(fobj, all_screens):
    txt = io.TextIOWrapper(fobj, encoding="utf-8", errors="replace")
    cols = read_header(txt.readline())
    ci = {c: i for i, c in enumerate(cols)}
    for line in txt:
        p = line.rstrip("\n").split("\t")
        if len(p) < len(cols):
            continue
        sid = p[ci["SCREEN_ID"]]
        all_screens[sid] = {c: p[ci[c]] for c in cols}

def scan_screen_stream(fobj, org_off, org_label, genes):
    txt = io.TextIOWrapper(fobj, encoding="utf-8", errors="replace")
    header = txt.readline()
    if not header.startswith("#"):
        return
    cols = read_header(header)
    ci = {c: i for i, c in enumerate(cols)}
    for line in txt:
        p = line.rstrip("\n").split("\t")
        if len(p) < len(cols):
            continue
        sym = p[ci["OFFICIAL_SYMBOL"]].strip()
        entrez = p[ci["IDENTIFIER_ID"]].strip()
        if sym in ("", "-"):
            sym = f"ENTREZ:{entrez}" if entrez not in ("", "-") else None
        if not sym:
            continue
        key = (org_label, sym)
        g = genes.get(key)
        if g is None:
            g = genes[key] = {"entrez": "", "aliases": "", "org_off": org_off,
                              "org_id": "", "tested": 0, "hits": []}
        g["tested"] += 1
        if not g["entrez"] and entrez not in ("", "-"):
            g["entrez"] = entrez
        if not g["aliases"]:
            g["aliases"] = p[ci["ALIASES"]].strip()
        if not g["org_id"]:
            g["org_id"] = p[ci["ORGANISM_ID"]].strip()
        if p[ci["HIT"]].strip().upper() == "YES":
            sid = p[ci["SCREEN_ID"]].strip()
            scores = [p[ci[f"SCORE.{n}"]].strip() for n in range(1, 6)]
            g["hits"].append((sid, scores))

def main():
    os.makedirs(OUT, exist_ok=True)
    all_screens = {}
    genes = {}

    for tar_name, org_off, org_label in ARCHIVES:
        tar_path = os.path.join(RAW, tar_name)
        if not os.path.exists(tar_path):
            print(f"SKIP {org_off}: {tar_name} not found", flush=True)
            continue
        print(f"[{org_off}] streaming {tar_name} ...", flush=True)
        n_screens = 0
        with tarfile.open(tar_path, "r:gz") as t:
            for m in t:
                if not m.isfile():
                    continue
                f = t.extractfile(m)
                if f is None:
                    continue
                if m.name.endswith("index.tab.txt"):
                    parse_index_stream(f, all_screens)
                elif m.name.endswith(".screen.tab.txt"):
                    scan_screen_stream(f, org_off, org_label, genes)
                    n_screens += 1
                    if n_screens % 200 == 0:
                        print(f"  ... {n_screens} screens", flush=True)
        print(f"  {n_screens} screen files scanned", flush=True)

    print(f"Screens indexed: {len(all_screens)}", flush=True)
    hit_genes = {k: v for k, v in genes.items() if v["hits"]}
    print(f"Genes seen: {len(genes)} | genes with >=1 hit: {len(hit_genes)}", flush=True)

    def render_gene(key, g):
        org_label, sym = key
        lines = [f"## {sym} — {g['org_off']} CRISPR screen hits"]
        idbits = []
        if g["entrez"] and not sym.startswith("ENTREZ"):
            idbits.append(f"Entrez Gene ID {g['entrez']}")
        idbits.append(f"organism {g['org_off']} (taxid {g['org_id']})")
        al = [a for a in g["aliases"].split("|") if a and a != "-"][:MAX_ALIASES]
        if al:
            idbits.append("aliases: " + ", ".join(al))
        lines.append(" | ".join(idbits))
        H, T = len(g["hits"]), g["tested"]
        lines.append(f"Summary: {sym} ({g['org_off']}) is a significant hit in {H} of "
                     f"{T} BioGRID ORCS CRISPR screen(s) in which it was assayed.")
        lines.append("")
        lines.append("Screen hits:")
        for sid, scores in g["hits"][:MAX_HITS_LISTED]:
            m = all_screens.get(sid, {})
            st = score_types(m)
            sc_txt = "; ".join(f"{st[i]}={scores[i]}" for i in range(5)
                               if st[i] and clean(scores[i]))
            parts = []
            head = f"Screen {sid}"
            nm = clean(m.get("SCREEN_NAME", ""))
            if nm: head += f" ({nm})"
            au = clean(m.get("AUTHOR", ""))
            if au: head += f", {au}"
            parts.append(head)
            cl = clean(m.get("CELL_LINE", "")); ct = clean(m.get("CELL_TYPE", ""))
            if cl: parts.append(f"cell line {cl}" + (f" ({ct})" if ct else ""))
            ph = clean(m.get("PHENOTYPE", ""))
            if ph: parts.append(f'phenotype "{ph}"')
            cond = clean(m.get("CONDITION_NAME", ""))
            if cond: parts.append(f"condition {cond}")
            lt = clean(m.get("LIBRARY_TYPE", "")); lm = clean(m.get("LIBRARY_METHODOLOGY", ""))
            enz = clean(m.get("ENZYME", ""))
            libbits = "/".join(x for x in (lt, lm) if x)
            if libbits or enz:
                parts.append(" ".join(x for x in (libbits, enz) if x))
            stype = clean(m.get("SCREEN_TYPE", ""))
            if stype: parts.append(stype)
            if sc_txt: parts.append(f"scores: {sc_txt}")
            src_id = clean(m.get("SOURCE_ID", "")); src_ty = clean(m.get("SOURCE_TYPE", ""))
            if src_ty == "pubmed" and src_id:
                parts.append(f"PubMed {PUBMED.format(src_id)}")
            lines.append("- " + "; ".join(parts))
        if H > MAX_HITS_LISTED:
            extra = []
            for sid, _ in g["hits"][MAX_HITS_LISTED:]:
                m = all_screens.get(sid, {})
                if clean(m.get("SOURCE_TYPE", "")) == "pubmed":
                    pid = clean(m.get("SOURCE_ID", ""))
                    if pid:
                        extra.append(pid)
            uniq = sorted(set(extra))
            lines.append(f"- ... and {H - MAX_HITS_LISTED} additional screen hit(s). "
                         f"Further supporting PubMed IDs: {', '.join(uniq[:60])}")
        lines.append("")
        return "\n".join(lines)

    keys = sorted(hit_genes.keys(), key=lambda k: (k[0], k[1].upper()))
    n_files = min(MAX_FILES, max(1, len(keys)))
    per_file = math.ceil(len(keys) / n_files)
    print(f"Writing {n_files} files (~{per_file} genes each) to {OUT}", flush=True)

    for f in glob.glob(os.path.join(OUT, "*.txt")):
        os.remove(f)

    safe = lambda s: "".join(c if c.isalnum() else "_" for c in s)[:24]
    written = 0
    for fi in range(n_files):
        chunk = keys[fi * per_file:(fi + 1) * per_file]
        if not chunk:
            break
        first = f"{chunk[0][0]}_{chunk[0][1]}"
        last = f"{chunk[-1][0]}_{chunk[-1][1]}"
        fname = f"orcs_gene_hits_{fi:03d}_{safe(first)}__{safe(last)}.txt"
        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as out:
            out.write(f"BioGRID ORCS CRISPR screen hits — gene documents (part {fi+1}/{n_files})\n")
            out.write("Source: BioGRID ORCS v2.0.18 (open repository of CRISPR screens). "
                      "Each entry lists the CRISPR screens in which the gene was a significant "
                      "hit, with cell line, phenotype, library, scores and source PubMed.\n")
            out.write("=" * 80 + "\n\n")
            for key in chunk:
                out.write(render_gene(key, hit_genes[key]))
                out.write("\n")
        written += 1

    with open(os.path.join(OUT, "_MANIFEST.txt"), "w", encoding="utf-8") as mf:
        mf.write("BioGRID ORCS gene-hit Knowledge-base corpus\n")
        mf.write(f"Genes with >=1 screen hit : {len(hit_genes)}\n")
        mf.write(f"Total screens indexed     : {len(all_screens)}\n")
        mf.write(f"Files generated           : {written} (cap {MAX_FILES})\n")
        mf.write(f"Total hit records         : {sum(len(v['hits']) for v in hit_genes.values())}\n")
    print(f"\nDONE: {written} files, {len(hit_genes)} genes, {len(all_screens)} screens.", flush=True)

if __name__ == "__main__":
    main()
