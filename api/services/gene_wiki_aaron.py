"""Gene-wiki / prediction / distribution / structure services (ported from the prototype).

All knowledge-base reads go to the RDS `reticle.kb_*` tables. The prototype had a `kb_fetchall`
that preferred a local 560 MB kb.db mirror and fell back to RDS; in the cloud there is no local
mirror, so everything here uses db_service.db_fetchall directly and the dialect is always Postgres.

Two prototype behaviours are preserved deliberately and are easy to break:

  * GO NEGATIVE ANNOTATIONS. kb_gene_go carries a `qualifier`; "NOT involved_in" / "NOT enables"
    mean a curator established the gene does NOT do this (~2.3k rows). Reading them as positive
    evidence displays and predicts the exact opposite of the curated fact — one gene (ATG16L2) has
    a NOT-annotation as its ONLY biological-process row. Every positive-use query below therefore
    carries _GO_POSITIVE. The single exception is the novelty-exclusion set in predict_functions,
    where a NOT row is a contraindication and should also suppress the prediction.

  * MIDRANK TIES in the distribution. Strict `v < focal` reports 0 on tie-saturated screens (the
    p-value-clipped ones where a large share of the genome sits on one floor value), which made the
    caption claim "1st percentile" for a gene that is merely tied. Ties count half — the standard
    fractional-rank definition.
"""

import json
import logging
import re
import threading
import urllib.request
from collections import defaultdict
from typing import Any

from services.db_service import db_fetchall
from services.execution import offload

logger = logging.getLogger(__name__)

# Append to any query that reads a GO row as "this gene does X" — see the module docstring.
#
# Written with substr() rather than the more obvious `NOT LIKE 'NOT%'` on purpose: db_fetchall hands
# the SQL to psycopg2 with bound parameters, and psycopg2 %-formats the query, so a LITERAL '%' in
# the text is read as a format specifier and raises "IndexError: tuple index out of range". (The
# prototype never hit this because its kb reads go to local sqlite, where % is not special — the bug
# only appears on the pure-cloud path.) Every negative qualifier is 'NOT <relation>' and no positive
# one starts with NOT, so this is exactly equivalent and contains no '%'.
_GO_POSITIVE = "AND (gg.qualifier IS NULL OR substr(gg.qualifier, 1, 3) <> 'NOT')"

_PUBMED_CLUSTER = re.compile(r"\s*\((?:PubMed:\d+)(?:,\s*PubMed:\d+)*\)")

_DIST_COL = {
    "native": "harmonized_score",
    "percentile": "percentile_score",
    "robustz": "robust_z_score",
}

# Structure URLs are resolved from live EBI/RCSB APIs; cache per process.
_STRUCT_CACHE: dict[str, dict] = {}
_BP_SIZE: dict[str, int] | None = None
_BP_NAME: dict[str, str] | None = None
_BP_LOCK = threading.Lock()


def resolve_symbol_variants(s: str) -> list[str]:
    """Casing variants only — no human<->mouse ortholog mapping."""
    return list(dict.fromkeys([s, s.upper(), s.lower(), s.capitalize()]))


def _clean_uniprot(text: str | None) -> tuple[str | None, int]:
    """Strip the dense inline (PubMed:...) citation clusters for display; return the count too."""
    if not text:
        return None, 0
    n = len(set(re.findall(r"PubMed:(\d+)", text)))
    clean = _PUBMED_CLUSTER.sub("", text)
    clean = re.sub(r"\bNote=", "", clean)  # a UniProt structural marker, not prose
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return (clean or None), n


# ---------------------------------------------------------------------------------------------
# TYPE-AHEAD for the home page's search box. One suggester per mode.
# ---------------------------------------------------------------------------------------------
class SuggestUnavailable(Exception):
    """The index could not be read. Distinct from "nothing matched", which is an empty list.

    Both used to surface as []. That is a lie the user acts on: when RDS stopped answering, the box
    reported that PO matches no genes — with POLR2A sitting right there in the table. A suggester
    that cannot reach its index has to say so, not answer confidently on its behalf.
    """


