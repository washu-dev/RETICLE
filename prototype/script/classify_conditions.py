"""
classify_conditions.py — rule-based facet classification of BioGRID ORCS screens.
================================================================================
The coarse fitness / stress / reporter domain is too blunt to drive directionality
(stress is a grab-bag whose sign convention differs by treatment — e.g. a growth-
PROMOTING signal inverts "vs control"). This adds three orthogonal facets, derived
DETERMINISTICALLY from BioGRID's structured fields that the pipeline wasn't using
(EXPERIMENTAL_SETUP, CONDITION_NAME, NOTES — ~99% populated on treated screens):

  condition_class   baseline | drug | pathogen | toxin | radiation | immune
                    | signal | nutrient | metabolic | binding | in-vivo | unknown
  growth_direction  none | suppressing | UNRESOLVED        (UNRESOLVED -> LLM)
  readout_type      proliferation | survival | marker | binding | UNRESOLVED

Rules resolve ~99% of `condition_class`; the genuinely free-text long tail (signal
sign, binding, "Other") is left UNRESOLVED for the LLM step, which EXTRACTS the
authors' stated convention from NOTES (reliable) rather than inferring it.

Outputs (processed_data/):
  condition_facets.csv       every screen: facets + method + current domain
  facets_needs_llm.csv        residual for the LLM (carries CONDITION_NAME + NOTES)
  facets_needs_review.csv     screens currently called `fitness` that are really
                              under a pressure/signal (the mislabels to verify)

  python3 script/classify_conditions.py
"""

import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths

# --- EXPERIMENTAL_SETUP (BioGRID's structured field) -> condition_class --------
SETUP_MAP = {
    "timecourse": "baseline",
    "drug exposure": "drug",
    "virus exposure": "pathogen",
    "bacteria exposure": "pathogen",
    "toxin exposure": "toxin",
    "radiation exposure": "radiation",
    "t cell exposure": "immune",
    "nk cell exposure": "immune",
    "cytokine exposure": "signal",
    "cytokine depletion": "signal",
    "ligand exposure": "signal",
    "implantation to mouse model": "in-vivo",
    "oxygen exposure": "metabolic",
    "sars-cov-2 spike-rbd exposure": "binding",
    "sars-cov-2 spike exposure (293t-spike-gfp11-p2a-mcherry cells)": "binding",
    "transferrin receptor (tfrc/cd71) exposure": "binding",
}

# growth direction (and a derived domain) per condition_class
SUPPRESSING = {"drug", "pathogen", "toxin", "radiation", "immune", "nutrient", "metabolic"}
NO_PRESSURE = {"baseline", "in-vivo"}          # proliferation readout, no agent
UNRESOLVED_CLASSES = {"signal", "binding", "unknown"}   # need the LLM for direction

# conservative keyword fallback for "Other" / combos (CONDITION_NAME + NOTES)
_SIGNAL_AGENT = re.compile(r"\b(wnt|rspo|r-spondin|estrogen|oestrogen|androgen|gm-csf|m-csf|lif|growth factor|cytokine)\b", re.I)
_SIGNAL_WD = re.compile(r"absence of|without|withdraw|[- ]independent", re.I)
_NUTRIENT = re.compile(r"(restrict|deprivation|starvation|depleted|low |withdraw).{0,40}(valine|glutamine|glucose|serine|methionine|amino acid|nutrient|cystine|arginine|lipid|sugar)", re.I)
_BINDING = re.compile(r"binding|surfaceome|interactome", re.I)
_DEATH = re.compile(r"necropt|apopto|death.?induc|cytotox|toxicity|ferropto|ceramide", re.I)
_MARKER = re.compile(r"\breporter\b", re.I)


def keyword_class(text):
    if _SIGNAL_AGENT.search(text) and _SIGNAL_WD.search(text):
        return "signal"
    if _NUTRIENT.search(text):
        return "nutrient"
    if _BINDING.search(text):
        return "binding"
    if _DEATH.search(text):
        return "drug"
    return None


def classify(setup, cond, notes):
    """Return (condition_class, method)."""
    s = (setup or "").strip().lower()
    if s in SETUP_MAP:
        return SETUP_MAP[s], "setup"
    kw = keyword_class(f"{cond} {notes}")
    if kw:
        return kw, "keyword"
    return "unknown", "unknown"


