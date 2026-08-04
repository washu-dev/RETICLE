"""LLM analyses over RETICLE data (ported from the standalone prototype).

Four endpoints' worth of grounded LLM work, all of them deliberately thin: the deterministic data
is assembled from RDS / the external-source cache first, and the model is only ever asked to
interpret what is already on the page.

  get_screen_analysis  — GET  /api/screen_analysis   per-phenotype read of one gene's BioGRID
                         CRISPR-screen footprint (gpt-4.1, JSON mode)
  get_reporter_explain — GET  /api/reporter_explain  1-2 sentences on whether a gene's KNOWN
                         function connects to a reporter screen's process (gpt-4.1)
  get_net_predict      — GET  /api/net_predict       guilt-by-association function prediction from
                         RETICLE's OWN co-essentiality network (gpt-5, JSON mode)
  get_interpret        — POST /api/interpret         the Explorer's "AI reading" of a gene's
                         cross-screen behaviour; RAG over MyGene/NCBI/STRING + PubMed (gpt-4.1)

FOUR THINGS THAT ARE EASY TO BREAK HERE
---------------------------------------
1. THE PROMPTS ARE TUNED ARTEFACTS. SCREEN_SYS / REXPLAIN_SYS / NET_PREDICT_SYS / SYS_PROMPT and
   the four prompt builders are copied byte-for-byte from prototype/web/app.py — em dashes, double
   spaces, and the '×' '⇄' '·' '–' '…' characters included. Rewording or re-wrapping any of them
   silently changes model behaviour. The "never assert the DIRECTION of a screen" clauses are a
   product invariant (co-essentiality and hit-recurrence are undirected), not house style.

2. NET_PREDICT'S SERVER-SIDE FILTERS *ARE* THE FEATURE. The model is told to be novel and to cite
   at least two real partners; it is not trusted to comply. _net_predict_filter re-checks novelty
   against the focal gene's own GO/Reactome terms, drops cited "partners" that are not actually in
   the co-essential partner list, dedupes, and only then requires >= 2 survivors. Loosening any of
   that turns a prediction feature into a hallucination feature. The <2-annotated-partners early
   return matters too: it is what stops a hopeless case from spending a gpt-5 call.

3. EVERYTHING IN HERE BLOCKS. db_fetchall is synchronous psycopg2 opening a fresh connection per
   query, services.external_sources uses urllib plus a real time.sleep() for NCBI rate limiting,
   and the gateway POST has a 60 s timeout retried up to 4 times (and up to twice more for JSON
   repair). Each public function is therefore an `async def` whose body does nothing but
   `await run_in_threadpool(<sync worker>)`. Never call the sync workers from the event loop.

4. THE PAYLOADS ARE BRANCH-SHAPED ON PURPOSE. screen_analysis has three different 200 bodies and
   reporter_explain has two, differing by which keys are PRESENT (see each docstring). The ported
   frontend branches on key presence, so normalising the shapes breaks it.

SQL AUDIT (db_fetchall does sql.replace("?", "%s") and psycopg2 then %-formats the query):
every statement written in this module — the reporter_explain screen join, the _screen_prompt
condition/cell-type scan, the two net_edge partner queries, and the three KB annotation queries —
contains no literal '%' (which would be read as a format specifier -> IndexError) and no '?'
inside a quoted SQL string literal (which would be silently rewritten to '%s'). The GO filter is
imported as gene_wiki_aaron._GO_POSITIVE and uses substr(...) <> 'NOT' rather than LIKE 'NOT%' for
exactly this reason — never "tidy" it back. Condition names in the DATA may contain '%'
("1% DMSO"); that is safe because they only ever travel as bound parameters and prompt text.
"""

# ruff: noqa: E501
#   The prompt constants and prompt builders below are copied verbatim from the prototype; hard-
#   wrapping them to 100 columns would change the exact strings the model sees.

import asyncio
import logging
import re
import threading
from typing import Any

from starlette.concurrency import run_in_threadpool

from services import external_sources as ex
from services.coessential_network_aaron import (
    NET_CTX_LABELS,
    _edge_table,
    _fitness_lean,
    _lean_label,
    _resolve_seed,
    cohit_among,
    edge_tier,
)
from services.db_service import db_fetchall
from services.external_sources import TAXID as ORG2TAX
from services.gene_wiki_aaron import (
    _GO_POSITIVE,
    _clean_uniprot,
    _kb_resolve,
    get_gene_wiki,
)
from services.llm_client_aaron import (
    INTERPRET_MODEL,
    NET_PREDICT_MODEL,
    WashULLMClientAaron,
    gen_kwargs,
)

logger = logging.getLogger(__name__)

# Bump when the prompt changes in a way that could change the answer; it is part of the
# prediction cache key so a stale entry cannot outlive its prompt.
NET_PREDICT_PROMPT_VERSION = "netpred-v1"


# ─────────────────────────── caches (PER WORKER PROCESS) ────────────────────────────
#
# These are plain module-level dicts, so every uvicorn worker / ECS task keeps its OWN copy: with
# N tasks behind the load balancer the hit rate is ~1/N, and because the models run at a non-zero
# temperature the same gene can come back worded differently depending on which task answers. A
# cached payload is also returned WHOLE — on a hit, counts like n_partners/view come from the run
# that populated the entry, not from the queries just executed. That is prototype behaviour and is
# kept.
#
# What is NOT kept: the prototype's dicts are unbounded and never evicted or invalidated, which is
# a slow leak in a long-lived server (and the Fargate task has 512 MB). These are capped, evicting
# the oldest insertion first. If cross-task coherence ever matters, promote them to a table rather
# than widening the dict.
_CACHE_MAX = 512

_SYNTH_CACHE: dict[Any, dict] = {}  # gene_id -> screen-analysis payload
_REXPLAIN_CACHE: dict[Any, dict] = {}  # (symbol.lower(), sorted screen ids) -> payload
_NET_PRED_CACHE: dict[Any, dict] = {}  # (gene_id | symbol, organism, context) -> payload


def _cache_put(cache: dict, key: Any, value: dict) -> None:
    """Insert, evicting the oldest entry once the cap is reached (dicts keep insertion order)."""
    if key not in cache and len(cache) >= _CACHE_MAX:
        cache.pop(next(iter(cache)))
    cache[key] = value


# ──────────────────────────────── gateway client ────────────────────────────────────

_CLIENTS: dict[str, WashULLMClientAaron] = {}
_CLIENT_LOCK = threading.Lock()