@offload("db")
def get_gene_suggest(q: str, taxid: int = 9606, limit: int = 8) -> list[dict[str, Any]]:
    """Ranked gene suggestions for a typed prefix, from the precomputed gene_search table.

    prototype/script/build_gene_search.py carries the reasoning and the measurements; the short
    version is that the ranking needed BOTH a screen-hit count and a paper count. Hits alone put
    TP53RK above TP53 — a tumour suppressor is rarely a called hit — and papers alone put PON1
    above POLR2A on "PO".

    Two rules in the ORDER BY, both learned by shipping them wrong first: canonical symbols come
    before aliases, or "FANC" answers BRCA1 and BRCA2 (correct alias hits, wrong intent); and an
    exact match only wins outright when it is a canonical symbol, or "PO" answers whichever obscure
    gene carries "PO" as a literal alias.

    De-duplicates by symbol — one gene with three matching aliases filled three of eight slots with
    itself — and over-fetches to leave room for that.
    """
    q = (q or "").strip()
    if not q:
        return []
    term = q.upper()
    limit = max(1, min(int(limit), 25))
    try:
        rows = db_fetchall(
            "SELECT symbol, term, is_alias, n_hits, name FROM gene_search "
            "WHERE taxid = ? AND term LIKE ? "
            "ORDER BY (term = ? AND is_alias = 0) DESC, is_alias, rank DESC, LENGTH(term), term "
            "LIMIT ?",
            (taxid, term + "%", term, limit * 5),
        )
    except Exception as exc:
        # gene_search is newer than the rest of the schema, so a deploy can predate it — and RDS
        # itself goes unreachable from time to time. Either way this is NOT "no matches"; the
        # router turns it into a flagged 200 so the box can say it lost the index.
        logger.warning("gene_search unavailable", exc_info=True)
        raise SuggestUnavailable() from exc
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        sym = r["symbol"]
        if sym in seen:
            continue
        seen.add(sym)
        out.append({"symbol": sym, "name": r["name"] or "",
                    "matched": r["term"] if r["is_alias"] else None,
                    "n_hits": r["n_hits"]})
        if len(out) >= limit:
            break
    return out


@offload("db")
def get_screen_suggest(q: str, taxid: int = 9606, limit: int = 8) -> list[dict[str, Any]]:
    """Ranked suggestions from the screen-similarity comparable pool.

    ``kb_screen`` has 2,157 screens, but only the 962 rows in ``screen_sim_meta``
    can be opened by the screen-comparison page. Suggesting an unsupported row
    sent users directly into a guaranteed 404, so this search intentionally
    joins the precomputed pool. The full corpus remains available through the
    upload/results and screen-detail flows.

    Matches what a person remembers a screen BY — cell line, condition, phenotype, first author, or
    the BioGRID id. Two things the raw columns get wrong, both fixed here rather than in the data:

      BioGRID punctuates its cell lines — K-562, HL-60, A-375 — and nobody types them that way.
      "K562" matched zero of 1,952 human screens. Both sides are stripped of hyphens and spaces
      before comparing, in plain SQL so it behaves the same on sqlite and Postgres.

      number_of_hits is stored as TEXT, so ORDER BY put '5' above '1345'. Cast it.
    """
    q = (q or "").strip()
    if not q:
        return []
    like = f"%{q.lower()}%"
    squashed = "%" + "".join(c for c in q.lower() if c.isalnum()) + "%"
    limit = max(1, min(int(limit), 25))
    sq = "REPLACE(REPLACE(LOWER(k.cell_line), '-', ''), ' ', '')"
    try:
        rows = db_fetchall(
            "SELECT k.screen_id, k.cell_line, k.condition_name, k.phenotype, k.author, k.pmid, "
            "       k.number_of_hits "
            "FROM kb_screen k "
            "JOIN screen_sim_meta sim "
            "  ON CAST(sim.screen_id AS TEXT) = CAST(k.screen_id AS TEXT) "
            "WHERE k.taxid = ? AND ("
            f"     {sq} LIKE ? OR LOWER(k.condition_name) LIKE ? "
            "  OR LOWER(k.phenotype) LIKE ? OR LOWER(k.author) LIKE ? "
            "  OR CAST(k.screen_id AS TEXT) LIKE ?) "
            "ORDER BY CAST(k.number_of_hits AS INTEGER) DESC LIMIT ?",
            (taxid, squashed, like, like, like, f"{q}%", limit),
        )
    except Exception as exc:
        logger.warning("screen suggest unavailable", exc_info=True)
        raise SuggestUnavailable() from exc
    return [{"screen_id": str(r["screen_id"]),
             "cell_line": r["cell_line"] or "", "condition": r["condition_name"] or "",
             "phenotype": r["phenotype"] or "", "author": r["author"] or "",
             "pmid": r["pmid"], "n_hits": r["number_of_hits"]} for r in rows]


