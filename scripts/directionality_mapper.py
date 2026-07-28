#!/usr/bin/env python3
"""
RETICLE — Directionality Mapper (production, warehouse-native)

For screens the deterministic harmonizer could not sign (screen_harmonization
score_basis tagged AMBIGUOUS_SELECTION, or UNRESOLVED), read the BioGRID curator
text (NOTES + SIGNIFICANCE_CRITERIA + RATIONALE) with an LLM and decide the sign
on RETICLE's unified loss-of-function axis.

Unified axis (the LLM must align to this):
  +1 = loss-of-function (knockout / inactivation) is ADVANTAGEOUS — guides ENRICHED
  -1 = the gene is ESSENTIAL / required for the phenotype — guides DEPLETED
  (CRISPRa/perturbation direction is folded into the LLM's final sign.)

INPUTS (all warehouse-native — no prototype paths, no SQLite):
  - target screens  : RDS screen_harmonization for a data version
  - screen metadata : $DATA_DIR/screen_metadata_<organism>.json (same files staging
                      and harmonize_warehouse read; via harmonize_warehouse.load_metadata)
  - the LLM         : scripts/llm_gateway.LLMGateway (config-driven model)

OUTPUT (versioned, in the database — NOT a JSON file):
  - screen_directionality (one row per version_id, screen_id): mode/sign/columns/
    confidence/evidence/status. Only status='auto' rows are later applied by
    harmonize_warehouse.py --apply-directionality. needs_review rows await humans.

Usage:
  python3 directionality_mapper.py --version 8 --show-prompt        # first prompt, no LLM
  python3 directionality_mapper.py --version 8 --dry-run            # list targets, no LLM/writes
  python3 directionality_mapper.py --version 8 --limit 5            # live, 5 screens
  python3 directionality_mapper.py --version 8                      # all ambiguous screens
  #   --model claude-opus-5 | gpt-5.5 | gemini-2.5-pro   (default from llm_config.json)
Needs ~/.pgpass (DB); live runs also need the WashU VPN + LLM secrets.
"""

import argparse
import json
import time

import psycopg2

from config import Config
import harmonization_core as hc
from harmonize_warehouse import load_metadata   # $DATA_DIR/screen_metadata_<organism>.json loader
from llm_gateway import LLMGateway

CONFIDENCE_THRESHOLD = 0.7
PROMPT_VERSION = "dir-v1.0"
LLM_RATE_LIMIT = 0.4


# --------------------------------------------------------------------------
# Warehouse I/O
# --------------------------------------------------------------------------

def _connect():
    params = Config.get_psycopg2_params()
    params["sslmode"] = "require"
    return psycopg2.connect(**params)


