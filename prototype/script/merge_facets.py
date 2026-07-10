"""
merge_facets.py — combine the rule layer + the LLM layer into one facet table.
=============================================================================
Inputs (processed_data/):
  condition_facets.csv        rule layer (all 2157 screens; ~96% resolved)
  condition_facets_llm.json   LLM layer (the ~82 long-tail screens)

For each screen the rule values win where they're deterministic; the LLM fills
the facets the rules left UNRESOLVED (only when its status == "auto"). A suggested
corrected `assay_domain` is derived from readout_type + condition_class so the
harmonization step knows which screens to re-domain / re-sign.

Output: processed_data/condition_facets_final.csv  (one row per screen)
  screen_id, organism, condition_class, growth_direction, readout_type,
  sign_convention, source, status, current_domain, new_domain, domain_changed

  python3 script/merge_facets.py
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths

PD = paths.PROCESSED_DATA
RULES_CSV = PD / "condition_facets.csv"
LLM_JSON = PD / "condition_facets_llm.json"
OUT = PD / "condition_facets_final.csv"


def derive_domain(condition_class, readout, growth):
    """Map facets back onto the coarse axis the pipeline uses."""
    if readout in ("marker", "binding"):
        return "reporter"                       # held out of quant axes
    if readout == "survival":
        return "stress"
    if readout == "proliferation":
        # baseline proliferation with no agent = fitness; proliferation UNDER a
        # drug/signal is conditional growth -> stress (not baseline essentiality)
        if condition_class in ("baseline", "in-vivo") and growth == "none":
            return "fitness"
        return "stress"
    return None                                  # unresolved


def main():
    rules = {r["screen_id"]: r for r in csv.DictReader(open(RULES_CSV))}
    llm = json.loads(LLM_JSON.read_text()).get("facets", {}) if LLM_JSON.exists() else {}

    rows = []
    src_cnt, dom_cnt, changed = Counter(), Counter(), 0
    for sid, r in rules.items():
        cc = r["condition_class"]
        gd = r["growth_direction"]
        ro = r["readout_type"]
        sign = ""
        status = "auto"
        source = "rule"

        lr = llm.get(sid)
        if lr is not None:                       # screen was in the LLM long tail
            if lr.get("status") == "auto":
                gd = lr["growth_direction"] or gd
                ro = lr["readout_type"] or ro
                sign = lr.get("sign_convention", "")
                source = "llm"
            else:
                source, status = "llm-review", "needs_review"

        if gd == "UNRESOLVED" or ro == "UNRESOLVED":
            status = "needs_review"

        current = r["current_domain"]
        new_dom = derive_domain(cc, ro, gd) or current
        dom_changed = int(bool(current) and new_dom != current)
        changed += dom_changed
        src_cnt[source] += 1
        dom_cnt[new_dom] += 1

        rows.append({
            "screen_id": sid, "organism": r["organism"],
            "condition_class": cc, "growth_direction": gd, "readout_type": ro,
            "sign_convention": sign, "source": source, "status": status,
            "current_domain": current, "new_domain": new_dom,
            "domain_changed": dom_changed,
        })

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"merged {len(rows)} screens -> {OUT}\n")
    print("source:        " + "  ".join(f"{k}={v}" for k, v in src_cnt.most_common()))
    print("new_domain:    " + "  ".join(f"{k}={v}" for k, v in dom_cnt.most_common()))
    cur = Counter(r["current_domain"] for r in rows if r["current_domain"])
    print("current_domain:" + "  ".join(f"{k}={v}" for k, v in cur.most_common()))
    print(f"\ndomain CHANGED by the facets: {changed} screens")
    nr = sum(1 for r in rows if r["status"] == "needs_review")
    print(f"still needs_review: {nr}")
    # what the changes look like
    moves = Counter((r["current_domain"], r["new_domain"]) for r in rows if r["domain_changed"])
    print("\ntop domain moves (current -> new):")
    for (a, b), n in moves.most_common(10):
        print(f"   {n:4}  {a or '?'} -> {b}")


if __name__ == "__main__":
    main()