def _kb_resolve(gene: str, taxid: int) -> dict | None:
    """symbol / alias / retired id / GeneID -> row with gene_id, symbol, taxid."""
    if gene.isdigit():
        r = db_fetchall(
            "SELECT gene_id, symbol, taxid FROM kb_gene WHERE gene_id=?", (int(gene),)
        )
        return r[0] if r else None
    # Exact match first, then case-insensitive. LOWER() works on both backends; the prototype's
    # original COLLATE NOCASE is sqlite-only and 500'd on Postgres.
    for ci in (False, True):
        col, val = ("LOWER(a.alias)", gene.lower()) if ci else ("a.alias", gene)
        r = db_fetchall(
            f"""SELECT g.gene_id, g.symbol, g.taxid FROM kb_gene_alias a
                JOIN kb_gene g ON g.gene_id = a.gene_id
                WHERE {col} = ? AND a.taxid = ?
                ORDER BY (a.alias_type='symbol') DESC LIMIT 1""",
            (val, taxid),
        )
        if r:
            return r[0]
    return None


# ─────────────────────────── /api/gene_wiki ────────────────────────────────


@offload("db")
def get_gene_wiki(gene: str, taxid: int = 9606) -> dict[str, Any] | None:
    """Everything the KB knows about one gene. Pure retrieval — no LLM, no directionality."""
    r = _kb_resolve(gene, taxid)
    if not r:
        return None
    gid, taxid = r["gene_id"], r["taxid"]

    g = db_fetchall(
        """SELECT symbol, description, full_name, type_of_gene, chromosome, map_location,
                  ncbi_summary, uniprot_acc, uniprot_function, uniprot_location, uniprot_disease,
                  ensembl_gene_id, omim_id
           FROM kb_gene WHERE gene_id=?""",
        (gid,),
    )[0]

    aliases = [
        a["alias"]
        for a in db_fetchall(
            "SELECT DISTINCT alias FROM kb_gene_alias "
            "WHERE gene_id=? AND alias_type='synonym' LIMIT 14",
            (gid,),
        )
    ]
    orthologs = [
        {
            "species": "Homo sapiens" if o["ortholog_taxid"] == 9606 else "Mus musculus",
            "symbol": o["ortholog_symbol"],
            "gene_id": o["ortholog_gene_id"],
            "taxid": o["ortholog_taxid"],
        }
        for o in db_fetchall(
            "SELECT ortholog_taxid, ortholog_gene_id, ortholog_symbol "
            "FROM kb_gene_ortholog WHERE gene_id=? ORDER BY ortholog_taxid",
            (gid,),
        )
    ]

    func, n_cite = _clean_uniprot(g["uniprot_function"])
    loc, _ = _clean_uniprot(g["uniprot_location"])
    dis, _ = _clean_uniprot(g["uniprot_disease"])

    go: dict[str, list[str]] = {}
    for ns in ("molecular_function", "biological_process", "cellular_component"):
        go[ns] = [
            x["name"]
            for x in db_fetchall(
                f"""SELECT DISTINCT t.name FROM kb_gene_go gg
                    JOIN kb_go_term t ON t.go_id=gg.go_id
                    WHERE gg.gene_id=? AND t.namespace=? AND t.is_obsolete=0
                    {_GO_POSITIVE} LIMIT 8""",
                (gid, ns),
            )
        ]

    part_rows = db_fetchall(
        """SELECT g2.gene_id gid, g2.symbol sym, e.combined_score sc FROM kb_string_edge e
           JOIN kb_gene g2
             ON g2.gene_id = CASE WHEN e.gene_id_a=? THEN e.gene_id_b ELSE e.gene_id_a END
           WHERE e.gene_id_a=? OR e.gene_id_b=? ORDER BY e.combined_score DESC LIMIT 12""",
        (gid, gid, gid),
    )
    partners = [{"partner": p["sym"], "score": p["sc"]} for p in part_rows]

    # Full sub-network: edges among {this gene} u {its partners} — a real graph, not a star.
    node_ids = [gid] + [p["gid"] for p in part_rows]
    nidx = {n: i for i, n in enumerate(node_ids)}
    net_edges = []
    if len(node_ids) > 1:
        ph = ",".join("?" * len(node_ids))
        for e in db_fetchall(
            f"SELECT gene_id_a a, gene_id_b b, combined_score s FROM kb_string_edge "
            f"WHERE gene_id_a IN ({ph}) AND gene_id_b IN ({ph})",
            tuple(node_ids + node_ids),
        ):
            if e["a"] in nidx and e["b"] in nidx:
                net_edges.append({"s": nidx[e["a"]], "t": nidx[e["b"]], "score": e["s"]})
    string_network = {
        "nodes": [g["symbol"]] + [p["sym"] for p in part_rows],
        "edges": net_edges,
    }

    dep = None
    dr = db_fetchall(
        """SELECT d.essential_class, d.mean_score, d.n_dependent, d.n_lines, d.min_score,
                  m.cell_line_name, m.lineage
           FROM kb_gene_dependency d
           LEFT JOIN kb_model m ON m.model_id = d.most_dependent_model
           WHERE d.gene_id=?""",
        (gid,),
    )
    if dr:
        d = dr[0]
        dep = {
            "essential_class": d["essential_class"],
            "mean_score": d["mean_score"],
            "n_dependent": d["n_dependent"],
            "n_lines": d["n_lines"],
            "min_score": d["min_score"],
            "most_dependent_cell": d["cell_line_name"],
            "lineage": d["lineage"],
        }

    n_scr = db_fetchall("SELECT COUNT(*) n FROM kb_screen_hit WHERE gene_id=?", (gid,))[0]["n"]
    by_phen = []
    # Postgres only in the cloud — the prototype branched here because sqlite spells this
    # GROUP_CONCAT.
    for row in db_fetchall(
        """SELECT s.phenotype, COUNT(*) c, STRING_AGG(DISTINCT s.condition_name, ',') conds
           FROM kb_screen_hit h JOIN kb_screen s ON s.screen_id=h.screen_id
           WHERE h.gene_id=? GROUP BY s.phenotype ORDER BY c DESC""",
        (gid,),
    ):
        conds = [x for x in (row["conds"] or "").split(",") if x and x != "None"]
        by_phen.append(
            {
                "phenotype": row["phenotype"] or "unspecified",
                "count": row["c"],
                "conditions": conds,
            }
        )

    n_pmid = db_fetchall("SELECT COUNT(*) n FROM kb_gene_pubmed WHERE gene_id=?", (gid,))[0]["n"]

    pathways = [
        {"name": p["name"], "stable_id": p["stable_id"], "url": p["url"]}
        for p in db_fetchall(
            "SELECT name, stable_id, url FROM kb_gene_pathway WHERE gene_id=? ORDER BY name",
            (gid,),
        )
    ]

    return {
        "found": True,
        "identity": {
            "symbol": g["symbol"],
            "gene_id": gid,
            "taxid": taxid,
            "organism": "Homo sapiens" if taxid == 9606 else "Mus musculus",
            "description": g["description"],
            "full_name": g["full_name"],
            "type_of_gene": g["type_of_gene"],
            "chromosome": g["chromosome"],
            "map_location": g["map_location"],
            "aliases": aliases,
            "uniprot_acc": g["uniprot_acc"],
            "ensembl_gene_id": g["ensembl_gene_id"],
            "omim_id": g["omim_id"],
            "genecards_symbol": g["symbol"] if taxid == 9606 else None,
            "orthologs": orthologs,
        },
        "ncbi_summary": g["ncbi_summary"],
        "uniprot": {
            "acc": g["uniprot_acc"],
            "function": func,
            "n_citations": n_cite,
            "location": loc,
            "disease": dis,
        },
        "go": go,
        "pathways": pathways,
        "string": partners,
        "string_network": string_network,
        "depmap": dep,
        "screens": {"n_total": n_scr, "by_phenotype": by_phen},
        "literature": {"n_pmid": n_pmid},
    }