def _client(model: str) -> WashULLMClientAaron:
    """One gateway client per model, process-wide.

    The prototype constructs a fresh WashULLMClient inside every request, so its in-memory bearer-
    token cache never survives a call and each request re-mints an Azure AD token. Reusing the
    instance changes no payload — only how often the token endpoint is hit. Construction raises
    when gateway config is missing (naming the KEY only, never a value), which is what turns a
    misconfigured deploy into the router's 502 before any network call happens.
    """
    c = _CLIENTS.get(model)
    if c is not None:
        return c
    with _CLIENT_LOCK:
        c = _CLIENTS.get(model)
        if c is None:
            c = WashULLMClientAaron(model=model)
            _CLIENTS[model] = c
    return c


# ════════════════════════════ GET /api/screen_analysis ══════════════════════════════
#
# The ONLY LLM call on the gene-wiki page. It reads nothing but the gene's BioGRID CRISPR-screen
# hits and describes the pattern phenotype by phenotype; everything else on that page is
# deterministic. No directionality is ever asserted.


SCREEN_SYS = (
    "You are a functional-genomics analyst interpreting one gene's CRISPR-screen footprint, PHENOTYPE BY "
    "PHENOTYPE. For each phenotype you are given the specific perturbations/conditions (drugs, viruses, "
    "treatments) and cell contexts of the screens in which knockout of this gene was an author-called hit.\n"
    "For EACH phenotype, infer — in ONE tight, specific sentence (two only if truly needed) — what the gene's "
    "recurrence in those SPECIFIC screens suggests about its role IN THAT context, using your knowledge of what "
    "the named conditions are (a drug's target/class, a treatment's pathway, a stress type). Be mechanistic and "
    "concrete: name the shared drug class / pathway / stress you infer (e.g. 'these are topoisomerase poisons "
    "and PARP/ATR inhibitors → recurs in DNA-damage-response screens'). Do NOT just restate the screen count.\n"
    "Then give ONE overall takeaway sentence.\n"
    "Return ONLY a JSON object of this exact shape:\n"
    '{"by_phenotype":[{"phenotype":"<copy the phenotype label EXACTLY as given>","insight":"<1-2 sentences>"}],'
    '"overall":"<one sentence>"}\n'
    "Cover every phenotype given, in the same order. For a phenotype with no specific perturbation (plain "
    "fitness/proliferation screens) infer from that fact (e.g. a core-essential requirement). If a condition is "
    "unfamiliar, don't guess its mechanism.\n"
    "Boundaries: the screen hits are OUR ground-truth data — invent no screens. NEVER assert the DIRECTION of a "
    "screen (no 'sensitizes' / 'protects' / 'required for' / sign of an effect); say the gene 'recurs in' or is "
    "'repeatedly implicated in' the context."
)


def _screen_prompt(w: dict[str, Any]) -> str:
    from collections import Counter, defaultdict
    idn, sc = w["identity"], w["screens"]
    per: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"conds": Counter(), "cells": Counter()})
    for r in db_fetchall(
        "SELECT s.phenotype ph, s.condition_name cond, s.cell_type ct "
        "FROM kb_screen_hit h JOIN kb_screen s ON s.screen_id = h.screen_id WHERE h.gene_id=?",
        (idn["gene_id"],)):
        ph = r["ph"] or "unspecified"
        c = (r["cond"] or "").strip()
        if c and c != "-":
            per[ph]["conds"][c] += 1
        ct = (r["ct"] or "").strip()
        if ct and ct != "-":
            per[ph]["cells"][ct] += 1
    blocks = []
    for p in sc["by_phenotype"]:                       # display order (by screen count desc)
        d = per.get(p["phenotype"], {"conds": Counter(), "cells": Counter()})
        conds = "; ".join(f"{c}(×{n})" if n > 1 else c for c, n in d["conds"].most_common(20)) \
            or "no specific perturbation (plain fitness / proliferation screens)"
        cells = ", ".join(c for c, _ in d["cells"].most_common(6)) or "various"
        blocks.append(f"### {p['phenotype']} — {p['count']} screen(s)\n"
                      f"conditions: {conds}\ncell contexts: {cells}")
    return (f"GENE: {idn['symbol']} ({idn['organism']}) — hit in {sc['n_total']} pooled CRISPR screens.\n\n"
            + "\n\n".join(blocks)
            + "\n\nProduce the per-phenotype interpretation JSON now.")


def _screen_analysis_sync(gene: str, taxid: int) -> dict[str, Any]:
    # get_gene_wiki is an existing `async def` whose body is entirely synchronous (blocking
    # psycopg2, no awaits), so it is driven on a private loop inside this worker thread rather
    # than on the request loop. It costs ~13 queries this analysis never reads — that is the
    # prototype's cost too, and re-implementing just the resolve + screens subset would fork
    # behaviour from the endpoint that owns it.
    w = asyncio.run(get_gene_wiki(gene, taxid))
    if not w:
        # A 200 whose ONLY key is found:false. Deliberately not a 404 (unlike /api/gene_wiki).
        return {"found": False}
    sym = w["identity"]["symbol"]
    if not w["screens"]["n_total"]:
        # No "model" key on this branch — the frontend keys off its absence to suppress the
        # "— gpt-4.1, per phenotype over N screen hits" footer. No LLM call, nothing cached.
        return {"found": True, "symbol": sym, "n_screens": 0, "by_phenotype": [], "overall": ""}
    key = w["identity"]["gene_id"]
    if key in _SYNTH_CACHE:
        return _SYNTH_CACHE[key]
    client = _client(INTERPRET_MODEL)
    # max_tokens passed literally rather than via gen_kwargs(): this reply is a per-phenotype list,
    # far longer than the ~200-word syntheses gen_kwargs is sized for. 4000, not the 1200 this
    # prompt used against gpt-4.1 — Claude writes longer insights, and a JSON reply cut off at the
    # limit is unparseable. No temperature: claude-opus-4-7 rejects it (HTTP 400).
    data = client.chat_json(
        [{"role": "system", "content": SCREEN_SYS},
         {"role": "user", "content": _screen_prompt(w)}],
        max_tokens=4000)
    # Entries missing either field are dropped; the phenotype label is whatever the model echoed
    # and is NOT validated against the KB label set (the frontend colour-keys on it). Order is the
    # model's, which the system prompt asks to match the input order (screen count DESC).
    items = [{"phenotype": x.get("phenotype"), "insight": (x.get("insight") or "").strip()}
             for x in (data.get("by_phenotype") or []) if x.get("phenotype") and x.get("insight")]
    out = {"found": True, "symbol": sym, "model": client.model,
           "n_screens": w["screens"]["n_total"],
           "by_phenotype": items, "overall": (data.get("overall") or "").strip()}
    if items:
        _cache_put(_SYNTH_CACHE, key, out)  # never memoize a degenerate/empty answer
    return out


