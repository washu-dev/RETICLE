"""Render the verified insight ledger into PI-facing views.

The ledger (``<GENE>_insights.jsonl``) is the canonical source of truth; the Markdown brief
(``<GENE>_insights.md``, GatewayAI-uploadable + the make-pdf source) and the interactive HTML
one-pager (``<GENE>_insights.html``) are deterministic renders of it, so the three can never
disagree. Both documents follow the same question-spine layout and carry a tier badge + resolved
citations on every claim. Figures come from ``figures.py`` (inline SVG everywhere; live Cytoscape
in the HTML with the SVG as its no-JS fallback).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import figures

# ---------------------------------------------------------------------------
CATEGORY_TITLES = {
    "A": "Identity & de-orphanization",
    "B": "Why it is a hit (Q1)",
    "C": "Why it is not a hit elsewhere (Q2)",
    "D": "Source literature",
    "E": "Functional relatives (Q3)",
    "F": "Cross-evidence synthesis",
    "G": "Confounds & QC",
    "H": "Confidence & limitations",
}
_TIER_HTML = {
    "direct_evidence": ("#065f46", "#d1fae5"),
    "indirect_evidence": ("#1e40af", "#dbeafe"),
    "inference": ("#5b21b6", "#ede9fe"),
    "literature_supported_inference": ("#5b21b6", "#ede9fe"),
    "hypothesis": ("#92400e", "#fef3c7"),
    "speculation": ("#374151", "#f3f4f6"),
    "contradiction": ("#991b1b", "#fee2e2"),
    "unknown": ("#374151", "#f3f4f6"),
}


# ---------------------------------------------------------------------------
# citation resolution
# ---------------------------------------------------------------------------
def _cite_label(eid: str, idx: dict, ctx: dict | None = None) -> tuple[str, str]:
    """Return (human_label, link_or_empty).

    External ids resolve to the authoritative database page: PMID -> PubMed,
    SCR -> the BioGRID ORCS screen page (matches the "screen N" label), GENE/REL ->
    NCBI Gene (the target by its Entrez id, relatives by symbol+organism search).
    Internal aggregates (CTX / HARM / SUM) have no external page, so they stay
    unlinked here; the interactive viewer turns them into in-app navigation instead.
    ``ctx`` carries {organism, entrez, gene} so gene links can be qualified.
    """
    from urllib.parse import quote
    ctx = ctx or {}
    organism, entrez, target_gene = ctx.get("organism", ""), ctx.get("entrez", ""), ctx.get("gene", "")
    it = idx.get(eid)
    kind = eid.split(":", 1)[0]
    val = eid.split(":", 1)[1] if ":" in eid else eid

    def _gene_link(sym: str) -> str:
        if sym == target_gene and entrez:
            return f"https://www.ncbi.nlm.nih.gov/gene/{quote(entrez)}"
        term = f"{sym}[sym] AND {organism}[orgn]" if organism else f"{sym}[sym]"
        return f"https://www.ncbi.nlm.nih.gov/gene/?term={quote(term)}"

    if kind == "PMID":
        return f"PMID {val}", f"https://pubmed.ncbi.nlm.nih.gov/{val}/"
    if kind == "SCR":
        return f"screen {val}", f"https://orcs.thebiogrid.org/Screen/{quote(val)}"
    if kind in ("GENE", "REL"):
        return val, _gene_link(val)
    if kind == "CTX":
        return f"context: {it.ref.get('context', val) if it else val}", ""
    if kind == "HARM":
        return f"QC {val}", ""
    if kind == "SUM":
        return "dossier summary", ""
    return eid, (it.link if it else "")


def _cites_md(ev_ids, idx, ctx=None) -> str:
    if not ev_ids:
        return ""
    out = []
    for eid in ev_ids:
        label, link = _cite_label(eid, idx, ctx)
        out.append(f"[{label}]({link})" if link else label)
    return "  \n  <sub>cites: " + ", ".join(out) + "</sub>"


def _cites_html(ev_ids, idx, ctx=None) -> str:
    if not ev_ids:
        return ""
    out = []
    for eid in ev_ids:
        label, link = _cite_label(eid, idx, ctx)
        out.append(f'<a href="{link}">{_esc(label)}</a>' if link else _esc(label))
    return f'<span class="cites">cites: {", ".join(out)}</span>'


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _note(v) -> str:
    if v.decision == "soften":
        return " _[softened — partial support]_"
    if v.decision == "downgraded_no_citation":
        return " _[downgraded — no resolvable citation]_"
    if v.decision == "labeled_unverified":
        return " _[unverified — flagged for review]_"
    if v.decision == "flag_contradiction":
        return " _[⚠ contradiction — review]_"
    return ""


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------
def _ledger_records(result):
    idx = result.pack.index()
    recs = []
    for v in result.claims:
        ev = []
        for eid in v.evidence_ids:
            it = idx.get(eid)
            ev.append({"id": eid, "kind": it.kind if it else "unresolved",
                       "ref": it.ref if it else {}, "link": it.link if it else ""})
        recs.append({
            "layer": v.layer, "category": v.category, "tier": v.label, "text": v.text,
            "evidence": ev, "confidence": v.confidence,
            "verification": {"status": v.verification_status, "decision": v.decision,
                             "support": v.support, "contradiction": v.contradiction},
            "uncertainty": v.uncertainty, "withheld": v.withheld,
            "withheld_reason": v.withheld_reason,
        })
    return recs


# ---------------------------------------------------------------------------
# markdown brief
# ---------------------------------------------------------------------------
def _by(result, *, cats=None, layers=None, withheld=None):
    out = []
    for v in result.claims:
        if withheld is not None and v.withheld != withheld:
            continue
        if cats is not None and not any(v.category == c or v.category.startswith(c) for c in cats):
            continue
        if layers is not None and v.layer not in layers:
            continue
        out.append(v)
    return out


def _md_claim(v, idx, ctx=None) -> str:
    return f"- **[{v.label}]** {v.text}{_note(v)}{_cites_md(v.evidence_ids, idx, ctx)}"


def render_markdown(result, gene, generated_at) -> str:
    idx = result.pack.index()
    view = result.pack.view
    ctx = {"organism": view.organism, "entrez": view.entrez, "gene": gene}
    L = [f"# {gene} — Insight Brief",
         "",
         f"*BioGRID ORCS CRISPR-screen evidence + source literature + specificity-corrected "
         f"relatedness, synthesized into cited insights. Generated {generated_at}. "
         f"Source: {result.provider_name}. Every claim is tier-labeled and verified against its "
         f"cited evidence (screen / PMID / relative); unsupported claims are dropped.*",
         ""]

    # Executive summary
    L += ["## Executive summary", ""]
    for cat in ("A", "B", "C", "E"):
        c = _by(result, cats=[cat], withheld=False)
        if c:
            L.append(_md_claim(c[0], idx, ctx))
    hyp = _by(result, layers=[2])
    if hyp:
        L.append(_md_claim(hyp[0], idx, ctx))
    conf = _by(result, cats=["H"], withheld=False)
    if conf:
        L.append(_md_claim(conf[0], idx, ctx))
    L.append("")

    # Figure 2 (hit-context) belongs with Q1; Figure 1 (network) with Q3.
    fig_matrix = figures.hit_context_matrix_svg(view)
    fig_net = figures.relatedness_network_svg(view)

    def section(title, claims, fig=None):
        L.append(f"## {title}")
        L.append("")
        if fig:
            L.append(fig)
            L.append("")
        if not claims:
            L.append("_No qualifying insights._")
        for v in claims:
            L.append(_md_claim(v, idx, ctx))
        L.append("")

    section("1. " + CATEGORY_TITLES["A"], _by(result, cats=["A"], withheld=False))
    section("2. " + CATEGORY_TITLES["B"], _by(result, cats=["B"], withheld=False), fig=fig_matrix)
    section("3. " + CATEGORY_TITLES["C"], _by(result, cats=["C"], withheld=False))
    section("4. " + CATEGORY_TITLES["E"], _by(result, cats=["E"], withheld=False), fig=fig_net)
    section("5. " + CATEGORY_TITLES["D"], _by(result, cats=["D"], withheld=False))

    synth = _by(result, cats=["F"], withheld=False) + _by(result, layers=[2])
    section("6. Cross-evidence synthesis & hypotheses", synth)
    section("7. Validation plan", _by(result, layers=[3]) + _by(result, cats=["V"]))
    section("8. " + CATEGORY_TITLES["H"],
            _by(result, cats=["H"], withheld=False) + _by(result, cats=["G"], withheld=False))

    withheld = _by(result, withheld=True)
    if withheld:
        section("9. Withheld interpretations (metadata insufficient)", withheld)

    # Evidence appendix — relatedness table + QC table
    L += ["## Appendix — specificity-corrected relatives (top 25)", "",
          "| gene | tier | class | channels | OR | rho | spec× | core-ess |",
          "|---|---|---|---|---|---|---|---|"]
    specific = sorted([r for r in view.relatives if r.get("specificity_class") == "specific"],
                      key=lambda r: -(r.get("strength") or 0))
    for r in specific[:25]:
        L.append(f"| {r['gene']} | {r.get('tier')} | {r.get('specificity_class')} | "
                 f"{', '.join(r.get('channels', []) or [])} | {r.get('odds_ratio')} | "
                 f"{r.get('rho')} | {r.get('spec_enrichment')} | "
                 f"{'yes' if r.get('is_core_essential') else 'no'} |")
    L += ["", "## Appendix — screen QC gates (fitness screens)", "",
          "| screen | phenotype | direction | gate | detail |", "|---|---|---|---|---|"]
    for s in sorted(view.screens, key=lambda s: int(s.screen_id) if s.screen_id.isdigit() else 0):
        if s.gate:
            L.append(f"| {s.screen_id} | {s.phenotype} | {s.direction} | {s.gate} | {s.gate_detail} |")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# interactive HTML one-pager
# ---------------------------------------------------------------------------
_HTML_CSS = """
:root{--fg:#111827;--muted:#6b7280;--line:#e5e7eb;--bg:#ffffff;--accent:#2563eb}
*{box-sizing:border-box}
body{font-family:Inter,-apple-system,Segoe UI,Arial,sans-serif;color:var(--fg);background:#f8fafc;
margin:0;line-height:1.55}
main{max-width:940px;margin:0 auto;padding:40px 28px 80px;background:var(--bg)}
h1{font-size:30px;margin:0 0 6px}h2{font-size:20px;margin:34px 0 10px;padding-top:8px;border-top:1px solid var(--line)}
.sub{color:var(--muted);font-size:14px;margin-bottom:8px}
.claim{margin:10px 0;padding-left:12px;border-left:3px solid var(--line)}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;margin-right:8px;vertical-align:middle}
.cites{display:block;color:var(--muted);font-size:12px;margin-top:3px}
.cites a{color:var(--accent);text-decoration:none}.cites a:hover{text-decoration:underline}
.note{font-size:12px;color:#b45309;font-weight:600;margin-left:6px}
figure{margin:18px 0;border:1px solid var(--line);border-radius:10px;padding:10px;background:#fff}
figcaption{color:var(--muted);font-size:12px;margin-top:6px}
#cy{width:100%;height:460px;border:1px solid var(--line);border-radius:10px;background:#fff}
table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left}th{background:#f3f4f6}
.exec{background:#f1f5f9;border-radius:10px;padding:14px 18px;margin:14px 0}
.withheld{background:#fffbeb;border-left-color:#f59e0b}
"""


def _html_claim(v, idx, ctx=None) -> str:
    fg, bg = _TIER_HTML.get(v.label, _TIER_HTML["unknown"])
    note = _note(v).strip().strip("_").strip()
    note_html = f'<span class="note">{_esc(note)}</span>' if note else ""
    cls = "claim withheld" if v.withheld else "claim"
    return (f'<div class="{cls}"><span class="badge" style="color:{fg};background:{bg}">{v.label}</span>'
            f'{_esc(v.text)}{note_html}{_cites_html(v.evidence_ids, idx, ctx)}</div>')


def render_html(result, gene, generated_at, *, interactive: bool = True) -> str:
    idx = result.pack.index()
    view = result.pack.view
    ctx = {"organism": view.organism, "entrez": view.entrez, "gene": gene}
    els = json.dumps(figures.cytoscape_elements(view))
    net_svg = figures.relatedness_network_svg(view)
    matrix_svg = figures.hit_context_matrix_svg(view)

    def sec(title, claims, extra=""):
        body = extra + "".join(_html_claim(v, idx, ctx) for v in claims)
        if not claims and not extra:
            body = "<p class='sub'>No qualifying insights.</p>"
        return f"<h2>{_esc(title)}</h2>{body}"

    exec_claims = []
    for cat in ("A", "B", "C", "E"):
        c = _by(result, cats=[cat], withheld=False)
        if c:
            exec_claims.append(c[0])
    exec_claims += _by(result, layers=[2])[:1] + _by(result, cats=["H"], withheld=False)[:1]
    exec_html = ("<h2>Executive summary</h2><div class='exec'>"
                 + "".join(_html_claim(v, idx, ctx) for v in exec_claims) + "</div>")

    if interactive:
        net_block = (
            f'<figure><div id="cy"></div><noscript>{net_svg}</noscript>'
            f'<figcaption>Figure 1 — specificity-corrected relatedness network (interactive; '
            f'hover an edge for statistics). Static fallback shown without JavaScript.</figcaption></figure>')
    else:
        net_block = (f'<figure>{net_svg}<figcaption>Figure 1 — specificity-corrected relatedness '
                     f'network.</figcaption></figure>')
    matrix_block = (f'<figure>{matrix_svg}<figcaption>Figure 2 — where {_esc(gene)} scores across '
                    f'{len(view.screens)} screens, coloured by QC gate.</figcaption></figure>')

    # appendix tables
    specific = sorted([r for r in view.relatives if r.get("specificity_class") == "specific"],
                      key=lambda r: -(r.get("strength") or 0))[:25]
    rel_rows = "".join(
        f"<tr><td>{_esc(r['gene'])}</td><td>{_esc(r.get('tier'))}</td>"
        f"<td>{_esc(', '.join(r.get('channels', []) or []))}</td><td>{_esc(r.get('odds_ratio'))}</td>"
        f"<td>{_esc(r.get('rho'))}</td><td>{_esc(r.get('spec_enrichment'))}</td>"
        f"<td>{'yes' if r.get('is_core_essential') else 'no'}</td></tr>" for r in specific)
    rel_table = (f"<h2>Appendix — top specificity-corrected relatives</h2><table><tr><th>gene</th>"
                 f"<th>tier</th><th>channels</th><th>OR</th><th>rho</th><th>spec×</th>"
                 f"<th>core-ess</th></tr>{rel_rows}</table>")

    withheld = _by(result, withheld=True)
    withheld_sec = sec("Withheld interpretations (metadata insufficient)", withheld) if withheld else ""

    cy_script = f"""
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js"></script>
<script>
(function(){{
  if(!window.cytoscape){{return;}}
  var cy=cytoscape({{container:document.getElementById('cy'),elements:{els},
    style:[
      {{selector:'node',style:{{'label':'data(label)','font-size':11,'text-valign':'center',
        'color':'#fff','background-color':'#2563eb','width':34,'height':34}}}},
      {{selector:'node[kind="target"]',style:{{'background-color':'#111827','width':48,'height':48,'font-weight':'bold'}}}},
      {{selector:'node[kind="orphan"]',style:{{'background-color':'#d97706'}}}},
      {{selector:'node[kind="core"]',style:{{'background-color':'#9ca3af'}}}},
      {{selector:'edge',style:{{'width':'data(w)','line-color':'#94a3b8','curve-style':'straight'}}}}
    ],
    layout:{{name:'concentric',minNodeSpacing:44,concentric:function(n){{return n.data('kind')==='target'?10:1;}},
             levelWidth:function(){{return 1;}}}}}});
  cy.edges().forEach(function(e){{e.on('mouseover',function(){{}});}});
  cy.on('mouseover','edge',function(e){{var t=e.target.data('tip')||'';if(t){{e.target.qtip;}}}});
}})();
</script>"""

    print_css = "" if interactive else (
        "@page{size:A4;margin:16mm}h2{page-break-after:avoid}.claim,figure{page-break-inside:avoid}"
        "body{background:#fff}main{max-width:none;padding:0}")
    cy_script = "" if not interactive else cy_script
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(gene)} — Insight Brief</title><style>{_HTML_CSS}{print_css}</style></head>
<body><main>
<h1>{_esc(gene)} — Insight Brief</h1>
<div class="sub">CRISPR-screen evidence + literature + specificity-corrected relatedness · generated {_esc(generated_at)} · source: {_esc(result.provider_name)}</div>
<div class="sub">Every claim is tier-labeled and verified against its cited evidence; unsupported claims are dropped.</div>
{exec_html}
{sec("1. " + CATEGORY_TITLES["A"], _by(result, cats=["A"], withheld=False))}
{sec("2. " + CATEGORY_TITLES["B"], _by(result, cats=["B"], withheld=False), extra=matrix_block)}
{sec("3. " + CATEGORY_TITLES["C"], _by(result, cats=["C"], withheld=False))}
{sec("4. " + CATEGORY_TITLES["E"], _by(result, cats=["E"], withheld=False), extra=net_block)}
{sec("5. " + CATEGORY_TITLES["D"], _by(result, cats=["D"], withheld=False))}
{sec("6. Cross-evidence synthesis & hypotheses", _by(result, cats=["F"], withheld=False) + _by(result, layers=[2]))}
{sec("7. Validation plan", _by(result, layers=[3]) + _by(result, cats=["V"]))}
{sec("8. " + CATEGORY_TITLES["H"], _by(result, cats=["H"], withheld=False) + _by(result, cats=["G"], withheld=False))}
{withheld_sec}
{rel_table}
{cy_script}
</main></body></html>"""


# ---------------------------------------------------------------------------
# viewer data bundle (consumed by the Next.js insights viewer)
# ---------------------------------------------------------------------------
def viewer_bundle(result, gene: str, generated_at: str) -> dict:
    from . import figures
    idx = result.pack.index()
    view = result.pack.view
    ctx = {"organism": view.organism, "entrez": view.entrez, "gene": gene}

    def claim_dict(v):
        cites = []
        for eid in v.evidence_ids:
            label, link = _cite_label(eid, idx, ctx)
            cites.append({"id": eid, "label": label, "link": link})
        return {"layer": v.layer, "category": v.category, "tier": v.label, "text": v.text,
                "evidence": cites, "confidence": v.confidence, "decision": v.decision,
                "withheld": v.withheld, "withheld_reason": v.withheld_reason}

    claims = [claim_dict(v) for v in result.claims]
    hits = len(view.hit_screens)
    return {
        "gene": gene,
        "organism": view.organism,
        "generated_at": generated_at,
        "provider": result.provider_name,
        "meta": {
            "entrez": view.entrez,
            "identity": (view.identity or {}).get("description", "predicted gene"),
            "n_screens": len(view.screens),
            "n_hits": hits,
            "n_full": view.n_full_screens,
            "n_relatives": view.validation.get("n_relatives"),
            "n_strong": view.validation.get("n_strong"),
            "n_publications": len(view.publications),
            "counts": result.counts,
            "n_deduped": result.n_deduped,
            "n_dropped": result.n_dropped,
        },
        "claims": claims,
        "network": figures.cytoscape_elements(view, top=16),
        "screens": [{
            "screen_id": s.screen_id, "hit": s.hit, "coverage": s.coverage,
            "phenotype": s.phenotype, "cell": s.cell_txt, "gate": s.gate,
            "is_fitness": s.is_fitness,
        } for s in view.screens],
        "relatives": [{
            "gene": r["gene"], "tier": r.get("tier"), "specificity_class": r.get("specificity_class"),
            "channels": r.get("channels", []), "odds_ratio": r.get("odds_ratio"),
            "rho": r.get("rho"), "spec_enrichment": r.get("spec_enrichment"),
            "is_core_essential": r.get("is_core_essential"),
        } for r in sorted([r for r in view.relatives if r.get("specificity_class") == "specific"],
                          key=lambda r: -(r.get("strength") or 0))[:25]],
        "publications": [{
            "pmid": p.pmid, "title": p.title, "abstract": p.abstract,
            "journal": p.journal, "year": p.year, "author": p.author,
            "has_fulltext": p.has_fulltext,
            "backs_screens": [{"screen_id": sid, "hit": hit} for sid, hit in p.backs_screens],
        } for p in view.publications],
        "qc": [{
            "screen_id": s.screen_id, "phenotype": s.phenotype, "direction": s.direction,
            "gate": s.gate, "gate_detail": s.gate_detail,
        } for s in sorted(view.screens, key=lambda s: int(s.screen_id) if s.screen_id.isdigit() else 0)
          if s.gate],
    }


# ---------------------------------------------------------------------------
def write_all(result, outdir: Path, gene: str, generated_at: str) -> list[str]:
    outdir = Path(outdir)
    written = []

    jl = outdir / f"{gene}_insights.jsonl"
    with jl.open("w", encoding="utf-8") as f:
        for rec in _ledger_records(result):
            f.write(json.dumps(rec) + "\n")
    written.append(jl.name)

    md = outdir / f"{gene}_insights.md"
    md.write_text(render_markdown(result, gene, generated_at), encoding="utf-8")
    written.append(md.name)

    html = outdir / f"{gene}_insights.html"
    html.write_text(render_html(result, gene, generated_at, interactive=True), encoding="utf-8")
    written.append(html.name)

    # print-optimised HTML (inline SVG figures, no CDN/JS) — source for the PDF brief
    print_html = outdir / f"{gene}_insights_print.html"
    print_html.write_text(render_html(result, gene, generated_at, interactive=False), encoding="utf-8")
    written.append(print_html.name)

    # standalone SVG figures (also embedded inline above; handy for slides)
    net = outdir / f"{gene}_network.svg"
    net.write_text(figures.relatedness_network_svg(result.pack.view), encoding="utf-8")
    written.append(net.name)
    mat = outdir / f"{gene}_hitmatrix.svg"
    mat.write_text(figures.hit_context_matrix_svg(result.pack.view), encoding="utf-8")
    written.append(mat.name)

    # data bundle for the Next.js insights viewer (UI/UX)
    bundle = outdir / f"{gene}_insights_data.json"
    bundle.write_text(json.dumps(viewer_bundle(result, gene, generated_at), indent=2),
                      encoding="utf-8")
    written.append(bundle.name)

    return written