# ─────────────────────── /api/gene_screen_distribution ──────────────────────


def _score_method_label(sb: str | None) -> str:
    """'DIR_POS(Log2FC)' -> 'Log2FC' (strip the provenance decoration)."""
    if not sb:
        return "native score"
    a, b = sb.find("("), sb.rfind(")")
    return sb[a + 1 : b].strip() if (a != -1 and b > a) else sb.strip()


def _histogram(vals: list[float], focal: float, nbins: int = 40,
               bounded: tuple[float, float] | None = None) -> dict:
    """Pure-python histogram; clip to the 1st-99th pct for readability unless `bounded` is given."""
    xs = sorted(vals)
    n = len(xs)
    if bounded:
        lo, hi = bounded
    else:
        lo, hi = xs[max(0, int(0.01 * n))], xs[min(n - 1, int(0.99 * n))]
    if hi <= lo:
        lo, hi = xs[0], xs[-1]
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / nbins
    counts = [0] * nbins
    for v in xs:
        counts[min(nbins - 1, max(0, int((v - lo) / width)))] += 1
    fb = min(nbins - 1, max(0, int((focal - lo) / width)))
    return {
        "bins": [{"x0": round(lo + i * width, 4), "c": counts[i]} for i in range(nbins)],
        "lo": round(lo, 4),
        "hi": round(hi, 4),
        "width": round(width, 6),
        "focal_bin": fb,
        "nbins": nbins,
    }


