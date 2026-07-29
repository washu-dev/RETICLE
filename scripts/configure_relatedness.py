#!/usr/bin/env python3
"""
configure_relatedness.py — D3 driver: the what-if CONFIG service (server side).

Turns a cheap relatedness_profile (D2) into an accepted relatedness_config that
D4/D5 read their thresholds + budget from. Three actions:

  --list-profiles / --list-configs   visibility (A/B configs coexist per version)
  --recommend                        given --max-pairs, pick the most-inclusive
                                     thresholds off the profile's projection
                                     curves whose projected volume fits; write a
                                     DRAFT relatedness_config (unless --dry-run)
  --accept --config-id N             re-validate the draft's projected cost
                                     SERVER-SIDE against the stored profile, then
                                     flip status draft -> accepted (OWASP A04:
                                     the budget gate is authoritative here, never
                                     trusted from a client)

--recommend --accept does both in one shot.

Lightweight DB-only op (reads one profile row, writes one config row) — runs in
seconds on the LOGIN NODE. No scipy, no SLURM job.

tier_cuts note: the profiler measures pair VOLUME, not the effect-size (ρ)
distribution, so Strong/Moderate/Weak cuts are seeded here with defaults and
recalibrated post-D5 from the real ρ distribution (see recalibrate_tiers TODO).

Usage:
  python3 configure_relatedness.py --version 8 --list-profiles
  python3 configure_relatedness.py --version 8 --recommend --max-pairs 5000000
  python3 configure_relatedness.py --version 8 --recommend --max-pairs 5e6 --accept --label budget-5M
  python3 configure_relatedness.py --version 8 --accept --config-id 3
  python3 configure_relatedness.py --version 8 --list-configs
"""

import argparse
import json
import logging
import sys

import psycopg2
import psycopg2.extras

from config import Config

logger = logging.getLogger("configure_relatedness")

CONFIG_VERSION = "d3-config-1.0"

# Seeded tier cuts (recalibrated from the real ρ / Jaccard distributions after
# D5 — recorded in the config so a run is reproducible and auditable).
DEFAULT_TIER_CUTS = {
    "co_essentiality": {"strong": 0.50, "moderate": 0.30},   # on |ρ|
    "co_hit":          {"strong": 0.50, "moderate": 0.20},   # on Jaccard
    "co_citation":     {"strong": 2.00, "moderate": 1.00},   # on PMI
    "overall":         {"strong": 0.50, "moderate": 0.30},
    "_calibration": "SEEDED_DEFAULTS — recalibrate from D5 ρ distribution",
}

# fixed (non-volume) threshold defaults; overridable via --thresholds-json
DEFAULT_STATIC_THRESHOLDS = {
    "tail_percentile": 0.10,
    "fdr_alpha": 0.01,
    "abs_rho_min": 0.0,     # keep all pairs; strength is expressed via tiers, not a hard cut
    "jaccard_min": 0.0,
    "pmi_min": 0.0,
}

# which curve each channel's volume-threshold lives under in the profile snapshot
_CHANNEL_KEY = {
    "co_essentiality": "min_shared_full_screens",
    "co_hit":          "min_cohit_screens",
    "co_citation":     "min_copub_count",
}


def connect():
    params = Config.get_psycopg2_params()
    params["sslmode"] = "require"
    conn = psycopg2.connect(**params)
    conn.autocommit = False
    return conn


