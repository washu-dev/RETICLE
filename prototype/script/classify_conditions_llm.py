"""
classify_conditions_llm.py — LLM resolution of the condition-facet long tail.
============================================================================
classify_conditions.py resolves ~96% of screens by rule. The residual it writes
to processed_data/facets_needs_llm.csv (condition_class signal / binding /
unknown — where growth direction or readout can't be set deterministically) is
handed here. For each screen the LLM **EXTRACTS** from BioGRID's CONDITION_NAME +
NOTES — the authors almost always STATE the convention — rather than inferring
it (extraction is far more reliable than the sign-guessing that burned us before).

Per screen the model returns:
  readout_type      proliferation | survival | marker | binding
  growth_direction  suppressing | promoting | none      (of the treatment)
  sign_convention   what +/- means, in the authors' terms (verbatim evidence)

Frozen artifact: processed_data/condition_facets_llm.json
  status = "auto" if confidence >= threshold AND both enums valid, else "needs_review".

Reuses llm_client (WashU gateway — must be on campus/VPN, else 403).

  python3 script/classify_conditions_llm.py             # all needs-LLM screens
  python3 script/classify_conditions_llm.py --limit 3   # smoke test
  python3 script/classify_conditions_llm.py --dry-run   # print a prompt, no calls
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths
from llm_client import WashULLMClient, _extract_json_block

NEEDS_LLM_CSV = paths.PROCESSED_DATA / "facets_needs_llm.csv"
OUT_PATH = paths.PROCESSED_DATA / "condition_facets_llm.json"
PROMPT_VERSION = "cond-v1.0"
CONFIDENCE_THRESHOLD = 0.7
RATE_LIMIT = 0.3

VALID_READOUT = {"proliferation", "survival", "marker", "binding"}
VALID_GROWTH = {"suppressing", "promoting", "none"}

SYSTEM_PROMPT = """You are a CRISPR screen curator for the RETICLE database. A screen was run \
under some treatment/condition. From the curator's NOTES and condition fields, EXTRACT three \
things. Do NOT infer beyond what the text supports — these screens were chosen precisely because \
the authors usually state the answer.

1. readout_type — what the screen MEASURES:
   - proliferation : growth / viability over time (which cells out-grow or drop out)
   - survival      : survival under a lethal or selective pressure (resistance vs sensitization)
   - marker        : a reporter / FACS marker (GFP reporter, a surface marker, phagocytosis, etc.)
   - binding       : a binding / interaction readout (e.g. a surfaceome binding screen)

2. growth_direction — which way the TREATMENT itself pushes cell growth:
   - suppressing : the treatment kills or slows cells (drug, virus, toxin, immune killing, nutrient restriction)
   - promoting   : the treatment promotes growth — a growth factor / mitogen / hormone / cytokine the cells
                   depend on (e.g. estrogen, GM-CSF, WNT); ALSO use this when the SELECTION is growth in the
                   ABSENCE/withdrawal of such a signal
   - none        : no growth-modulating agent (a pure marker or binding readout, or plain baseline)

3. sign_convention — what the SIGN of the score means, in the authors' own words. Quote the phrase
   from NOTES that states it (e.g. "positive score = enriched = KO confers resistance",
   "negative score = depleted = gene required").

"confidence" = 1.0 only if NOTES explicitly states it; lower if you must infer. Put the verbatim
supporting phrase in "evidence"; if there is no concrete phrase, confidence must be <= 0.3.