@offload("db")
def get_gene_screen_distribution(
    gene: str,
    taxid: int = 9606,
    screen: str | None = None,
    score: str = "percentile",
    top: int = 12,
) -> dict[str, Any] | None:
    """Where a gene sits inside a screen, against that screen's full gene distribution."""
    org = "Mus musculus" if str(taxid) == "10090" else "Homo sapiens"
    variants = resolve_symbol_variants(gene)
    ph = ",".join("?" * len(variants))

    # Rank the gene's screens by ABSOLUTE effect. The prototype's original
    # `ORDER BY percentile_score ASC` was a tautology: it always picked the screen where the gene
    # ranks most depleted, so the panel opened at "1st percentile" every time and a gene's
    # ENRICHED screens were structurally unreachable from the dropdown.
    trows = db_fetchall(
        f"""SELECT h.screen_id sid, h.gene_symbol sym, h.harmonized_score harm,
                   h.percentile_score pct, h.robust_z_score rz, h.is_hit hit,
                   m.cell_line cell, m.phenotype pheno, m.score_basis basis
            FROM harmonized_scores h JOIN screen_metadata m ON m.screen_id = h.screen_id
            WHERE h.gene_symbol IN ({ph}) AND m.organism_official = ?
                  AND m.coverage_type = 'FULL' AND h.percentile_score IS NOT NULL
            ORDER BY ABS(h.percentile_score) DESC, h.is_hit DESC, ABS(h.robust_z_score) DESC
            LIMIT ?""",
        tuple(variants + [org, top]),
    )
    if not trows:
        return None

    seed = trows[0]["sym"]
    screens = [
        {
            "sid": r["sid"],
            "label": (r["cell"] or "?") + ((" · " + r["pheno"]) if r["pheno"] else ""),
            "method": _score_method_label(r["basis"]),
            "pct": round(r["pct"], 3),
            "hit": int(r["hit"] or 0),
        }
        for r in trows
    ]
    sids = {r["sid"] for r in trows}
    sid = screen if screen in sids else trows[0]["sid"]
    srow = next(r for r in trows if r["sid"] == sid)

    col = _DIST_COL.get(score, "percentile_score")
    drows = db_fetchall(
        f"SELECT {col} v FROM harmonized_scores WHERE screen_id = ? AND {col} IS NOT NULL",
        (sid,),
    )
    vals = [r["v"] for r in drows]
    if len(vals) < 5:
        return None

    focal = srow["harm"] if score == "native" else srow["rz"] if score == "robustz" else srow["pct"]
    focal = 0.0 if focal is None else focal
    hist = _histogram(vals, focal, bounded=(-1.0, 1.0) if score == "percentile" else None)

    # Midrank for ties — see the module docstring.
    n_below = sum(1 for v in vals if v < focal)
    n_tied = sum(1 for v in vals if v == focal)
    below = n_below + 0.5 * n_tied

    return {
        "focus": seed,
        "taxid": taxid,
        "screen": sid,
        "score": score,
        "screens": screens,
        "screen_meta": {
            "label": next(s["label"] for s in screens if s["sid"] == sid),
            "method": _score_method_label(srow["basis"]),
            "coverage": "FULL",
        },
        "dist": hist,
        "focal": {
            "value": round(focal, 4),
            "bin": hist["focal_bin"],
            "n_genes": len(vals),
            "pct_in_screen": round(below / len(vals), 4),
            "n_tied": n_tied,
            "direction": "depleted" if focal < 0 else "enriched" if focal > 0 else "neutral",
            "is_hit": int(srow["hit"] or 0),
        },
    }