def growth_direction(cc):
    if cc in NO_PRESSURE:
        return "none"
    if cc in SUPPRESSING:
        return "suppressing"
    return "UNRESOLVED"          # signal / binding / unknown


def readout_type(cc, current_domain, notes):
    if current_domain == "reporter" or _MARKER.search(notes or ""):
        return "marker"
    if cc in NO_PRESSURE:
        return "proliferation"
    if cc in SUPPRESSING:
        return "survival"
    if cc == "binding":
        return "binding"
    return "UNRESOLVED"


def expected_domain(cc):
    if cc in NO_PRESSURE:
        return "fitness"
    if cc in SUPPRESSING or cc == "signal":
        return "stress"
    return None                 # binding / unknown -> don't assert


def _entry(v):
    return v[0] if isinstance(v, list) else v


def main():
    meta = {}
    for p in paths.BIOGRID_METADATA.values():
        if p.exists():
            for sid, v in json.loads(p.read_text()).items():
                meta[str(sid)] = _entry(v)

    current = {}
    if paths.DB.exists():
        con = sqlite3.connect(str(paths.DB))
        try:
            for sid, dom in con.execute("SELECT screen_id, assay_domain FROM screen_metadata_curated"):
                current[str(sid)] = dom
        except sqlite3.Error:
            pass
        con.close()

    facets, needs_llm, needs_review = [], [], []
    ccount, methodcount = Counter(), Counter()

    for sid, m in meta.items():
        setup = m.get("EXPERIMENTAL_SETUP", "")
        cond = (m.get("CONDITION_NAME") or "").strip()
        notes = (m.get("NOTES") or "").replace("\n", " ").strip()
        dom = current.get(sid, "")

        cc, method = classify(setup, cond, notes)
        gd = growth_direction(cc)
        ro = readout_type(cc, dom, notes)
        unresolved = gd == "UNRESOLVED" or ro == "UNRESOLVED" or cc == "unknown"
        mislabel = dom == "fitness" and expected_domain(cc) == "stress"

        ccount[cc] += 1
        methodcount[method] += 1
        row = {"screen_id": sid, "organism": m.get("ORGANISM_OFFICIAL", ""),
               "experimental_setup": setup, "condition_name": cond,
               "condition_class": cc, "growth_direction": gd, "readout_type": ro,
               "method": method, "current_domain": dom,
               "needs_llm": int(unresolved), "needs_review": int(mislabel)}
        facets.append(row)
        if unresolved:
            needs_llm.append({"screen_id": sid, "condition_class": cc,
                              "condition_name": cond, "notes": notes[:300]})
        if mislabel:
            needs_review.append({"screen_id": sid, "condition_class": cc,
                                 "current_domain": dom, "condition_name": cond,
                                 "notes": notes[:200]})

    out = paths.PROCESSED_DATA
    out.mkdir(parents=True, exist_ok=True)

    def write_csv(name, rows):
        path = out / name
        if rows:
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        return path

    write_csv("condition_facets.csv", facets)
    write_csv("facets_needs_llm.csv", needs_llm)
    write_csv("facets_needs_review.csv", needs_review)

    n = len(facets)
    print(f"classified {n} screens\n")
    print("condition_class:")
    for k, c in ccount.most_common():
        print(f"   {c:5}  {k}")
    print(f"\nmethod:  " + "  ".join(f"{k}={c}" for k, c in methodcount.most_common()))
    resolved = n - len(needs_llm)
    print(f"\n  rule-resolved (no LLM needed) : {resolved}  ({100*resolved//n}%)")
    print(f"  -> facets_needs_llm.csv        : {len(needs_llm)}  (signal/binding/unknown — read NOTES)")
    print(f"  -> facets_needs_review.csv     : {len(needs_review)}  (currently 'fitness', really a pressure/signal)")
    print(f"\nwrote: {out/'condition_facets.csv'}\n       {out/'facets_needs_llm.csv'}\n       {out/'facets_needs_review.csv'}")


if __name__ == "__main__":
    main()