def resolve_organism(conn, version_id):
    cur = conn.cursor()
    cur.execute("SELECT organism FROM data_load_version WHERE version_id=%s", (version_id,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"version_id {version_id} not found")
    return row[0]


def latest_profile(conn, version_id, profile_id=None):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if profile_id is not None:
        cur.execute("SELECT profile_id, organism, snapshot, created_at "
                    "FROM relatedness_profile WHERE profile_id=%s AND data_load_version_id=%s",
                    (profile_id, version_id))
    else:
        cur.execute("SELECT profile_id, organism, snapshot, created_at "
                    "FROM relatedness_profile WHERE data_load_version_id=%s "
                    "ORDER BY created_at DESC LIMIT 1", (version_id,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(
            f"No relatedness_profile for version {version_id}"
            + (f" (profile_id={profile_id})" if profile_id else "")
            + ". Run slurm/reticle-profile.sh first (D2).")
    return row


# ---- projection lookup -----------------------------------------------------

def _channel_curve(snapshot, channel):
    block = snapshot.get("projection_curves", {}).get(channel, {})
    if block.get("status") == "unavailable":
        return None, block.get("reason", "unavailable")
    return block.get("curve"), None


def _volume_at(curve, key, threshold, conservative=False):
    """Projected pairs for a channel at a given threshold. Grid points are exact;
    a non-grid threshold falls back to the closest grid point <= threshold (an
    UPPER BOUND on pairs, since higher threshold => fewer pairs)."""
    if not curve:
        return None
    exact = [p for p in curve if p["threshold"][key] == threshold]
    if exact:
        p = exact[0]
    else:
        lower = [p for p in curve if p["threshold"][key] <= threshold]
        if not lower:
            return None
        p = max(lower, key=lambda p: p["threshold"][key])
    return p.get("ci_high", p["projected_pairs"]) if conservative else p["projected_pairs"]


def recommend(snapshot, max_pairs):
    """Pick the most-inclusive (smallest) threshold per channel whose projected
    volume fits max_pairs. Co-essentiality uses the conservative ci_high (it is
    SAMPLED); co-hit/co-citation are EXACT. Returns (thresholds, breakdown,
    total_pairs, coess_cost, compute_mode)."""
    thresholds = dict(DEFAULT_STATIC_THRESHOLDS)
    thresholds["tier_cuts"] = json.loads(json.dumps(DEFAULT_TIER_CUTS))  # deep copy
    thresholds["selective_gene_filter"] = snapshot.get("filter", {})
    thresholds["compute_mode"] = "EXACT"
    thresholds["ann_topk"] = None
    breakdown = {}
    total = 0
    coess_cost = 0

    for channel, key in _CHANNEL_KEY.items():
        curve, reason = _channel_curve(snapshot, channel)
        if curve is None:
            breakdown[channel] = {"status": "unavailable", "reason": reason}
            thresholds[key] = None
            continue
        conservative = (channel == "co_essentiality")
        chosen = None
        for pt in sorted(curve, key=lambda p: p["threshold"][key]):
            vol = pt.get("ci_high", pt["projected_pairs"]) if conservative else pt["projected_pairs"]
            if vol <= max_pairs:
                chosen = pt
                break
        if chosen is None:
            # even the strictest grid point exceeds budget
            chosen = max(curve, key=lambda p: p["threshold"][key])
            if channel == "co_essentiality":
                thresholds["compute_mode"] = "ANN_TOPK"   # fall back to top-K pruning
        thresholds[key] = chosen["threshold"][key]
        if channel == "co_essentiality":
            thresholds["tail_percentile"] = chosen["threshold"].get("tail_percentile",
                                                                     thresholds["tail_percentile"])
            coess_cost = chosen.get("projected_cost_units", chosen["projected_pairs"])
        vol = chosen.get("ci_high", chosen["projected_pairs"]) if conservative else chosen["projected_pairs"]
        breakdown[channel] = {
            "threshold": chosen["threshold"][key],
            "projected_pairs": chosen["projected_pairs"],
            "volume_used_for_budget": vol,
            "estimation": chosen["estimation_method"],
            "fits_budget": vol <= max_pairs,
        }
        total += chosen["projected_pairs"]

    return thresholds, breakdown, total, coess_cost, thresholds["compute_mode"]


def validate_cost(snapshot, thresholds, max_pairs):
    """SERVER-AUTHORITATIVE revalidation: recompute per-channel projected volume
    from the STORED profile at the config's thresholds and compare to the budget.
    Returns (ok, total, per_channel)."""
    total = 0
    per_channel = {}
    for channel, key in _CHANNEL_KEY.items():
        t = thresholds.get(key)
        if t is None:
            per_channel[channel] = None
            continue
        curve, _ = _channel_curve(snapshot, channel)
        conservative = (channel == "co_essentiality")
        vol = _volume_at(curve, key, t, conservative=conservative)
        per_channel[channel] = vol
        if vol:
            total += vol
    return (total <= max_pairs), total, per_channel


# ---- actions ---------------------------------------------------------------

def do_list_profiles(conn, version_id):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT profile_id, organism, profiler_version, created_by, created_at, "
                "snapshot->'selective_gene_count' AS selective, snapshot->'screens' AS screens "
                "FROM relatedness_profile WHERE data_load_version_id=%s ORDER BY created_at DESC",
                (version_id,))
    rows = cur.fetchall()
    if not rows:
        print(f"No profiles for version {version_id}.")
        return
    print(f"Profiles for version {version_id}:")
    for r in rows:
        print(f"  profile_id={r['profile_id']}  {r['organism']}  selective={r['selective']}  "
              f"screens={r['screens']}  by={r['created_by']}  {r['created_at']:%Y-%m-%d %H:%M}")


def do_list_configs(conn, version_id):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT config_id, profile_id, organism, label, status, projected_pairs, "
                "projected_cost_units, created_by, created_at "
                "FROM relatedness_config WHERE data_load_version_id=%s ORDER BY created_at DESC",
                (version_id,))
    rows = cur.fetchall()
    if not rows:
        print(f"No configs for version {version_id}.")
        return
    print(f"Configs for version {version_id}:")
    for r in rows:
        print(f"  config_id={r['config_id']}  [{r['status']}]  label={r['label']!r}  "
              f"profile_id={r['profile_id']}  projected_pairs={r['projected_pairs']}  "
              f"cost={r['projected_cost_units']}  by={r['created_by']}")


def _print_recommendation(breakdown, total, max_pairs, mode):
    print(f"\nRecommendation (budget max_pairs={max_pairs:,}):")
    for ch, b in breakdown.items():
        if b.get("status") == "unavailable":
            print(f"  {ch:16s} unavailable ({b['reason']})")
            continue
        flag = "OK" if b["fits_budget"] else "OVER-BUDGET"
        print(f"  {ch:16s} threshold={b['threshold']:<4} projected_pairs={b['projected_pairs']:>12,} "
              f"({b['estimation']}, {flag})")
    print(f"  {'TOTAL':16s} {'':13} projected_pairs={total:>12,}")
    print(f"  compute_mode={mode}")


def do_recommend(conn, version_id, organism, profile, max_pairs, budget, label,
                 thresholds_override, created_by, accept, dry_run):
    snapshot = profile["snapshot"]
    thresholds, breakdown, total, coess_cost, mode = recommend(snapshot, max_pairs)
    if thresholds_override:
        thresholds.update(thresholds_override)
        # re-derive volume/mode from the (possibly overridden) thresholds
        ok, total, per = validate_cost(snapshot, thresholds, max_pairs)
        logger.info(f"Applied threshold overrides; server-side total={total:,} fits={ok}")
    _print_recommendation(breakdown, total, max_pairs, mode)

    if dry_run:
        print("\n[dry-run] no config written")
        print(json.dumps(thresholds, indent=2))
        return

    status = "draft"
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO relatedness_config
            (data_load_version_id, profile_id, organism, label, thresholds, compute_budget,
             projected_pairs, projected_cost_units, status, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (data_load_version_id, organism, label) DO UPDATE SET
            profile_id=EXCLUDED.profile_id, thresholds=EXCLUDED.thresholds,
            compute_budget=EXCLUDED.compute_budget, projected_pairs=EXCLUDED.projected_pairs,
            projected_cost_units=EXCLUDED.projected_cost_units, status=EXCLUDED.status,
            updated_at=CURRENT_TIMESTAMP
        RETURNING config_id
    """, (version_id, profile["profile_id"], organism, label,
          psycopg2.extras.Json(thresholds), psycopg2.extras.Json(budget),
          int(total), float(coess_cost), status, created_by))
    config_id = cur.fetchone()[0]
    conn.commit()
    print(f"\nWrote relatedness_config config_id={config_id} status={status} label={label!r}")

    if accept:
        do_accept(conn, version_id, config_id, created_by)
    else:
        print(f"Review, then accept with:  --version {version_id} --accept --config-id {config_id}")


def do_accept(conn, version_id, config_id, accepted_by):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT config_id, profile_id, organism, label, thresholds, compute_budget, status "
                "FROM relatedness_config WHERE config_id=%s AND data_load_version_id=%s",
                (config_id, version_id))
    cfg = cur.fetchone()
    if not cfg:
        raise SystemExit(f"config_id {config_id} not found for version {version_id}")
    if cfg["status"] not in ("draft", "accepted"):
        raise SystemExit(f"config_id {config_id} status={cfg['status']} — only draft/accepted can be (re)accepted")

    profile = latest_profile(conn, version_id, cfg["profile_id"])
    max_pairs = (cfg["compute_budget"] or {}).get("max_pairs")
    if max_pairs is None:
        raise SystemExit("compute_budget.max_pairs missing — cannot validate cost server-side")

    ok, total, per = validate_cost(profile["snapshot"], cfg["thresholds"], max_pairs)
    print(f"Server-side revalidation vs profile_id={cfg['profile_id']}: "
          f"projected_pairs={total:,} budget max_pairs={int(max_pairs):,} -> {'OK' if ok else 'REJECT'}")
    for ch, v in per.items():
        print(f"    {ch:16s} {('n/a' if v is None else format(v, ',')):>14}")
    if not ok:
        raise SystemExit(
            "REJECTED: projected pairs exceed compute_budget.max_pairs. "
            "Re-recommend with a tighter --max-pairs or set compute_mode=ANN_TOPK.")

    cur.execute("UPDATE relatedness_config SET status='accepted', projected_pairs=%s, "
                "updated_at=CURRENT_TIMESTAMP WHERE config_id=%s", (int(total), config_id))
    conn.commit()
    print(f"config_id={config_id} accepted (label={cfg['label']!r}). D4/D5 can now build against it.")


def main():
    ap = argparse.ArgumentParser(description="D3 what-if relatedness config service")
    ap.add_argument("--version", type=int, required=True, help="Data load version ID")
    ap.add_argument("--profile-id", type=int, default=None, help="specific profile (default: latest)")
    ap.add_argument("--list-profiles", action="store_true")
    ap.add_argument("--list-configs", action="store_true")
    ap.add_argument("--recommend", action="store_true", help="recommend thresholds + write a draft config")
    ap.add_argument("--accept", action="store_true", help="accept (validate cost server-side, flip to accepted)")
    ap.add_argument("--config-id", type=int, default=None, help="config to --accept")
    ap.add_argument("--max-pairs", type=float, default=None, help="budget: max projected candidate pairs")
    ap.add_argument("--cpu-hours", type=float, default=None)
    ap.add_argument("--gpu-hours", type=float, default=None)
    ap.add_argument("--label", default="default", help="A/B label for the config (unique per version)")
    ap.add_argument("--thresholds-json", default=None, help="JSON dict of threshold overrides")
    ap.add_argument("--created-by", default=None)
    ap.add_argument("--dry-run", action="store_true", help="recommend only; write nothing")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    import os
    created_by = args.created_by or os.getenv("USER") or "config-service"

    conn = connect()
    try:
        organism = resolve_organism(conn, args.version)

        if args.list_profiles:
            do_list_profiles(conn, args.version)
        if args.list_configs:
            do_list_configs(conn, args.version)
        if args.list_profiles or args.list_configs:
            if not (args.recommend or args.accept):
                return

        if args.recommend:
            if args.max_pairs is None:
                raise SystemExit("--recommend requires --max-pairs (the budget)")
            profile = latest_profile(conn, args.version, args.profile_id)
            budget = {"max_pairs": int(args.max_pairs),
                      "cpu_hours": args.cpu_hours, "gpu_hours": args.gpu_hours}
            overrides = json.loads(args.thresholds_json) if args.thresholds_json else None
            do_recommend(conn, args.version, organism, profile, int(args.max_pairs), budget,
                         args.label, overrides, created_by, args.accept, args.dry_run)
        elif args.accept:
            if args.config_id is None:
                raise SystemExit("--accept (without --recommend) requires --config-id")
            do_accept(conn, args.version, args.config_id, created_by)
        elif not (args.list_profiles or args.list_configs):
            ap.error("nothing to do: pass --list-profiles / --list-configs / --recommend / --accept")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