# ────────────────────────── /api/gene_structure ─────────────────────────────


def _http_json(url: str, timeout: int = 12) -> Any:
    """GET a JSON document over https.

    The scheme is enforced here rather than trusted at each call site. That is what bandit's B310
    is about — urlopen also accepts file:/ and custom schemes — and while today's callers all build
    their URL from a literal https prefix, the interpolated part is a UniProt accession read out of
    the KB, so the value is data rather than a constant.
    """
    if not url.startswith("https://"):
        raise ValueError("refusing to fetch a non-https URL")
    req = urllib.request.Request(url, headers={"User-Agent": "RETICLE-KB/1.0 (research)"})
    # The suppressions on the next line are for the scheme check above; hosts are EBI and RCSB.
    # (Written as prose, not as a bare "noqa/nosec:" prefix — ruff parses any line containing
    # `noqa` as a directive and warns that this one names no rule codes.)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310  # nosec B310
        return json.loads(r.read())


def _resolve_structures(uniprot_acc: str) -> dict[str, Any]:
    """-> {alphafold_pdb_url, alphafold_version, experimental:[{pdb_id, method, resolution,
    chain, url}]}"""
    if uniprot_acc in _STRUCT_CACHE:
        return _STRUCT_CACHE[uniprot_acc]
    out: dict[str, Any] = {
        "uniprot_acc": uniprot_acc,
        "alphafold_pdb_url": None,
        "alphafold_version": None,
        "experimental": [],
    }
    # AlphaFold model. Read pdbUrl from the API rather than composing a filename — model versions
    # change and a hardcoded v4 URL already 404s.
    try:
        preds = _http_json(f"https://alphafold.ebi.ac.uk/api/prediction/{uniprot_acc}")
        af = next(
            (p for p in preds if p.get("entryId", "").startswith(f"AF-{uniprot_acc}-F1")),
            preds[0],
        )
        out["alphafold_pdb_url"] = af.get("pdbUrl")
        out["alphafold_version"] = str(af.get("latestVersion") or "")
    except Exception as exc:  # noqa: BLE001 — a missing model is normal, not an error
        logger.info("AlphaFold lookup failed for %s: %s", uniprot_acc, exc)
    # Experimental structures, ranked by resolution + coverage.
    try:
        best = _http_json(
            f"https://www.ebi.ac.uk/pdbe/api/mappings/best_structures/{uniprot_acc}"
        )
        for b in best.get(uniprot_acc, [])[:6]:
            out["experimental"].append(
                {
                    "pdb_id": b["pdb_id"],
                    "method": b.get("experimental_method"),
                    "resolution": b.get("resolution"),
                    "chain": b.get("chain_id"),
                    "url": f"https://files.rcsb.org/download/{b['pdb_id']}.pdb",
                }
            )
    except Exception as exc:  # noqa: BLE001
        logger.info("PDBe lookup failed for %s: %s", uniprot_acc, exc)
    _STRUCT_CACHE[uniprot_acc] = out
    return out


@offload("external")
def get_gene_structure(gene: str, taxid: int = 9606) -> dict[str, Any]:
    r = _kb_resolve(gene, taxid)
    if not r:
        return {"available": False}
    row = db_fetchall("SELECT uniprot_acc FROM kb_gene WHERE gene_id=?", (r["gene_id"],))
    acc = row[0]["uniprot_acc"] if row else None
    if not acc:
        return {"available": False, "reason": "no UniProt accession for this gene"}
    s = _resolve_structures(acc)
    s["available"] = bool(s.get("alphafold_pdb_url") or s.get("experimental"))
    return s


# ───────────────────────── /api/gene_predictions ────────────────────────────


