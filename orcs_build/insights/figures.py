"""Hand-rolled SVG figures for the insight brief (stdlib-only; embed in MD/HTML/PDF).

Two figures:
  relatedness_network_svg — the target gene anchored, ringed by its top specificity-corrected
                            relatives; edge width ~ strength, node colour by class (co-orphan /
                            core-essential / specific partner).
  hit_context_matrix_svg  — every screen as a cell, split HIT vs NOT-A-HIT, coloured by the QC
                            gate (PASS / WARN / not-applicable), so Q1/Q2 read at a glance.

An optional matplotlib path (``matplotlib_network_png``) produces a publication-grade raster
when matplotlib is installed; it is never required.
"""
from __future__ import annotations

import math

# palette (matches the app's brand-neutral tokens closely enough for a standalone doc)
_C_TARGET = "#111827"
_C_SPECIFIC = "#2563eb"
_C_ORPHAN = "#d97706"
_C_CORE = "#9ca3af"
_C_HIT_PASS = "#16a34a"
_C_HIT_WARN = "#f59e0b"
_C_HIT_NA = "#0891b2"
_C_NONHIT = "#cbd5e1"
_C_EDGE = "#94a3b8"


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _rel_color(r: dict, gene: str) -> str:
    if r.get("is_core_essential"):
        return _C_CORE
    if str(r.get("gene", "")).startswith("Gm") and r.get("gene") != gene:
        return _C_ORPHAN
    return _C_SPECIFIC


def relatedness_network_svg(view, *, top: int = 14, w: int = 760, h: int = 480) -> str:
    g = view.gene
    specific = [r for r in view.relatives if r.get("specificity_class") == "specific"
                and r.get("tier") in ("Strong", "Moderate")]
    specific.sort(key=lambda r: -(r.get("strength") or 0))
    nodes = specific[:top]
    cx, cy = w / 2, h / 2
    R = min(w, h) / 2 - 78
    strengths = [r.get("strength") or 0 for r in nodes] or [1]
    smax = max(strengths) or 1

    edges, circles, labels = [], [], []
    for i, r in enumerate(nodes):
        ang = 2 * math.pi * i / max(len(nodes), 1) - math.pi / 2
        x, y = cx + R * math.cos(ang), cy + R * math.sin(ang)
        strength = r.get("strength") or 0
        wdt = 1.2 + 5 * (strength / smax)
        chans = ", ".join(r.get("channels", []) or [])
        tip = (f"{g}–{r['gene']}: {r.get('tier')} ({chans}); OR {r.get('odds_ratio')}, "
               f"rho {r.get('rho')}, specificity {r.get('spec_enrichment')}x")
        edges.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
            f'stroke="{_C_EDGE}" stroke-width="{wdt:.1f}" stroke-opacity="0.65">'
            f'<title>{_esc(tip)}</title></line>')
        col = _rel_color(r, g)
        dashed = ' stroke-dasharray="3,2"' if r.get("tier") == "Moderate" else ""
        circles.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="16" fill="{col}" stroke="#ffffff" '
            f'stroke-width="2"{dashed}><title>{_esc(tip)}</title></circle>')
        anchor = "start" if math.cos(ang) > 0.25 else "end" if math.cos(ang) < -0.25 else "middle"
        lx = x + (22 if anchor == "start" else -22 if anchor == "end" else 0)
        ly = y + (4 if abs(math.cos(ang)) <= 0.25 and math.sin(ang) > 0 else 4)
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="12" text-anchor="{anchor}" '
            f'fill="#1f2937" font-family="Inter,Arial,sans-serif">{_esc(r["gene"])}</text>')

    center = (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="24" fill="{_C_TARGET}"/>'
        f'<text x="{cx:.1f}" y="{cy + 4:.1f}" font-size="13" font-weight="700" text-anchor="middle" '
        f'fill="#ffffff" font-family="Inter,Arial,sans-serif">{_esc(g)}</text>')

    legend = (
        f'<g font-family="Inter,Arial,sans-serif" font-size="11" fill="#374151">'
        f'<circle cx="16" cy="{h-46}" r="7" fill="{_C_SPECIFIC}"/><text x="30" y="{h-42}">specific partner</text>'
        f'<circle cx="150" cy="{h-46}" r="7" fill="{_C_ORPHAN}"/><text x="164" y="{h-42}">co-orphan (Gm*)</text>'
        f'<circle cx="300" cy="{h-46}" r="7" fill="{_C_CORE}"/><text x="314" y="{h-42}">core-essential</text>'
        f'<text x="16" y="{h-22}">edge width ∝ relatedness strength; dashed ring = Moderate tier; '
        f'hover an edge for statistics</text></g>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%" '
        f'role="img" aria-label="Relatedness network for {_esc(g)}">'
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>'
        f'<text x="16" y="24" font-size="14" font-weight="700" fill="#111827" '
        f'font-family="Inter,Arial,sans-serif">Figure 1 — {_esc(g)} specificity-corrected relatedness network</text>'
        + "".join(edges) + center + "".join(circles) + "".join(labels) + legend + "</svg>")