async def get_screen_analysis(gene: str, taxid: int = 9606) -> dict[str, Any]:
    """Per-phenotype LLM interpretation of ONLY this gene's BioGRID CRISPR-screen hits.

    Three distinct 200 shapes, all of which the frontend branches on — keep them apart:

      gene does not resolve  -> {"found": false}                       (a 200, NOT a 404)
      resolves, zero screens -> found/symbol/n_screens/by_phenotype/overall, NO "model" key
      the LLM ran            -> the same keys PLUS "model"

    Raises on any gateway/DB failure; the router turns that into the 502 contract.
    """
    return await run_in_threadpool(_screen_analysis_sync, gene, taxid)


# ═══════════════════════════ GET /api/reporter_explain ══════════════════════════════
#
# Per-reporter-row synthesis: extraction, not generation. Grounded ONLY in the gene's curated
# summary/partners and the abstracts of the screens' own papers.


def _norm_process(rationale: str | None, phenotype: str | None) -> str:
    """A reporter screen's rationale names the process it reads out
    (e.g. 'Negative regulators of NFkB signaling') — strip the screen's design
    framing down to the bare process, falling back to the GO-style phenotype.

    A private copy of the prototype's helper (web/app.py:307), deliberately NOT imported from
    services/explorer_gene.py even though an identical function lives there. That one is a
    teammate-owned private helper with a single in-module caller; importing it would mean a rename
    on their side turns into an ImportError at `import main`, taking every route down — theirs
    included. The prototype is self-contained here too, so this copy also keeps the two in step.
    """
    s = (rationale or "").strip()
    s = re.sub(r'^(positive|negative)\s+regulators?\s+of\s+', '', s, flags=re.I)
    s = re.sub(r'^regulators?\s+of\s+', '', s, flags=re.I)
    s = re.sub(r'^genes?\s+(involved\s+in|for|regulating)\s+', '', s, flags=re.I)
    return (s or phenotype or "unspecified process").strip()


REXPLAIN_SYS = (
    "You write 1-2 substantive sentences on whether a gene's KNOWN function connects to a specific "
    "cellular process it scored in — for a functional-genomics UI. Ground every functional claim "
    "ONLY in the provided KNOWN FUNCTION summary, known partners, or cited abstracts — never in "
    "outside knowledge of the gene. Give the reader a real takeaway; never pad with boilerplate like "
    "'the abstract does not mention X'."
)


def _reporter_explain_prompt(symbol: str, process: str, screen_rows: list[Any],
                             abstracts: list[dict[str, Any]], ann: dict[str, Any] | None,
                             dk: dict[str, Any] | None, partners: list[str]) -> str:
    summary = (ann or {}).get("summary") or ""
    L = [f"GENE: {symbol}", f"PROCESS (reporter read-out): {process}", "",
         "KNOWN FUNCTION (curated summary — your MAIN grounding): "
         + (summary or "(none on record — this gene is poorly characterized)")]
    if dk:
        L.append(f"DARKNESS: {dk.get('score', '?')}/10 ({dk.get('band', '?')}) — "
                 f"{dk.get('pubmed_count', '?')} PubMed papers")
    if partners:
        L.append("KNOWN PARTNERS (STRING): " + ", ".join(partners[:8]))
    L += ["", "ESTABLISHED SCREEN FACT (from the data — you MAY state it):"]
    for r in screen_rows:
        cite = f"PMID {r['pmid']}" if r["pmid"] else "unpublished"
        L.append(f"  • In {r['author'] or 'a'} ({cite}), knockout of {symbol} was an author-called "
                 f"hit in this '{process}' reporter screen.")
    if abstracts:
        L += ["", "SCREEN PAPER ABSTRACT(S) (extra source; cite by PMID):"]
        for a in abstracts:
            L.append(f"[PMID {a['pmid']}] {a['title']}\n{(a['abstract'] or '')[:900]}")
    L += ["",
          f"Write 1-2 substantive sentences on {symbol} and {process}:",
          f"- If the KNOWN FUNCTION / partners / abstracts clearly relate to {process}: explain HOW they "
          f"connect and note the screen hit is consistent with it (ground it, e.g. 'per its curated function').",
          f"- If {symbol} is poorly characterized (dark / no summary): frame this screen hit as the PRIMARY "
          f"evidence that it regulates {process} — a de-orphanization lead.",
          f"- If {symbol} is well-studied but its known roles do NOT involve {process}: say briefly this is "
          f"an association its established function does not explain (an uncharacterized link) — invent NO mechanism.",
          "RULES: base every functional claim ONLY on the material above, never on outside knowledge; cite "
          "abstracts as (PMID xxxxx). Mention only the aspect of the gene's function relevant to THIS "
          "process (or that none is) — do NOT recite its whole function list. No boilerplate, no hedging "
          "padding — give the actual takeaway."]
    return "\n".join(L)


def _reporter_explain_sync(symbol: str, screen_ids: list[str]) -> dict[str, Any]:
    if not screen_ids:
        # Unreachable through the router, which 400s "Missing symbol/screens." before calling.
        # Guarded anyway: an empty placeholder string renders `IN ()`, a syntax error on both
        # backends, and this keeps raw SQL out of the 502 text.
        raise ValueError("Missing symbol/screens.")
    # The ids are already capped at 6 by the router, and the cap is baked into the cache key.
    key = (symbol.lower(), tuple(sorted(screen_ids)))
    if key in _REXPLAIN_CACHE:
        return _REXPLAIN_CACHE[key]
    ph = ",".join("?" * len(screen_ids))
    # SQL audit: no literal '%' anywhere, and every '?' is a real placeholder (none sits inside a
    # quoted literal). The bare uppercase identifiers are unquoted, so Postgres folds them.
    rows = db_fetchall(
        f"""SELECT c.screen_id, c.pmid, m.AUTHOR AS author,
                   m.SCREEN_RATIONALE AS rat, m.PHENOTYPE AS phen,
                   m.ORGANISM_OFFICIAL AS org
            FROM screen_metadata_curated c JOIN screen_metadata m ON m.SCREEN_ID = c.screen_id
            WHERE c.screen_id IN ({ph})""", tuple(screen_ids))
    if not rows:
        # 200 with exactly three keys and NO "darkness" — the asymmetry with the full payload is
        # part of the contract. Not cached.
        return {"text": "", "sources": [], "process": ""}
    # rows[0] with no ORDER BY: Postgres guarantees nothing, so when the 6 screens do not share a
    # rationale/organism the chosen process and taxid can vary between runs (and the first answer
    # is then frozen into the cache). This is prototype behaviour — adding an ORDER BY would make
    # it deterministic but is a behaviour change, so it is flagged rather than done.
    process = _norm_process(rows[0]["rat"], rows[0]["phen"])
    taxid = ORG2TAX.get(rows[0]["org"], 9606)
    try:
        ext = ex.enrich(symbol, taxid)  # curated summary + darkness + STRING partners (cached)
    except Exception:
        logger.warning("reporter_explain: external enrichment failed for %s; continuing", symbol)
        ext = {}
    ann = (ext or {}).get("annotation") or {}
    dk = (ext or {}).get("darkness") or {}
    partners = [x["partner"] for x in (ext or {}).get("string_partners", [])]
    # Digits-only scrub, in DB row order, NOT de-duplicated: de-duplicating would reorder the list
    # and change pubmed_abstracts' cache key. NCBI returns one record per distinct id, so the
    # `sources` array cannot contain duplicates regardless.
    pmids = [d for d in (re.sub(r"\D", "", str(r["pmid"] or "")) for r in rows) if d]
    abstracts = ex.pubmed_abstracts(pmids) if pmids else []
    client = _client(INTERPRET_MODEL)
    text = client.chat(
        [{"role": "system", "content": REXPLAIN_SYS},
         {"role": "user", "content": _reporter_explain_prompt(symbol, process, rows, abstracts, ann, dk, partners)}],
        **gen_kwargs(client.model))
    out = {"text": text.strip(), "process": process, "darkness": dk.get("score"),
           "sources": [{"pmid": a["pmid"], "title": a["title"]} for a in abstracts]}
    _cache_put(_REXPLAIN_CACHE, key, out)
    return out