def _bp_meta() -> tuple[dict[str, int], dict[str, str]]:
    """Cached GO biological-process term sizes and names.

    `size` counts kb_gene_go ROWS, not distinct genes — kb_gene_go repeats a (gene, term) pair once
    per evidence code, so a multi-evidence term over-counts. It is used only for the 5..300 breadth
    filter, where the approximation is acceptable.
    """
    global _BP_SIZE, _BP_NAME
    if _BP_SIZE is None or _BP_NAME is None:
        # The lock is load-bearing, not defensive. The guard covers TWO globals whose
        # assignments are separated by a full database round-trip, so without it a second
        # caller arriving in that window sees _BP_SIZE already set, skips the block, and gets
        # back (_BP_SIZE, None) — and get_gene_predictions' `name.get(term, term)` then raises
        # AttributeError, i.e. an unhandled 500 on /api/gene_predictions.
        # This is currently unreachable because the event loop serialises these requests, but
        # /api/net_predict and /api/interpret already run in starlette's threadpool, so it is
        # one call path away from being live.
        with _BP_LOCK:
            if _BP_SIZE is None or _BP_NAME is None:  # re-check under the lock
                size = {
                    r["go_id"]: r["c"]
                    for r in db_fetchall(
                        "SELECT gg.go_id, COUNT(*) c FROM kb_gene_go gg "
                        "JOIN kb_go_term t ON t.go_id=gg.go_id "
                        "WHERE t.namespace='biological_process' AND t.is_obsolete=0 "
                        f"{_GO_POSITIVE} GROUP BY gg.go_id"
                    )
                }
                name = {
                    r["go_id"]: r["name"]
                    for r in db_fetchall(
                        "SELECT go_id, name FROM kb_go_term WHERE namespace='biological_process'"
                    )
                }
                # Publish both only once both are built, so no reader can observe a half-state
                # even if it somehow bypassed the lock.
                _BP_SIZE, _BP_NAME = size, name
    return _BP_SIZE, _BP_NAME  # type: ignore[return-value]


def _string_clean_neighbours(gid: int, k: int = 30) -> dict[int, float]:
    """STRING partners from ANNOTATION-INDEPENDENT channels only.

    The `database` and `textmining` channels encode curated GO/pathway knowledge, so scoring a GO
    prediction with them would be circular. Recombining only neighborhood/fusion/cooccurence/
    coexpression/experimental keeps the evidence orthogonal to the thing being predicted.
    """
    out: dict[int, float] = {}
    for r in db_fetchall(
        "SELECT CASE WHEN gene_id_a=? THEN gene_id_b ELSE gene_id_a END nb, "
        "neighborhood, fusion, cooccurence, coexpression, experimental "
        "FROM kb_string_edge WHERE gene_id_a=? OR gene_id_b=?",
        (gid, gid, gid),
    ):
        p = 1.0
        for c in (
            r["neighborhood"],
            r["fusion"],
            r["cooccurence"],
            r["coexpression"],
            r["experimental"],
        ):
            p *= 1.0 - (c or 0) / 1000.0
        clean = 1.0 - p
        if clean > 0:
            out[r["nb"]] = clean
    return dict(sorted(out.items(), key=lambda x: -x[1])[:k])