def resolve_organism(conn, version_id):
    cur = conn.cursor()
    cur.execute("SELECT organism FROM data_load_version WHERE version_id = %s", (version_id,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"version_id {version_id} not found in data_load_version")
    return row[0]


def target_screens(conn, version_id):
    """[(screen_id, biogrid_screen_id, is_unresolved), ...] for screens whose
    deterministic harmonization could not fix a direction (from screen_harmonization)."""
    cur = conn.cursor()
    cur.execute(
        "SELECT screen_id, biogrid_screen_id, score_basis FROM screen_harmonization "
        "WHERE version_id = %s AND (score_basis LIKE %s OR score_basis = %s) "
        "ORDER BY biogrid_screen_id",
        (version_id, "%AMBIGUOUS_SELECTION%", "UNRESOLVED"),
    )
    return [(sid, str(bid), basis == "UNRESOLVED") for sid, bid, basis in cur.fetchall()]


def already_resolved(conn, version_id):
    cur = conn.cursor()
    cur.execute("SELECT screen_id FROM screen_directionality WHERE version_id = %s", (version_id,))
    return {r[0] for r in cur.fetchall()}


def upsert_decision(conn, version_id, screen_id, biogrid_id, decision, status,
                    is_unresolved, model, raw):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO screen_directionality
            (version_id, screen_id, biogrid_screen_id, mode, sign, positive_column,
             negative_column, confidence, evidence, status, is_unresolved,
             llm_model, prompt_version, raw_llm_output, resolved_at, is_current)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,TRUE)
        ON CONFLICT (version_id, screen_id) DO UPDATE SET
            biogrid_screen_id=EXCLUDED.biogrid_screen_id, mode=EXCLUDED.mode,
            sign=EXCLUDED.sign, positive_column=EXCLUDED.positive_column,
            negative_column=EXCLUDED.negative_column, confidence=EXCLUDED.confidence,
            evidence=EXCLUDED.evidence, status=EXCLUDED.status,
            is_unresolved=EXCLUDED.is_unresolved, llm_model=EXCLUDED.llm_model,
            prompt_version=EXCLUDED.prompt_version, raw_llm_output=EXCLUDED.raw_llm_output,
            resolved_at=CURRENT_TIMESTAMP, is_current=TRUE
    """, (version_id, screen_id, biogrid_id, decision["mode"], decision["sign"],
          decision["positive_column"], decision["negative_column"],
          decision["confidence"], decision["evidence"], status, is_unresolved,
          model, PROMPT_VERSION, raw))
    conn.commit()


def score_layout(bio):
    """{'SCORE.1': 'MaGeCK Score', ...} (non-empty only)."""
    out = {}
    for i in range(1, 6):
        t = str(bio.get(f"SCORE.{i}_TYPE", "") or "").strip()
        if t and t != "-":
            out[f"SCORE.{i}"] = t
    return out


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a CRISPR screen curator for the RETICLE database. Your one job is to \
determine the SIGN (directionality) of a screen's score on RETICLE's unified loss-of-function axis.

UNIFIED AXIS (memorize this):
  +1  = loss-of-function (gene knockout / inactivation) is ADVANTAGEOUS — guides are
        ENRICHED in the selected population; the gene normally PROMOTES the bad outcome
        (e.g. it is required for the cytotoxic/selective pressure to kill cells).
  -1  = the gene is ESSENTIAL / REQUIRED for the selected phenotype — guides are DEPLETED
        (e.g. core-essential genes in a viability screen).

The screens you receive have an UNSIGNED significance score (a p-value, FDR, STARS/CasTLE/RSA
score, or an RRA/MaGeCK p-value). The number alone does NOT tell you the direction — you must
read the curator's NOTES, the SIGNIFICANCE_CRITERIA, and the RATIONALE to decide.

Decide ONE of three modes:

1. SINGLE — there is one effective significance column and a single global sign applies.
   Output "sign": +1 or -1 = the sign a HIT/significant gene should get on the unified axis.

2. PAIR — the layout has TWO analyses of opposite direction (e.g. two columns both named
   "MaGeCK Score", one for depletion and one for enrichment; the criteria reference two
   different Score.N). Identify which column is the ENRICHED/positive side and which is the
   DEPLETED/negative side.
   Output "positive_column" (the +1 / enrichment side) and "negative_column" (the -1 / depletion side),
   each as "SCORE.N".

3. UNDEFINED — the polarity genuinely cannot be determined from the provided text.

Rules:
- Quote the EXACT phrase from NOTES/criteria/rationale that justifies your call in "evidence".
  If you cannot point to a concrete phrase, the answer is UNDEFINED.
- "confidence" reflects how unambiguous that evidence is (1.0 = explicit statement of sign↔biology).
- Account for the perturbation type yourself: a CRISPRa/activation screen inverts the meaning
  relative to knockout. Your sign is the FINAL sign on the loss-of-function axis.

Return ONLY a single valid JSON object with exactly these keys:
{
  "mode": "SINGLE" | "PAIR" | "UNDEFINED",
  "sign": 1 | -1 | null,
  "positive_column": "SCORE.N" | null,
  "negative_column": "SCORE.N" | null,
  "confidence": <float 0.0-1.0>,
  "evidence": "<verbatim supporting phrase, or empty>"
}"""

