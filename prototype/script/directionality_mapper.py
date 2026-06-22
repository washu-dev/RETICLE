"""
RETICLE — Directionality Mapper (LLM, one-shot artifact generator)
==================================================================
对 Phase 1 里**方向无法确定**的 screen（SCORE_BASIS 含 AMBIGUOUS_SELECTION，或
UNRESOLVED），用 LLM 读 BioGRID 的 NOTES + SIGNIFICANCE_CRITERIA + RATIONALE，
裁决该 screen 在 RETICLE 统一 loss-of-function 轴上的符号，产出一个**冻结的 JSON
产物** processed_data/directionality_overrides.json。

为什么是「一次性冻结产物」
------------------------
  LLM 是非确定性、要花钱、要联网的。把它的输出冻结成一个可提交、可人工抽查的
  文件，让 harmonize / apply_directionality 把这个文件当**确定性输入**读取——
  Phase 1 因此仍是纯函数（相同原始数据 + 相同 override → 相同结果），LLM 的随机性
  被隔离在这一步里。

统一轴定义（LLM 必须对齐）
------------------------
  +  : 基因功能丧失(loss-of-function) 是有利的 / 被选择群体所富集
       （该基因正常时抑制所测表型 / KO 后存活、富集）
  -  : 基因是必需的 / 所测表型所需（KO 后耗竭、缺失）
  注：CRISPRa 等扰动方向已被 LLM 在推理 NOTES 时一并考虑，输出即为
      HARMONIZED_SCORE 的最终符号，apply_directionality 不再单独乘 perturbation_mult。

输出（每个 screen 一条）
----------------------
  mode = SINGLE : 单个无方向显著性列 → 给出 sign(+1/-1)
  mode = PAIR   : 隐藏的 pos/neg 配对 → 指明哪列是 +(positive_column) 哪列是 -(negative_column)
  mode = UNDEFINED : 文本里读不出极性
  低置信度(< THRESHOLD) 或 UNDEFINED → status="needs_review"，不自动应用，等人工裁决。
  UNRESOLVED 桶(无可用效应列) → status="binary_only"，只记录生物学方向供 binary 模式参考。

RUN
---
  python3 script/directionality_mapper.py --show-prompt        # 看第一条 prompt，不调 LLM
  python3 script/directionality_mapper.py --dry-run            # 打印将处理的 screen，不调 LLM
  python3 script/directionality_mapper.py --limit 5            # 需要 WashU VPN
  python3 script/directionality_mapper.py                      # 全部 111 个
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths
from llm_client import WashULLMClient, _extract_json_block

OVERRIDES_PATH = paths.PROCESSED_DATA / "directionality_overrides.json"
CONFIDENCE_THRESHOLD = 0.7
PROMPT_VERSION = "dir-v1.0"
LLM_RATE_LIMIT = 0.4

# --------------------------------------------------------------------------
# BioGRID raw metadata
# --------------------------------------------------------------------------

_biogrid_index: dict[str, dict] = {}


def _load_biogrid():
    if _biogrid_index:
        return
    for _, path in paths.BIOGRID_METADATA.items():
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for sid, entries in data.items():
            if entries:
                _biogrid_index[str(sid)] = entries[0]


def get_bio(screen_id: str) -> dict:
    _load_biogrid()
    return _biogrid_index.get(str(screen_id), {})


def score_layout(bio: dict) -> dict[str, str]:
    """{'SCORE.1': 'MaGeCK Score', 'SCORE.3': 'MaGeCK Score', ...} (non-empty only)."""
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


def build_prompt(screen_id: str, bio: dict) -> str:
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
# LLM call + validation
# --------------------------------------------------------------------------

def parse_decision(raw: str, layout: dict) -> dict:
    """Parse + sanity-check the model's JSON. Returns a normalized dict; on any
    structural problem returns an UNDEFINED decision with confidence 0."""
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        d = _extract_json_block(raw)
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
        return {"mode": "SINGLE", "sign": int(sign),
                "positive_column": None, "negative_column": None,
                "confidence": conf, "evidence": evidence}

    if mode == "PAIR":
        pos, neg = d.get("positive_column"), d.get("negative_column")
        if pos not in layout or neg not in layout or pos == neg:
            return _undef(f"PAIR with columns not in layout ({pos},{neg})")
        return {"mode": "PAIR", "sign": None,
                "positive_column": pos, "negative_column": neg,
                "confidence": conf, "evidence": evidence}

    return {"mode": "UNDEFINED", "sign": None,
            "positive_column": None, "negative_column": None,
            "confidence": conf, "evidence": evidence}


def _undef(reason: str) -> dict:
    return {"mode": "UNDEFINED", "sign": None, "positive_column": None,
            "negative_column": None, "confidence": 0.0, "evidence": "",
            "parse_note": reason}


def classify_status(decision: dict, is_unresolved: bool) -> str:
    if is_unresolved:
        return "binary_only"               # 无连续效应列，不进连续轴
    if decision["mode"] == "UNDEFINED":
        return "needs_review"
    if decision["confidence"] < CONFIDENCE_THRESHOLD:
        return "needs_review"
    return "auto"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def target_screens(db) -> list[tuple[str, bool]]:
    """Return [(screen_id, is_unresolved), ...] for every screen Phase 1 could not
    resolve a direction for."""
    rows = db.execute(
        "SELECT SCREEN_ID, SCORE_BASIS FROM screen_metadata "
        "WHERE SCORE_BASIS LIKE '%AMBIGUOUS_SELECTION%' OR SCORE_BASIS='UNRESOLVED' "
        "ORDER BY CAST(SCREEN_ID AS INTEGER)"
    ).fetchall()
    return [(str(sid), basis == "UNRESOLVED") for sid, basis in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--screen-ids", type=str, default="")
    ap.add_argument("--model", type=str, default="gpt-4o",
                    help="方向裁决用的模型（默认 gpt-4o；PAIR 列识别比 mini 更可靠）")
    ap.add_argument("--dry-run", action="store_true", help="列出将处理的 screen，不调 LLM")
    ap.add_argument("--show-prompt", action="store_true", help="打印第一条 prompt 后退出")
    args = ap.parse_args()

    db = sqlite3.connect(str(paths.DB))
    targets = target_screens(db)
    db.close()

    if args.screen_ids:
        want = {s.strip() for s in args.screen_ids.split(",") if s.strip()}
        targets = [(s, u) for s, u in targets if s in want]
    if args.limit:
        targets = targets[:args.limit]

    _load_biogrid()
    n_amb = sum(1 for _, u in targets if not u)
    n_unr = sum(1 for _, u in targets if u)
    log(f"Targets: {len(targets)}  (AMBIGUOUS={n_amb}, UNRESOLVED={n_unr})")

    if args.show_prompt:
        sid = targets[0][0]
        print("\n--- SYSTEM ---\n" + SYSTEM_PROMPT)
        print("\n--- USER ---\n" + build_prompt(sid, get_bio(sid)))
        return

    if args.dry_run:
        for sid, u in targets:
            print(f"  {'UNRESOLVED' if u else 'AMBIGUOUS '} screen {sid}: "
                  f"layout={score_layout(get_bio(sid))}")
        return

    client = WashULLMClient(model=args.model)
    log(f"Model: {client.model}")
    try:
        client.chat([{"role": "user", "content": "ping"}], max_tokens=5)
    except Exception as e:
        log("LLM preflight FAILED — 中止，未写任何文件。")
        log(f"  {e}")
        log("  若 403 Forbidden：关 Cloudflare WARP、连 WashU VPN，再重跑。")
        return

    results = {}
    counts = {"auto": 0, "needs_review": 0, "binary_only": 0}
    tok_p = tok_c = 0

    for i, (sid, is_unr) in enumerate(targets, 1):
        bio = get_bio(sid)
        layout = score_layout(bio)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(sid, bio)},
        ]
        try:
            resp = client.complete(messages, temperature=0, max_tokens=300,
                                   response_format={"type": "json_object"})
            raw = resp["choices"][0]["message"]["content"]
            usage = resp.get("usage", {})
            tok_p += usage.get("prompt_tokens", 0)
            tok_c += usage.get("completion_tokens", 0)
            decision = parse_decision(raw, layout)
        except Exception as e:
            log(f"  ! screen {sid} LLM error: {e}")
            decision = _undef(f"LLM error: {e}")
            raw = ""

        status = classify_status(decision, is_unr)
        counts[status] += 1
        results[sid] = {
            **decision,
            "status": status,
            "is_unresolved": is_unr,
            "score_layout": layout,
            "llm_model": client.model,
            "prompt_version": PROMPT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "raw_llm_output": raw,
        }
        log(f"[{i}/{len(targets)}] screen {sid}: {decision['mode']} "
            f"conf={decision['confidence']:.2f} -> {status}")
        time.sleep(LLM_RATE_LIMIT)

    payload = {
        "_meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": client.model,
            "prompt_version": PROMPT_VERSION,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "counts": counts,
            "axis": "+1 = loss-of-function advantageous/enriched; -1 = gene essential/depleted",
        },
        "overrides": results,
    }
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print()
    log(f"Wrote {OVERRIDES_PATH}")
    log(f"  auto-apply={counts['auto']}  needs_review={counts['needs_review']}  "
        f"binary_only={counts['binary_only']}")
    log(f"  tokens: prompt={tok_p:,} completion={tok_c:,}")
    if counts["needs_review"]:
        log("  人工裁决清单（status=needs_review）:")
        for sid, r in results.items():
            if r["status"] == "needs_review":
                log(f"    screen {sid}: mode={r['mode']} conf={r['confidence']:.2f} "
                    f"evidence={r['evidence'][:80]!r}")


if __name__ == "__main__":
    main()