def _coess_neighbours(gid: int, k: int = 30) -> dict[int, float]:
    """Co-essential partners (DepMap-derived). Degrades to STRING-only if unbuilt."""
    try:
        return {
            r["neighbor_gene_id"]: r["corr"]
            for r in db_fetchall(
                "SELECT neighbor_gene_id, corr FROM kb_coessential WHERE gene_id=? "
                "ORDER BY corr DESC LIMIT ?",
                (gid, k),
            )
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("kb_coessential unavailable (%s) — predicting from STRING only", exc)
        return {}


_LAYER_DESC = {
    ("coess", "string"): "co-essential CRISPR dependency and STRING functional interactions",
    ("string",): "STRING functional interactions",
    ("coess",): "co-essential CRISPR dependency",
}


def _format_prediction(
    term: str,
    supp: set[int],
    layers: set[str],
    neigh: dict[int, dict[str, Any]],
    sym_map: dict[int, str],
    name: dict[str, str],
    sym: str,
) -> dict[str, Any]:
    """One candidate term -> the prediction record the UI renders.

    Confidence is computed here from the EVIDENCE (how many independent layers agree, how many
    genes support it), never asserted by a model — these predictions are deterministic.
    """
    supp_sorted = sorted(supp, key=lambda nb: -neigh[nb]["w"])
    syms = [sym_map.get(nb, str(nb)) for nb in supp_sorted[:5]]
    nl = len(layers)
    if nl >= 2 and len(supp) >= 3:
        conf = "high"
    elif len(supp) >= 4 or nl >= 2:
        conf = "moderate"
    else:
        conf = "tentative"
    desc = _LAYER_DESC[tuple(sorted(layers))]
    more = f" and {len(supp) - len(syms)} more" if len(supp) > len(syms) else ""
    return {
        "function": name.get(term, term),
        "go_id": term,
        "confidence": conf,
        "n_support": len(supp),
        "layers": sorted(layers),
        "supporters": syms,
        "explanation": (
            f"Shares {desc} with {', '.join(syms)}{more} — genes that act in this "
            f"process — while {sym} itself carries no such annotation."
        ),
    }


@offload("db")
def get_gene_predictions(gene: str, taxid: int = 9606, top: int = 8) -> dict[str, Any]:
    """Guilt-by-association GO predictions the gene is NOT already annotated with."""
    r = _kb_resolve(gene, taxid)
    if not r:
        return {"found": False}
    gid, sym = r["gene_id"], r["symbol"]
    size, name = _bp_meta()

    def norm(d: dict[int, float]) -> dict[int, float]:
        """Scale each layer to its own max so the two are comparable when summed."""
        m = max(d.values()) if d else 1.0
        return {k: v / m for k, v in d.items()}

    strn, coess = norm(_string_clean_neighbours(gid)), norm(_coess_neighbours(gid))
    neigh: dict[int, dict[str, Any]] = {}
    for nb, w in strn.items():
        neigh.setdefault(nb, {"w": 0.0, "layers": set()})
        neigh[nb]["w"] += w
        neigh[nb]["layers"].add("string")
    for nb, w in coess.items():
        neigh.setdefault(nb, {"w": 0.0, "layers": set()})
        neigh[nb]["w"] += w
        neigh[nb]["layers"].add("coess")
    if not neigh:
        return {"found": True, "symbol": sym, "n_neighbours": 0, "predictions": []}

    # Terms we will NOT predict. Deliberately NOT filtered by _GO_POSITIVE: a "NOT involved_in" row
    # is curated evidence AGAINST the gene doing this, so it should suppress the prediction too.
    own = {
        row["go_id"]
        for row in db_fetchall(
            "SELECT gg.go_id FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id=gg.go_id "
            "WHERE gg.gene_id=? AND t.namespace='biological_process'",
            (gid,),
        )
    }

    nb_ids = list(neigh.keys())
    ph = ",".join("?" * len(nb_ids))
    supporters: dict[str, set[int]] = defaultdict(set)  # set => one vote per gene
    for row in db_fetchall(
        f"SELECT gg.gene_id gid, gg.go_id term FROM kb_gene_go gg "
        f"JOIN kb_go_term t ON t.go_id=gg.go_id "
        f"WHERE gg.gene_id IN ({ph}) AND t.namespace='biological_process' AND t.is_obsolete=0 "
        f"{_GO_POSITIVE}",
        tuple(nb_ids),
    ):
        supporters[row["term"]].add(row["gid"])

    cands = []
    for term, supp in supporters.items():
        if term in own or not (5 <= size.get(term, 0) <= 300) or len(supp) < 2:
            continue
        score = sum(neigh[nb]["w"] for nb in supp)
        layers = set().union(*[neigh[nb]["layers"] for nb in supp])
        cands.append((score, term, supp, layers))
    cands.sort(key=lambda x: -x[0])
    cands = cands[:top]

    all_supp = {nb for _, _, supp, _ in cands for nb in supp}
    sym_map: dict[int, str] = {}
    if all_supp:
        ph2 = ",".join("?" * len(all_supp))
        sym_map = {
            row["gene_id"]: row["symbol"]
            for row in db_fetchall(
                f"SELECT gene_id, symbol FROM kb_gene WHERE gene_id IN ({ph2})",
                tuple(all_supp),
            )
        }

    preds = [
        _format_prediction(term, supp, layers, neigh, sym_map, name, sym)
        for _score, term, supp, layers in cands
    ]

    return {
        "found": True,
        "symbol": sym,
        "n_neighbours": len(neigh),
        "n_known_bp": len(own),
        "predictions": preds,
    }