USER_TEMPLATE = """SCREEN_ID: {screen_id}
PERTURBATION (METHODOLOGY): {methodology}
LIBRARY_TYPE: {library_type}
SCREEN_TYPE: {screen_type}
PHENOTYPE: {phenotype}
EXPERIMENTAL_SETUP: {setup}
SCORE COLUMN LAYOUT: {layout}
SIGNIFICANCE_CRITERIA: {criteria}
SCREEN_RATIONALE: {rationale}
NOTES: {notes}"""


def build_prompt(screen_id, bio):
    layout = score_layout(bio)
    layout_str = ", ".join(f"{k}={v}" for k, v in layout.items()) or "-"
    return USER_TEMPLATE.format(
        screen_id=screen_id,
        methodology=bio.get("METHODOLOGY") or "-",
        library_type=bio.get("LIBRARY_TYPE") or "-",
        screen_type=bio.get("SCREEN_TYPE") or "-",
        phenotype=bio.get("PHENOTYPE") or "-",
        setup=bio.get("EXPERIMENTAL_SETUP") or "-",
        layout=layout_str,
        criteria=bio.get("SIGNIFICANCE_CRITERIA") or "-",
        rationale=bio.get("SCREEN_RATIONALE") or "-",
        notes=(bio.get("NOTES") or "-")[:1500],
    )


# --------------------------------------------------------------------------
# Decision parsing / classification
# --------------------------------------------------------------------------

def parse_decision(d, layout):
    """Sanity-check the model's already-parsed JSON object (from chat_json).
    Returns a normalized dict; UNDEFINED / confidence 0 on any structural problem."""
    if not isinstance(d, dict):
        return _undef("model returned non-JSON")
    mode = str(d.get("mode", "")).upper()
    try:
        conf = max(0.0, min(1.0, float(d.get("confidence", 0.0))))
    except (TypeError, ValueError):
        conf = 0.0
    evidence = str(d.get("evidence", "") or "")

    if mode == "SINGLE":
        sign = d.get("sign")
        if sign not in (1, -1, 1.0, -1.0):
            return _undef("SINGLE without valid sign")
        return {"mode": "SINGLE", "sign": int(sign), "positive_column": None,
                "negative_column": None, "confidence": conf, "evidence": evidence}

    if mode == "PAIR":
        pos, neg = d.get("positive_column"), d.get("negative_column")
        if pos not in layout or neg not in layout or pos == neg:
            return _undef(f"PAIR with columns not in layout ({pos},{neg})")
        return {"mode": "PAIR", "sign": None, "positive_column": pos,
                "negative_column": neg, "confidence": conf, "evidence": evidence}

    return {"mode": "UNDEFINED", "sign": None, "positive_column": None,
            "negative_column": None, "confidence": conf, "evidence": evidence}


def _undef(reason):
    return {"mode": "UNDEFINED", "sign": None, "positive_column": None,
            "negative_column": None, "confidence": 0.0, "evidence": "", "parse_note": reason}