async def get_reporter_explain(symbol: str, screen_ids: list[str]) -> dict[str, Any]:
    """Grounded 1-2 sentence synthesis of a gene's role in one reporter's process.

    `screen_ids` must already be capped at 6 by the router (the cap is part of the cache key) and
    must be non-empty. Two 200 shapes: the full payload {text, process, darkness, sources}, and —
    when no id matches a curated screen — {text: "", sources: [], process: ""} with NO "darkness".
    """
    return await run_in_threadpool(_reporter_explain_sync, symbol, list(screen_ids))


# ═════════════════════════════ GET /api/net_predict ═════════════════════════════════
#
# Predict a gene's UNDISCOVERED function from RETICLE's OWN BioGRID co-essentiality network
# (net_edge): gpt-5 reasons over the focal gene's partners' real curated annotations and proposes
# a shared complex/pathway/process the focal gene is not yet annotated with. gpt-5 rather than
# gpt-4.1 because this is multi-step reasoning over a partner dossier, not text generation.


def _net_predict_partners(seed: str, tbl: str, context: str, organism: str,
                          top: int = 18) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The dossier: ALWAYS the union top-`top`, each partner graded by evidence tier against the seed.

    Deliberately NOT coessential_network_aaron._neighbourhood: this endpoint needs the per-edge
    `reciprocal` flag (the ⇄ tag in the prompt, the supporters payload, and the tier), and that
    helper's SELECT list does not carry it.

    This no longer mirrors the graph's reciprocal-only toggle, which REVERSES an earlier fix, so the
    reasoning matters. The original bug was that the dossier was assembled reciprocal-first no matter
    what was on screen — widen the graph to 29 partners, press Predict, and the model silently read 2.
    The fix made the dossier follow the toggle. That closed the honesty gap but kept the real damage:
    the toggle is a DISPLAY choice, and letting it decide what evidence the model reads means the 812
    of 5,269 human genes (15.4%) with exactly one reciprocal partner trip the "fewer than two
    annotated partners" early return every single time and can NEVER produce a prediction, while ~29
    one-directional partners sit unread. Median reciprocal degree is 2 against a median union degree
    of 29; only 2.6% of genes have the 18 reciprocal partners this dossier is sized for, against 86.7%
    in the union.

    So: read the union always, grade every partner, and REPORT the difference rather than hiding it
    (the original bug) or obeying it (the first fix). Two wanted side effects — the dossier is now
    reproducible across users regardless of their display state, which is why `view` no longer belongs
    in the cache key; and a partner arriving through the widened window is not treated as equal to a
    mutual-best one, because it carries its tier.
    """
    rows = db_fetchall(
        f"SELECT CASE WHEN gene_a=? THEN gene_b ELSE gene_a END nb, strength, reciprocal "
        f"FROM {tbl} WHERE context=? AND channel='coessential' AND (gene_a=? OR gene_b=?) "
        f"ORDER BY strength DESC LIMIT ?", (seed, context, seed, seed, top))
    if not rows:
        return [], {}
    ch = cohit_among([seed] + [r["nb"] for r in rows], organism)
    out: list[dict[str, Any]] = []
    hist: dict[int, int] = {}
    for r in rows:
        nb = r["nb"]
        c = ch.get((seed, nb) if seed <= nb else (nb, seed))
        tier = edge_tier(bool(r["reciprocal"]), c is not None)
        hist[tier] = hist.get(tier, 0) + 1
        out.append({"nb": nb, "strength": r["strength"], "reciprocal": int(r["reciprocal"]),
                    "tier": tier, "cohit_fold": c["fold"] if c else None})
    return out, {str(t): hist.get(t, 0) for t in (1, 2, 3, 4)}


def _net_predict_go_bp(gene_ids: list[int], cap: int = 8) -> dict[int, list[str]]:
    """gene_id -> [GO biological-process name, ...] (non-obsolete, positive-qualifier), per-gene cap.

    No ORDER BY on t.name, so WHICH `cap` terms survive depends on physical row order and can
    differ between the prototype's sqlite mirror and RDS. Prototype behaviour — do not add a
    tiebreaker: this list is also the novelty-exclusion set, so changing it changes which
    predictions survive.
    """
    if not gene_ids:
        return {}
    ph = ",".join("?" * len(gene_ids))
    out: dict[int, list[str]] = {}
    for row in db_fetchall(
        f"SELECT gg.gene_id gid, t.name name FROM kb_gene_go gg JOIN kb_go_term t ON t.go_id=gg.go_id "
        f"WHERE gg.gene_id IN ({ph}) AND t.namespace='biological_process' AND t.is_obsolete=0 "
        f"{_GO_POSITIVE} ORDER BY gg.gene_id", tuple(gene_ids)):
        lst = out.setdefault(row["gid"], [])
        if len(lst) < cap and row["name"] not in lst:
            lst.append(row["name"])
    return out


def _net_predict_pathways(gene_ids: list[int], cap: int = 5) -> dict[int, list[str]]:
    """gene_id -> [Reactome pathway name, ...], capped per gene (same ordering caveat as above)."""
    if not gene_ids:
        return {}
    ph = ",".join("?" * len(gene_ids))
    out: dict[int, list[str]] = {}
    for row in db_fetchall(
        f"SELECT gene_id gid, name FROM kb_gene_pathway WHERE gene_id IN ({ph}) ORDER BY gene_id",
        tuple(gene_ids)):
        lst = out.setdefault(row["gid"], [])
        if len(lst) < cap and row["name"] not in lst:
            lst.append(row["name"])
    return out


def _net_predict_oneliner(gene_ids: list[int], cap_chars: int = 220) -> dict[int, str]:
    """gene_id -> one short cleaned curated sentence (UniProt function first, else NCBI description).

    Genes with neither field are simply absent from the mapping.
    """
    if not gene_ids:
        return {}
    ph = ",".join("?" * len(gene_ids))
    out: dict[int, str] = {}
    for row in db_fetchall(
        f"SELECT gene_id gid, uniprot_function, description FROM kb_gene WHERE gene_id IN ({ph})",
        tuple(gene_ids)):
        text, _ = _clean_uniprot(row["uniprot_function"])
        text = text or row["description"]
        if text:
            out[row["gid"]] = (text[:cap_chars] + "…") if len(text) > cap_chars else text
    return out


NET_PREDICT_SYS = """You are a functional-genomics analyst working inside RETICLE. A FOCAL gene was mapped in \
RETICLE's OWN CRISPR co-essentiality network — edges are correlations between genes' knockout-fitness profiles \
across pooled BioGRID screens. Genes whose knockout-fitness profiles correlate tend to act in the SAME protein \
complex, the SAME pathway, or the SAME biological process. That co-essentiality relationship is your ONLY \
inference license.