def _cell_color(s) -> str:
    if s.hit:
        if s.gate == "WARN":
            return _C_HIT_WARN
        if s.gate == "PASS":
            return _C_HIT_PASS
        return _C_HIT_NA
    return _C_NONHIT


def hit_context_matrix_svg(view, *, cols: int = 11, w: int = 760) -> str:
    g = view.gene
    hits = sorted(view.hit_screens, key=lambda s: (s.gate != "PASS", s.gate != "WARN"))
    nonhits = sorted(view.nonhit_screens, key=lambda s: int(s.screen_id) if s.screen_id.isdigit() else 0)
    cw, ch, pad = 60, 40, 8
    top = 74

    def grid(screens, y0):
        cells = []
        for i, s in enumerate(screens):
            col, row = i % cols, i // cols
            x = pad + col * (cw + 6)
            y = y0 + row * (ch + 6)
            dashed = ' stroke="#334155" stroke-dasharray="3,2" stroke-width="1.5"' if s.coverage == "HIT_ONLY" else ' stroke="#ffffff" stroke-width="1.5"'
            tip = (f"screen {s.screen_id}: {'HIT' if s.hit else 'not a hit'} | {s.phenotype} | "
                   f"{s.cell_txt} | gate {s.gate or 'N/A'}")
            cells.append(
                f'<g><rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="5" fill="{_cell_color(s)}"{dashed}>'
                f'<title>{_esc(tip)}</title></rect>'
                f'<text x="{x + cw/2:.0f}" y="{y + ch/2 + 4:.0f}" font-size="12" text-anchor="middle" '
                f'fill="#ffffff" font-family="Inter,Arial,sans-serif" font-weight="600">{_esc(s.screen_id)}</text></g>')
        rows = (len(screens) + cols - 1) // cols
        return "".join(cells), y0 + rows * (ch + 6)

    y = top
    hdr_hit = (f'<text x="{pad}" y="{y-8}" font-size="13" font-weight="700" fill="#111827" '
               f'font-family="Inter,Arial,sans-serif">HIT ({len(hits)})</text>')
    hit_cells, y = grid(hits, y)
    y += 26
    hdr_non = (f'<text x="{pad}" y="{y-8}" font-size="13" font-weight="700" fill="#111827" '
               f'font-family="Inter,Arial,sans-serif">ASSAYED, NOT A HIT ({len(nonhits)})</text>')
    non_cells, y = grid(nonhits, y)

    legend_y = y + 22
    legend = (
        f'<g font-family="Inter,Arial,sans-serif" font-size="11" fill="#374151">'
        f'<rect x="{pad}" y="{legend_y-10}" width="14" height="14" rx="3" fill="{_C_HIT_PASS}"/><text x="{pad+20}" y="{legend_y+1}">hit, QC-trusted (PASS)</text>'
        f'<rect x="{pad+170}" y="{legend_y-10}" width="14" height="14" rx="3" fill="{_C_HIT_WARN}"/><text x="{pad+190}" y="{legend_y+1}">hit, low-trust (WARN)</text>'
        f'<rect x="{pad+350}" y="{legend_y-10}" width="14" height="14" rx="3" fill="{_C_HIT_NA}"/><text x="{pad+370}" y="{legend_y+1}">hit, non-fitness</text>'
        f'<rect x="{pad+510}" y="{legend_y-10}" width="14" height="14" rx="3" fill="{_C_NONHIT}"/><text x="{pad+530}" y="{legend_y+1}">not a hit</text>'
        f'<text x="{pad}" y="{legend_y+24}">dashed border = HIT_ONLY coverage (no non-hit counterfactual)</text></g>')
    h = legend_y + 40

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%" '
        f'role="img" aria-label="Hit-context matrix for {_esc(g)}">'
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>'
        f'<text x="{pad}" y="26" font-size="14" font-weight="700" fill="#111827" '
        f'font-family="Inter,Arial,sans-serif">Figure 2 — Where {_esc(g)} scores across {len(view.screens)} screens</text>'
        + hdr_hit + hit_cells + hdr_non + non_cells + legend + "</svg>")