def classify_status(decision, is_unresolved):
    if is_unresolved:
        return "binary_only"
    if decision["mode"] == "UNDEFINED":
        return "needs_review"
    if decision["confidence"] < CONFIDENCE_THRESHOLD:
        return "needs_review"
    return "auto"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="LLM directionality resolution -> screen_directionality (DB)")
    ap.add_argument("--version", type=int, required=True,
                    help="data_load_version_id whose ambiguous screens to resolve")
    ap.add_argument("--model", type=str, default=None,
                    help="Model key from scripts/llm_config.json (default: config default_model). "
                         "e.g. claude-opus-5, gpt-5.5, gemini-2.5-pro")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--screen-ids", type=str, default="", help="comma-separated biogrid ids to restrict to")
    ap.add_argument("--resume", action="store_true", help="skip screens already in screen_directionality")
    ap.add_argument("--dry-run", action="store_true", help="list targets, no LLM, no writes")
    ap.add_argument("--show-prompt", action="store_true", help="print the first prompt and exit")
    args = ap.parse_args()

    conn = _connect()
    organism = resolve_organism(conn, args.version)
    targets = target_screens(conn, args.version)

    if args.screen_ids:
        want = {s.strip() for s in args.screen_ids.split(",") if s.strip()}
        targets = [t for t in targets if t[1] in want]
    if args.resume:
        done = already_resolved(conn, args.version)
        targets = [t for t in targets if t[0] not in done]
    if args.limit:
        targets = targets[:args.limit]

    metadata = load_metadata(organism)   # $DATA_DIR/screen_metadata_<organism>.json
    n_amb = sum(1 for _, _, u in targets if not u)
    n_unr = sum(1 for _, _, u in targets if u)
    log(f"version={args.version} organism={organism}  targets={len(targets)} "
        f"(AMBIGUOUS={n_amb}, UNRESOLVED={n_unr})")

    if not targets:
        log("No target screens (no AMBIGUOUS_SELECTION / UNRESOLVED in screen_harmonization).")
        log("  Run harmonize_warehouse.py for this version first so ambiguous screens are tagged.")
        conn.close()
        return

    def get_bio(bid):
        return metadata.get(hc.normalize_screen_id(bid)) or {}

    if args.show_prompt:
        bid = targets[0][1]
        print("\n--- SYSTEM ---\n" + SYSTEM_PROMPT)
        print("\n--- USER ---\n" + build_prompt(bid, get_bio(bid)))
        conn.close()
        return

    if args.dry_run:
        for sid, bid, u in targets:
            print(f"  {'UNRESOLVED' if u else 'AMBIGUOUS '} screen_id={sid} biogrid={bid} "
                  f"layout={score_layout(get_bio(bid))}")
        conn.close()
        return

    gw = LLMGateway(model=args.model)
    model_name = args.model or gw.default_model
    log(f"Model: {model_name}")
    try:
        gw.chat([{"role": "user", "content": "ping"}], max_tokens=5)
    except Exception as e:
        log("LLM preflight FAILED — aborting, nothing written.")
        log(f"  {e}")
        log("  If 403: connect the WashU VPN and ensure RETICLE/secure_api secrets are reachable.")
        conn.close()
        return

    counts = {"auto": 0, "needs_review": 0, "binary_only": 0}
    for i, (sid, bid, is_unr) in enumerate(targets, 1):
        bio = get_bio(bid)
        layout = score_layout(bio)
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(bid, bio)}]
        try:
            d = gw.chat_json(messages, model=args.model, max_tokens=512)
            raw = json.dumps(d, ensure_ascii=False)
            decision = parse_decision(d, layout)
        except Exception as e:
            log(f"  ! screen {bid} LLM error: {e}")
            decision = _undef(f"LLM error: {e}")
            raw = ""
        status = classify_status(decision, is_unr)
        counts[status] += 1
        upsert_decision(conn, args.version, sid, bid, decision, status, is_unr, model_name, raw)
        log(f"[{i}/{len(targets)}] screen {bid}: {decision['mode']} "
            f"conf={decision['confidence']:.2f} -> {status}")
        time.sleep(LLM_RATE_LIMIT)

    log("=== Summary (written to screen_directionality) ===")
    log(f"  auto={counts['auto']}  needs_review={counts['needs_review']}  binary_only={counts['binary_only']}")
    if counts["needs_review"]:
        log(f"  Human adjudication needed: SELECT * FROM screen_directionality "
            f"WHERE version_id={args.version} AND status='needs_review';")
    conn.close()


if __name__ == "__main__":
    main()