You are given (1) the focal gene's strongest co-essential PARTNERS, each with its real curated annotations — \
GO biological-process terms, Reactome pathways, a one-line curated function, and its own knockout-fitness lean \
— and (2) the focal gene's OWN known functions, listed separately.

TASK: Decide whether the partners CONVERGE on a specific, named protein complex, pathway, or biological process. \
If they do, predict the focal gene's membership or role in it.

STRICT RULES (a broken rule makes that prediction useless — omit it instead):
1. Ground every prediction ONLY in the partner annotations given below. Invent no gene, complex, pathway, or \
term that is not present in the partner evidence. Use NO outside knowledge about any gene, including the focal \
gene — reason only from what is written below.
2. NOVELTY IS THE POINT: never predict anything already listed in the focal gene's KNOWN FUNCTION block, or an \
obvious synonym of it. If a convergence merely restates something the focal gene is already annotated with, \
drop it.
3. Every prediction MUST name the partners that support it (exact symbols from the list below). Name ALL of them \
and ONLY the ones that genuinely carry the claim — a partner you list is a partner a human will check. Two or \
more is the normal case; ONE is acceptable only when that single partner's evidence tier is [T1]. Do not pad the \
list to reach a count, and do not compute a confidence score yourself.
3b. EVIDENCE TIERS are marked on each partner below and they are measured, not decorative. Against CORUM \
same-complex membership: [T1] 46.4% · [T2] 22.4% · [T3] 17.7% · [T4] 4.9%, where a random annotated pair is 0.6%. \
A claim carried by two [T1] partners is worth far more than one carried by four [T4] partners. Weigh them \
accordingly, and prefer convergences that the higher-tier partners agree on.
4. Prefer the single most specific, defensible claim: a named complex beats a named pathway beats a vague \
process. Return 0-5 predictions — a short list of strong claims, not a long list of speculative ones.
5. If the partners do NOT converge on anything coherent, return an empty predictions list and say so plainly in \
"summary". Do not manufacture a guess to fill the list.
6. Never assert directionality, sign, or epistasis (no "activates", "represses", "required for", "sensitizes") \
— co-essentiality is undirected. Say the focal gene "likely participates in" or "is a candidate component of" \
the shared process.