def cytoscape_elements(view, *, top: int = 16) -> list[dict]:
    """Elements array for the interactive Cytoscape network in the HTML one-pager."""
    g = view.gene
    specific = [r for r in view.relatives if r.get("specificity_class") == "specific"
                and r.get("tier") in ("Strong", "Moderate")]
    specific.sort(key=lambda r: -(r.get("strength") or 0))
    els = [{"data": {"id": g, "label": g, "kind": "target"}}]
    for r in specific[:top]:
        kind = ("core" if r.get("is_core_essential")
                else "orphan" if str(r.get("gene", "")).startswith("Gm") else "specific")
        els.append({"data": {"id": r["gene"], "label": r["gene"], "kind": kind,
                             "tier": r.get("tier")}})
        els.append({"data": {
            "id": f"{g}_{r['gene']}", "source": g, "target": r["gene"],
            "w": round(1 + 6 * (r.get("strength") or 0), 2),
            "tip": f"{r.get('tier')} | {', '.join(r.get('channels', []) or [])} | OR {r.get('odds_ratio')}, rho {r.get('rho')}, spec {r.get('spec_enrichment')}x",
        }})
    return els


def matplotlib_network_png(view, path, *, top: int = 14) -> bool:
    """Optional publication-grade raster; returns False (no-op) if matplotlib is absent."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    g = view.gene
    specific = [r for r in view.relatives if r.get("specificity_class") == "specific"
                and r.get("tier") in ("Strong", "Moderate")]
    specific.sort(key=lambda r: -(r.get("strength") or 0))
    nodes = specific[:top]
    fig, ax = plt.subplots(figsize=(8, 5.2))
    ax.scatter([0], [0], s=900, c=_C_TARGET, zorder=3)
    ax.annotate(g, (0, 0), color="white", ha="center", va="center", fontsize=11, weight="bold", zorder=4)
    for i, r in enumerate(nodes):
        ang = 2 * math.pi * i / max(len(nodes), 1) - math.pi / 2
        x, y = math.cos(ang), math.sin(ang)
        ax.plot([0, x], [0, y], color=_C_EDGE, lw=1 + 5 * (r.get("strength") or 0), zorder=1)
        ax.scatter([x], [y], s=380, c=_rel_color(r, g), zorder=3, edgecolors="white")
        ax.annotate(r["gene"], (x * 1.14, y * 1.14), ha="center", va="center", fontsize=9)
    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-1.4, 1.4)
    ax.axis("off")
    ax.set_title(f"{g} specificity-corrected relatedness network")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return True