Return ONLY one valid JSON object with exactly these keys:
{
  "readout_type": "proliferation" | "survival" | "marker" | "binding",
  "growth_direction": "suppressing" | "promoting" | "none",
  "sign_convention": "<one short phrase>",
  "confidence": <float 0.0-1.0>,
  "evidence": "<verbatim phrase from NOTES, or empty>"
}"""

USER_TEMPLATE = """SCREEN_ID: {sid}
EXPERIMENTAL_SETUP: {setup}
CONDITION_NAME: {cond}
CONDITION_DOSAGE: {dose}
PHENOTYPE: {phenotype}
METHODOLOGY: {methodology}
SCREEN_RATIONALE: {rationale}
SIGNIFICANCE_CRITERIA: {criteria}
NOTES: {notes}"""


def _entry(v):
    return v[0] if isinstance(v, list) else v


def load_meta():
    meta = {}
    for p in paths.BIOGRID_METADATA.values():
        if p.exists():
            for sid, v in json.loads(p.read_text()).items():
                meta[str(sid)] = _entry(v)
    return meta


def build_prompt(sid, bio):
    return USER_TEMPLATE.format(
        sid=sid,
        setup=bio.get("EXPERIMENTAL_SETUP") or "-",
        cond=bio.get("CONDITION_NAME") or "-",
        dose=bio.get("CONDITION_DOSAGE") or "-",
        phenotype=bio.get("PHENOTYPE") or "-",
        methodology=bio.get("METHODOLOGY") or "-",
        rationale=bio.get("SCREEN_RATIONALE") or "-",
        criteria=bio.get("SIGNIFICANCE_CRITERIA") or "-",
        notes=(bio.get("NOTES") or "-")[:1500],
    )


def parse(raw):
    d = _extract_json_block(raw) or {}
    ro = str(d.get("readout_type", "")).strip().lower()
    gd = str(d.get("growth_direction", "")).strip().lower()
    try:
        conf = max(0.0, min(1.0, float(d.get("confidence", 0.0))))
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "readout_type": ro if ro in VALID_READOUT else None,
        "growth_direction": gd if gd in VALID_GROWTH else None,
        "sign_convention": str(d.get("sign_convention", ""))[:300],
        "confidence": conf,
        "evidence": str(d.get("evidence", ""))[:300],
    }


def status_of(dec):
    if dec["readout_type"] and dec["growth_direction"] and dec["confidence"] >= CONFIDENCE_THRESHOLD:
        return "auto"
    return "needs_review"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个(冒烟测试)")
    ap.add_argument("--dry-run", action="store_true", help="打印一个 prompt,不调用")
    args = ap.parse_args()

    if not NEEDS_LLM_CSV.exists():
        print(f"missing {NEEDS_LLM_CSV} — run classify_conditions.py first.")
        return
    targets = [r["screen_id"] for r in csv.DictReader(open(NEEDS_LLM_CSV))]
    if args.limit:
        targets = targets[: args.limit]
    meta = load_meta()
    print(f"{len(targets)} screens to resolve via LLM")

    if args.dry_run:
        sid = targets[0]
        print("\n--- SYSTEM ---\n" + SYSTEM_PROMPT)
        print("\n--- USER ---\n" + build_prompt(sid, meta[sid]))
        return

    client = WashULLMClient(model=args.model)
    print(f"Model: {client.model}")
    try:
        client.chat([{"role": "user", "content": "ping"}], max_tokens=5)
    except Exception as e:
        print("LLM preflight FAILED — 中止,未写文件。")
        print(f"  {e}")
        print("  若 403 Forbidden:连 WashU VPN(关 Cloudflare WARP)再重跑。")
        return

    results, counts = {}, {"auto": 0, "needs_review": 0}
    for i, sid in enumerate(targets, 1):
        bio = meta.get(sid, {})
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(sid, bio)},
        ]
        try:
            resp = client.complete(messages, temperature=0, max_tokens=350,
                                    response_format={"type": "json_object"})
            raw = resp["choices"][0]["message"]["content"]
            dec = parse(raw)
        except Exception as e:
            print(f"  ! screen {sid} LLM error: {e}")
            dec = {"readout_type": None, "growth_direction": None,
                   "sign_convention": "", "confidence": 0.0, "evidence": f"LLM error: {e}"}
            raw = ""
        st = status_of(dec)
        counts[st] += 1
        results[sid] = {**dec, "status": st, "condition_name": bio.get("CONDITION_NAME", ""),
                        "experimental_setup": bio.get("EXPERIMENTAL_SETUP", ""),
                        "llm_model": client.model, "prompt_version": PROMPT_VERSION,
                        "raw_llm_output": raw}
        print(f"[{i}/{len(targets)}] {sid}: {dec['readout_type']}/{dec['growth_direction']} "
              f"conf={dec['confidence']:.2f} -> {st}")
        time.sleep(RATE_LIMIT)

    payload = {
        "_meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": client.model, "prompt_version": PROMPT_VERSION,
            "confidence_threshold": CONFIDENCE_THRESHOLD, "counts": counts,
        },
        "facets": results,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n{counts}  ->  {OUT_PATH}")


if __name__ == "__main__":
    main()