Return ONLY a single JSON object of this exact shape, no prose, no markdown fences:
{"converges": true|false,
 "predictions": [{"prediction": "<specific complex/pathway/process name>",
                   "type": "complex"|"pathway"|"process",
                   "supporting_partners": ["<SYMBOL>", "<SYMBOL>", ...],
                   "rationale": "<1-2 sentences, grounded only in the partner annotations above>"}],
 "summary": "<one sentence overall — or why nothing converged>"}"""


def _net_predict_prompt(sym: str, organism: str, context_label: str, view: str,
                        own_bp: list[str], own_pw: list[str], own_fn: str | None,
                        partners: list[dict[str, Any]]) -> str:
    """partners: list of dicts {sym, strength, reciprocal, lean, go, pw, fn} in strength-desc order."""
    def esc_join(xs: list[str]) -> str:
        return "; ".join(xs) if xs else "(none on record)"
    lines = [
        f"FOCAL GENE: {sym} ({organism}) — co-essentiality context: {context_label} · view: {view}",
        "",
        f"KNOWN FUNCTION of {sym}  (do NOT predict any of these — this is the novelty-exclusion list):",
        f"  GO biological-process: {esc_join(own_bp)}",
        f"  Reactome pathways: {esc_join(own_pw)}",
        f"  Curated function: {own_fn or '(poorly characterized — no curated summary on record)'}",
        "",
        "CO-ESSENTIAL PARTNERS (your evidence — each is a REAL curated annotation set; "
        "r = knockout-fitness profile correlation, ⇄ = mutual-best):",
    ]
    any_annotated = False
    for p in partners:
        has_evidence = bool(p["go"] or p["pw"] or p["fn"])
        if not has_evidence:
            continue
        any_annotated = True
        tag = f"r={p['strength']:.2f}{' ⇄' if p['reciprocal'] else ''}"
        lean_txt = f", fitness: {p['lean']}" if p["lean"] else ""
        lines.append(f"### {p['sym']}  ({tag}{lean_txt})")
        lines.append(f"  GO biological-process: {esc_join(p['go'])}")
        lines.append(f"  Reactome pathways: {esc_join(p['pw'])}")
        lines.append(f"  Curated function: {p['fn'] or '(none)'}")
    if not any_annotated:
        lines.append("(no partner carries any curated annotation)")
    lines += ["", f"Now: identify the complex/pathway/process these partners converge on, and predict {sym}'s "
                  f"role in it — obeying the novelty rule. Return the JSON object now."]
    return "\n".join(lines)


def _net_predict_filter(data: dict, partners: list[dict], own_bp_norm: set[str],
                        own_pw_norm: set[str]) -> tuple[list[dict], int]:
    """The anti-hallucination layer — the part that makes this a prediction feature rather than a
    generation feature. Every check still runs at full strength; what changed is that a failed check
    now returns a VERDICT instead of deleting the prediction.

    Three things were wrong with deleting:
      * this layer is the product's whole claim to being auditable, and it fired in the dark. Nobody
        could show it had ever caught anything, which is indistinguishable from it not working;
      * the ">= 2 supporters" rule COUNTS HEADS where it should WEIGH EVIDENCE. One [T1] supporter
        recovers a CORUM complex 46.4% of the time; two [T4] supporters, 4.9% each. The old rule
        dropped the first and kept the second;
      * a request to show users material below the top confidence band is unanswerable while the
        weaker material never leaves the server.

    The checks, in order — order still matters:
      1. drop nameless predictions (the only remaining hard drop: there is nothing to label);
      2. CITATION CHECK — a cited symbol that is not an ANNOTATED partner is unverifiable. Note this
         is stricter than it used to be: partner_by_sym now covers only the partners the model was
         actually SHOWN. An unannotated partner contributes no annotation to reason from, so a
         citation of one cannot be evidence for anything — it is a name the model produced without
         having read a thing about it, which is the definition this check exists to catch;
      3. dedupe, preserving the model's order;
      4. NOVELTY RE-CHECK — exact match (strip + lower) against the focal gene's own GO
         biological-process terms and Reactome pathways. The system prompt asks for novelty; the
         model is NOT trusted to comply. Exact match only, no fuzzy/synonym matching, over the same
         8 GO + 5 Reactome the model was shown;
      5. WEIGH the survivors into a verdict rather than counting them.

    Returns (predictions, n_unverifiable_citations). Predictions keep the model's original order; only
    each prediction's own supporters are sorted, best tier first then strength descending.
    """
    partner_by_sym = {p["sym"]: p for p in partners if p["go"] or p["pw"] or p["fn"]}
    preds_out = []
    n_ghost = 0
    for pred in (data.get("predictions") or []):
        name = (pred.get("prediction") or "").strip()
        if not name:
            continue
        raw = list(dict.fromkeys(s for s in (pred.get("supporting_partners") or [])
                                 if isinstance(s, str) and s.strip()))
        cited = [s for s in raw if s in partner_by_sym]
        ghosts = [s for s in raw if s not in partner_by_sym]
        n_ghost += len(ghosts)
        supporters = [{"symbol": s, "strength": partner_by_sym[s]["strength"],
                       "reciprocal": partner_by_sym[s]["reciprocal"],
                       "tier": partner_by_sym[s]["tier"],
                       "cohit_fold": partner_by_sym[s]["cohit_fold"]} for s in cited]
        # stable: ties keep the model's cited order
        supporters.sort(key=lambda x: (x["tier"], -x["strength"]))
        best_tier = min((s["tier"] for s in supporters), default=4)
        n_strong = sum(1 for s in supporters if s["tier"] <= 2)

        if name.lower().strip() in own_bp_norm or name.lower().strip() in own_pw_norm:
            verdict = "rejected:not-novel"
        elif not supporters:
            verdict = "rejected:no-verifiable-support"
        elif len(supporters) == 1:
            # Weight, not headcount. A lone [T1] supporter is a stronger statement than a pair of
            # [T4]s, so it is promoted rather than demoted — the one place the old rule was not
            # merely blunt but backwards.
            verdict = "verified" if best_tier == 1 else "single-supporter"
        else:
            verdict = "verified"

        strengths = [s["strength"] for s in supporters]
        n_recip = sum(1 for s in supporters if s["reciprocal"])
        confidence = ("high" if n_strong >= 2 or (best_tier == 1 and len(supporters) >= 2)
                      else "moderate" if best_tier <= 3
                      else "low")
        # separators are U+00B7 MIDDLE DOT and the range dash is U+2013 EN DASH — rendered literally
        convergence = ((f"{len(supporters)} partner{'' if len(supporters) == 1 else 's'} · "
                        f"r {min(strengths):.2f}–{max(strengths):.2f}"
                        + (f" · {n_recip} mutual-best" if n_recip else "")
                        + f" · best tier T{best_tier}") if supporters else "no verifiable support")
        preds_out.append({
            "prediction": name,
            # membership test runs on the raw value: a missing key or anything else -> "process"
            "type": pred.get("type") if pred.get("type") in ("complex", "pathway", "process") else "process",
            "verdict": verdict, "evidence_tier": best_tier if supporters else None,
            "confidence": confidence, "convergence": convergence,
            "rationale": (pred.get("rationale") or "").strip(), "supporting_partners": supporters,
            "unverifiable_citations": ghosts,
        })
    return preds_out, n_ghost


def _assemble_partners(partner_syms: list[str], partner_meta: dict[str, dict[str, Any]],
                       resolved: dict[str, int], lean: dict[str, float],
                       go_by_gid: dict[int, list[str]], pw_by_gid: dict[int, list[str]],
                       fn_by_gid: dict[int, str]) -> list[dict[str, Any]]:
    """One dict per partner, carrying both its network evidence (strength / reciprocal / tier /
    co-hit fold) and its curated annotations. A partner that did not resolve to a KB gene_id keeps
    empty annotations rather than being dropped — it still exists in the network, it just cannot
    contribute evidence, and _net_predict_filter treats that distinction as load-bearing."""
    out = []
    for sym in partner_syms:
        gid = resolved.get(sym)
        out.append({
            "sym": sym,
            "strength": partner_meta[sym]["strength"],
            "reciprocal": partner_meta[sym]["reciprocal"],
            "tier": partner_meta[sym]["tier"],
            "cohit_fold": partner_meta[sym]["cohit_fold"],
            "lean": _lean_label(lean.get(sym)),
            "go": go_by_gid.get(gid, []) if gid else [],
            "pw": pw_by_gid.get(gid, []) if gid else [],
            "fn": fn_by_gid.get(gid) if gid else None,
        })
    return out


def _net_predict_sync(gene: str, context: str, organism: str, top: int, reciprocal_only: bool = True) -> dict[str, Any] | None:
    taxid = 10090 if organism == "mouse" else 9606
    tbl = _edge_table(organism)

    # The seed probe does NOT filter channel='coessential' while the partner query does, so a gene
    # whose only edges are on another channel resolves here and then yields no partners — both
    # paths return None and the router renders the same 404. Faithful to the prototype.
    seed = _resolve_seed(gene.strip(), tbl, context)
    if seed is None:
        return None

    prows, partner_tiers = _net_predict_partners(seed, tbl, context, organism, top=top)
    if not prows:
        return None

    partner_syms = [r["nb"] for r in prows]
    # float()/bool() before round(): psycopg2 returns numerics as Decimal, and round() keeps a
    # Decimal — which breaks both the f"{...:.2f}" prompt tags and FastAPI's JSON encoder.
    partner_meta = {r["nb"]: {"strength": round(float(r["strength"]), 3),
                              "reciprocal": bool(r["reciprocal"]),
                              "tier": int(r["tier"]),
                              "cohit_fold": r["cohit_fold"]} for r in prows}
    # How much of this dossier the caller's graph filter was hiding. Reported, never acted on: the
    # model reads the union either way (see _net_predict_partners).
    n_beyond_view = sum(1 for r in prows if not r["reciprocal"]) if reciprocal_only else 0

    seed_r = _kb_resolve(seed, taxid)
    resolved: dict[str, int] = {}  # symbol -> gene_id, for partners that exist in the KB
    for sym in partner_syms:
        r = _kb_resolve(sym, taxid)
        if r:
            resolved[sym] = r["gene_id"]
    n_unresolved = len(partner_syms) - len(resolved)

    lean = _fitness_lean([seed] + partner_syms, organism)

    all_gids = list(resolved.values()) + ([seed_r["gene_id"]] if seed_r else [])
    go_by_gid = _net_predict_go_bp(all_gids)
    pw_by_gid = _net_predict_pathways(all_gids)
    fn_by_gid = _net_predict_oneliner(all_gids)

    own_bp: list[str] = []
    own_pw: list[str] = []
    own_fn: str | None = None
    if seed_r:
        own_bp = go_by_gid.get(seed_r["gene_id"], [])
        own_pw = pw_by_gid.get(seed_r["gene_id"], [])
        own_fn = fn_by_gid.get(seed_r["gene_id"])
    own_bp_norm = {t.strip().lower() for t in own_bp}
    own_pw_norm = {t.strip().lower() for t in own_pw}

    partners = _assemble_partners(partner_syms, partner_meta, resolved, lean,
                                  go_by_gid, pw_by_gid, fn_by_gid)
    n_annotated = sum(1 for p in partners if p["go"] or p["pw"] or p["fn"])
    view = "union"  # always, now — see _net_predict_partners

    if n_annotated < 2:
        # Genuinely nothing to reason over — don't spend an LLM call on it. This branch neither reads
        # nor writes the cache and never constructs a client, hence model: None. The message is now a
        # real annotation-coverage statement: the dossier already read the full union, so the old
        # "widen the view" advice would be a lie — there is no wider view left.
        return {"found": True, "symbol": seed, "organism": organism, "context": context,
                "context_label": NET_CTX_LABELS.get(context, context), "view": view,
                "n_partners": len(partner_syms), "n_annotated_partners": n_annotated,
                "n_unresolved": n_unresolved, "partner_tiers": partner_tiers,
                "n_beyond_view": n_beyond_view, "model": None, "converges": False,
                "predictions": [], "no_call": True,
                "summary": f"Only {n_annotated} of this gene's {len(partner_syms)} co-essential "
                           "partners carries a curated function on record, so no prediction was "
                           "attempted. This is an annotation-coverage limit, not a filter — the "
                           "dossier already reads every partner, mutual-best or not."}

    # Keyed on the KB gene_id when the seed resolved, else the resolved SYMBOL — heterogeneous by
    # design. `top` is deliberately NOT part of the key. Looked up AFTER all the DB work but
    # BEFORE the LLM call, exactly as in the prototype.
    # Everything that changes the answer belongs in the key. It was (gene, organism, context)
    # only, so switching the model or editing the prompt let a warm worker keep serving the
    # previous answer under the new model's name.
    # `view` used to be in the key and no longer needs to be: the dossier is the union regardless of
    # the caller's display state, which is itself the point — two users on the same gene now get the
    # same answer.
    cache_key = (seed_r["gene_id"] if seed_r else seed, organism, context,
                 NET_PREDICT_MODEL, NET_PREDICT_PROMPT_VERSION)
    if cache_key in _NET_PRED_CACHE:
        return _NET_PRED_CACHE[cache_key]

    prompt = _net_predict_prompt(seed, organism, NET_CTX_LABELS.get(context, context), view,
                                 own_bp, own_pw, own_fn, partners)
    client = _client(NET_PREDICT_MODEL)
    # 3000 rather than the 600 default: the reply is a JSON list of predictions with rationales,
    # and a truncated one is unparseable JSON rather than a short answer.
    data = client.chat_json([{"role": "system", "content": NET_PREDICT_SYS},
                             {"role": "user", "content": prompt}], **gen_kwargs(NET_PREDICT_MODEL, max_tokens=3000))

    preds_out, n_ghost = _net_predict_filter(data, partners, own_bp_norm, own_pw_norm)
    tally: dict[str, int] = {"verified": 0, "single-supporter": 0,
                             "rejected:not-novel": 0, "rejected:no-verifiable-support": 0}
    for p in preds_out:
        tally[p["verdict"]] = tally.get(p["verdict"], 0) + 1

    out = {"found": True, "symbol": seed, "organism": organism, "context": context,
           "context_label": NET_CTX_LABELS.get(context, context), "view": view,
           "n_partners": len(partner_syms), "n_annotated_partners": n_annotated,
           "n_unresolved": n_unresolved, "partner_tiers": partner_tiers,
           "n_beyond_view": n_beyond_view, "model": client.model,
           # `converges` is derived SERVER-SIDE and stays the STRICT reading — the model's own
           # top-level "converges" is read by nobody, and the headline renders from this, so
           # loosening it to include single-supporter would restate a hunch as a finding.
           "converges": any(p["verdict"] == "verified" for p in preds_out),
           "predictions": preds_out, "verdicts": tally,
           "n_unverifiable_citations": n_ghost,
           "summary": (data.get("summary") or "").strip()}
    if preds_out:
        _cache_put(_NET_PRED_CACHE, cache_key, out)  # a run that converged on nothing is not cached
    return out


async def get_net_predict(gene: str, context: str, organism: str = "human", top: int = 18,
                          reciprocal_only: bool = True) -> dict[str, Any] | None:
    """Guilt-by-association from RETICLE's OWN net_edge network (not STRING/DepMap).

    Returns None when the seed is not in the network for this context, or when it has no
    co-essential partners at all — the router renders both as the same 404. Otherwise always a 200
    payload; note the short-circuit branch (fewer than two partners carry any curated annotation)
    returns model: None, converges: false, predictions: [] WITHOUT spending a model call.

    `reciprocal_only` is the caller's DISPLAY state. It no longer selects the dossier — that is
    always the tier-graded union — and only feeds the reported `n_beyond_view`.
    """
    return await run_in_threadpool(_net_predict_sync, gene, context, organism, top,
                                   reciprocal_only)


# ═══════════════════════════════ POST /api/interpret ════════════════════════════════
#
# The Explorer's "AI reading": RAG over external sources + PubMed abstracts, grounded in the gene
# payload the client already received from GET /api/gene. Issues no SQL of its own.


SYS_PROMPT = """You are a functional-genomics analyst. You are given a gene's behavior across pooled \
CRISPR screens (RETICLE's own harmonized data), its "darkness" rating, its known function and \
partners, and a few PubMed abstracts. Synthesize them into one grounded reading.

RETICLE axis: percentile -1 = knockout DELETERIOUS / gene essential; +1 = knockout ADVANTAGEOUS / \
loss promotes selection; 0 = no effect. Three assay domains:
- FITNESS  : baseline growth/viability — where ESSENTIALITY is read.
- STRESS   : survival under an applied pressure (drug/virus) — conditional; can diverge from fitness.
- REPORTER : marker (FACS) screens — specific functional probes (e.g. "regulators of mitophagy"),
             used to name the PROCESS the gene acts in, not essentiality.

Write 140-200 words, plain active prose, no headers/bullets:
(1) the FITNESS verdict grounded in the median/spread; (2) any STRESS divergence; (3) the functional
process suggested by REPORTER probes; (4) reconcile with KNOWN FUNCTION and the PubMed abstracts —
cite supporting papers as (PMID xx…).
DARK-MATTER PAYOFF: if the gene is poorly studied (high darkness) yet behaves like its known/known-
pathway partners in the screens, say so explicitly and frame it as a de-orphanization candidate with
a concrete, testable prediction. If the abstracts are sparse because the gene is dark, say that plainly
rather than inventing literature. Never fabricate a PMID — only cite ones provided."""


def _signal_lines(p: dict[str, Any]) -> list[str]:
    def blk(name: str, b: dict[str, Any] | None) -> str:
        if not b:
            return f"{name}: (no screens)"
        return (f"{name}: n={b['n']}, hits={b['n_hits']}, median={b['median']:+.3f}, "
                f"IQR=[{b['p25']:+.3f},{b['p75']:+.3f}], lean={b['lean']}")
    def ctx(items: list[dict[str, Any]]) -> str:
        return "; ".join(f"{i['cell_line']} ({i['screen_type'] or 'screen'}, {i['percentile']:+.2f})"
                         for i in items[:5])
    out = [blk("FITNESS", p["fitness"])]
    # STRESS: per-condition facts, never a pooled median (magnitudes aren't comparable)
    st = p["stress"]
    if not st:
        out.append("STRESS: (no screens)")
    else:
        out.append(f"STRESS: n={st['n']}, author-called hits={st['n_hits']} "
                   f"— direction is per specific condition, NOT pooled")
        for r in (st.get("ledger") or [])[:6]:
            out.append(f"  {r['condition']} [{r['class']}] -> {r['direction']} "
                       f"({r['n_agree']}/{r['n_screens']} screens agree)")
    if p["fitness"]:
        out.append(f"  fitness most-essential: {ctx(p['fitness']['most_essential'])}")
        out.append(f"  fitness most-advantageous: {ctx(p['fitness']['most_advantageous'])}")
    rep = p["reporter"]
    if rep["n"]:
        procs = "; ".join(f"{r['process']} ({r['n_screens']} screen"
                          f"{'s' if r['n_screens'] > 1 else ''})"
                          for r in rep.get("ledger", [])[:8])
        out.append(f"REPORTER: n={rep['n']} marker screens — gene regulates: {procs or '(no called hits)'}")
    return out


def build_rag_prompt(p: dict[str, Any], ext: dict[str, Any],
                     abstracts: list[dict[str, Any]]) -> str:
    sym, org = p["symbol"], p["organism"]
    ann = (ext or {}).get("annotation") or {}
    dk = (ext or {}).get("darkness") or {}
    partners = [x["partner"] for x in (ext or {}).get("string_partners", [])]
    lines = [f"GENE: {sym}  ({org})"]
    if dk:
        lines.append(f"DARKNESS: {dk['score']}/10 ({dk['band']}) — {dk['pubmed_count']} PubMed papers, "
                     f"{dk['go_total']} GO terms")
    lines.append("KNOWN FUNCTION: " + (ann.get("summary") or "(no curated summary — poorly characterized)"))
    if partners:
        lines.append("KNOWN PARTNERS (STRING): " + ", ".join(partners))
    lines.append("\nRETICLE SCREEN SIGNAL")
    lines += _signal_lines(p)
    lines.append("\nPUBMED ABSTRACTS (evidence — cite by PMID):")
    if abstracts:
        for a in abstracts:
            lines.append(f"[PMID {a['pmid']}] {a['title']}\n{a['abstract'][:600]}")
    else:
        lines.append("(none retrieved — consistent with a poorly studied gene)")
    return "\n".join(lines)


def _interpret_sync(p: dict) -> dict[str, Any]:
    sym = p["symbol"]
    # An unknown/missing organism silently becomes human — the prototype does not error on it.
    # str() rather than passing the raw value: the body is client-supplied, so `organism` can be
    # any JSON type, and ORG2TAX is keyed by str.
    taxid = ORG2TAX.get(str(p.get("organism") or ""), 9606)
    # Order is load-bearing: enrich() first, because its gene_annotation result is reused by
    # darkness() so the annotation is fetched once. Every source fails soft (None/[]), which is
    # what produces the "(no curated summary — poorly characterized)" dark-gene path instead of an
    # error — do not "improve" that by raising.
    ext = ex.enrich(sym, taxid)
    # The positional 5 is load-bearing: it is not the function's default (6) and it is part of the
    # external-source cache key ("pmids:<taxid>:<sym>:5").
    abstracts = ex.pubmed_abstracts(ex.pubmed_pmids(sym, taxid, 5))
    client = _client(INTERPRET_MODEL)
    text = client.chat(
        [{"role": "system", "content": SYS_PROMPT},
         {"role": "user", "content": build_rag_prompt(p, ext, abstracts)}],
        **gen_kwargs(client.model),
    )
    # `sources` is every abstract RETRIEVED, in NCBI efetch order — not the PMIDs the model
    # actually cited — and the abstract text itself is deliberately not echoed back.
    return {"model": client.model, "text": text.strip(),
            "sources": [{"pmid": a["pmid"], "title": a["title"]} for a in abstracts]}


async def get_interpret(payload: dict) -> dict[str, Any]:
    """One grounded 140-200 word reading of a gene's cross-screen behaviour.

    `payload` is the FULL gene payload from GET /api/gene. Keys actually read: symbol (required,
    bare index), organism, fitness, stress, reporter — a missing one raises KeyError, which the
    router turns into the prototype's 502 (e.g. "Interpretation unavailable: 'symbol'"). No result
    caching: every POST is a paid gateway call, as in the prototype.
    """
    return await run_in_threadpool(_interpret_sync, payload)
