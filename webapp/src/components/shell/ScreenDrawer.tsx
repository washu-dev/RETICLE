import { useEffect, useMemo, useState } from 'react';
import { X, ExternalLink, Download, Info } from 'lucide-react';
import Provenance from '../washu/Provenance';
import { fetchScreenDetail, type ScreenDetail, type ScreenGene } from '../../services/reticleApi';
import { ApiError } from '../../services/api';
import { labelFor, ASSAY_DOMAIN, MODALITY } from '../../data/screenVocab';

/**
 * The screen drawer — opens a matched screen's own data without leaving the
 * results view (mirrors GeneDrawer's overlay). Three tabs:
 *   • Overview  — metadata, verified citation, link-outs to the paper + screen
 *   • Genes     — the screen's genes as clickable tokens (route into gene lookup)
 *   • Raw data  — the actual per-gene score table (raw deposited + harmonized),
 *                 sortable, filterable, downloadable, with plain-language column
 *                 explainers so a bench biologist can read it without a legend.
 *
 * Sits at z-index 55 — below GeneDrawer (60) — so a gene opened from here stacks
 * on top of the screen it came from.
 */

type Load<T> = { state: 'loading' | 'ok' | 'error' | 'notfound'; data: T | null };
type Tab = 'overview' | 'genes' | 'raw';

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'genes', label: 'Genes' },
  { id: 'raw', label: 'Raw data' },
];

// Column meta for the raw table. `help` is the pedagogy — what the number means.
type Col = {
  key: 'symbol' | 'raw' | 'harm' | 'z' | 'pct';
  label: string;
  help: string;
  numeric: boolean;
  get: (g: ScreenGene) => number | null | undefined;
};

export default function ScreenDrawer({
  screenId,
  onClose,
  onOpenGene,
}: {
  screenId: string | null;
  onClose: () => void;
  onOpenGene: (symbol: string) => void;
}) {
  const open = screenId != null;
  const [detail, setDetail] = useState<Load<ScreenDetail>>({ state: 'loading', data: null });
  const [tab, setTab] = useState<Tab>('overview');
  const [showAll, setShowAll] = useState(false);
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<{ key: Col['key']; dir: 'asc' | 'desc' }>({ key: 'pct', dir: 'desc' });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!screenId) return;
    setDetail({ state: 'loading', data: null });
    setTab('overview');
    setShowAll(false);
    setQ('');
    setSort({ key: 'pct', dir: 'desc' });
    const ctrl = new AbortController();
    fetchScreenDetail(screenId, ctrl.signal)
      .then((d) => setDetail({ state: 'ok', data: d }))
      .catch((e) => {
        if (e?.name === 'AbortError') return;
        setDetail({ state: e instanceof ApiError && e.status === 404 ? 'notfound' : 'error', data: null });
      });
    return () => ctrl.abort();
  }, [screenId]);

  const d = detail.data;
  const genes = d?.genes ?? [];
  const rawLabel = d?.rawScoreLabel || 'raw';

  const filtered = useMemo(() => {
    const needle = q.trim().toUpperCase();
    return needle ? genes.filter((g) => g.symbol.toUpperCase().includes(needle)) : genes;
  }, [genes, q]);

  // Token cloud (Genes tab) — capped unless "show all" / filtering.
  const tokens = showAll || q ? filtered : filtered.slice(0, 40);

  const cols: Col[] = useMemo(() => [
    { key: 'symbol', label: 'Gene', numeric: false, get: () => 0,
      help: 'Official gene symbol. Click to open it in the single-gene lookup.' },
    { key: 'raw', label: `Raw · ${rawLabel}`, numeric: true, get: (g) => g.rawScore,
      help: `The score exactly as deposited in BioGRID ORCS (${rawLabel}), before RETICLE touches it. Scale and sign are the original authors'.` },
    { key: 'harm', label: 'Harmonized', numeric: true, get: (g) => g.harmonizedScore,
      help: 'RETICLE’s cross-screen–comparable score. Rescaled so higher always means a stronger phenotype, letting screens be compared like-for-like.' },
    { key: 'z', label: 'Robust z', numeric: true, get: (g) => g.robustZ,
      help: 'How many robust standard deviations this gene sits from the screen’s median (median/MAD based, so outliers don’t distort it).' },
    { key: 'pct', label: 'Percentile', numeric: true, get: (g) => g.percentile,
      help: 'The gene’s rank within this screen, 0–1. 0.99 = stronger than 99% of measured genes here.' },
  ], [rawLabel]);

  // Raw table rows — filtered then sorted by the active column.
  const rows = useMemo(() => {
    const col = cols.find((c) => c.key === sort.key) ?? cols[4];
    const mul = sort.dir === 'asc' ? 1 : -1;
    const val = (g: ScreenGene) => (sort.key === 'symbol' ? g.symbol : col.get(g));
    return [...filtered].sort((a, b) => {
      const va = val(a); const vb = val(b);
      if (sort.key === 'symbol') return String(va).localeCompare(String(vb)) * mul;
      const na = va == null ? -Infinity : Number(va);
      const nb = vb == null ? -Infinity : Number(vb);
      return (na - nb) * mul;
    });
  }, [filtered, sort, cols]);

  const toggleSort = (key: Col['key']) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' }));

  // Roving-tabindex keyboard nav across the tab bar (WAI-ARIA tabs pattern):
  // Left/Right move between tabs, Home/End jump to the ends, and focus follows.
  const onTabKey = (e: React.KeyboardEvent) => {
    const i = TABS.findIndex((t) => t.id === tab);
    let next = i;
    if (e.key === 'ArrowRight') next = (i + 1) % TABS.length;
    else if (e.key === 'ArrowLeft') next = (i - 1 + TABS.length) % TABS.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = TABS.length - 1;
    else return;
    e.preventDefault();
    setTab(TABS[next].id);
    document.getElementById(`screen-tab-${TABS[next].id}`)?.focus();
  };

  const metaRows: [string, string | null | undefined][] = d ? [
    ['Rationale', d.rationale],
    ['Cell line', d.cellLine],
    ['Cell type', d.cellType],
    ['Phenotype', d.phenotype],
    ['Condition', d.conditionName],
    ['Analysis', d.analysis],
    ['Score basis', d.scoreBasis],
    ['Coverage', d.coverageType],
  ] : [];

  const downloadTable = () => {
    if (!d) return;
    const header = ['gene', `raw_${rawLabel}`, 'harmonized_score', 'robust_z', 'percentile', 'is_hit'];
    const body = genes.map((g) => [
      g.symbol, g.rawScore ?? '', g.harmonizedScore ?? '', g.robustZ ?? '', g.percentile ?? '', g.isHit ? 1 : 0,
    ]);
    const csv = [header, ...body]
      .map((r) => r.map((c) => (/[",\n]/.test(String(c)) ? `"${String(c).replace(/"/g, '""')}"` : String(c))).join(','))
      .join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `reticle-screen-${d.screenId}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <div
        className={`overlay${open ? '' : ' hidden'}`}
        style={{ display: open ? 'block' : 'none' }}
        onClick={onClose}
      />
      <aside
        className="screen-drawer"
        style={{ ...drawer, transform: open ? 'none' : 'translateX(100%)' }}
        aria-label="Screen detail"
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
      >
        <div style={drawerHead}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <div>
              <div className="eyebrow">Matched screen</div>
              <h3 style={{ fontWeight: 700, fontSize: '1.3rem', margin: '6px 0 0', lineHeight: 1.2 }}>
                {d?.name ?? (screenId ? `Screen ${screenId}` : '')}
              </h3>
              <div style={{ fontSize: '0.8rem', color: 'var(--faint)', marginTop: 4 }}>
                {[d?.author, d?.organism].filter(Boolean).join(' · ')}
              </div>
            </div>
            <button style={xclose} onClick={onClose} aria-label="Close"><X size={20} /></button>
          </div>
          {d && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '12px 0 14px' }}>
              {d.organism && <span className="badge badge-unknown">{d.organism}</span>}
              {d.modality && <span className="badge badge-ko">{labelFor(MODALITY, d.modality)}</span>}
              {d.assayDomain && <span className="badge badge-dark">{labelFor(ASSAY_DOMAIN, d.assayDomain)}</span>}
            </div>
          )}
          {/* Tabs — WAI-ARIA tabs pattern with roving tabindex + arrow-key nav */}
          {detail.state === 'ok' && d && (
            <div style={tabBar} role="tablist" aria-label="Screen views" onKeyDown={onTabKey}>
              {TABS.map((t) => {
                const active = tab === t.id;
                return (
                  <button
                    key={t.id}
                    id={`screen-tab-${t.id}`}
                    role="tab"
                    aria-selected={active}
                    aria-controls={`screen-panel-${t.id}`}
                    tabIndex={active ? 0 : -1}
                    onClick={() => setTab(t.id)}
                    style={{ ...tabBtn, ...(active ? tabBtnActive : null) }}
                  >
                    {t.label}
                    {t.id === 'raw' && genes.length > 0 && <span style={tabCount}>{genes.length}</span>}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div
          style={drawerBody}
          role={detail.state === 'ok' ? 'tabpanel' : undefined}
          id={detail.state === 'ok' ? `screen-panel-${tab}` : undefined}
          aria-labelledby={detail.state === 'ok' ? `screen-tab-${tab}` : undefined}
        >
          {detail.state === 'loading' && <p style={muted}>Loading screen…</p>}
          {detail.state === 'notfound' && <p style={muted}>Screen {screenId} isn't in the corpus.</p>}
          {detail.state === 'error' && <p style={muted}>Couldn't reach the corpus for this screen — try again.</p>}

          {detail.state === 'ok' && d && tab === 'overview' && (
            <>
              {/* Link-outs: the paper and the original screen */}
              <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap' }}>
                {d.pubmedUrl && (
                  <a href={d.pubmedUrl} target="_blank" rel="noreferrer" style={linkBtn}>
                    PubMed <ExternalLink size={13} />
                  </a>
                )}
                <a href={d.biogridUrl} target="_blank" rel="noreferrer" style={linkBtn}>
                  BioGRID ORCS <ExternalLink size={13} />
                </a>
              </div>

              {/* Verified citation — resolved from the same pmid the link points to */}
              {d.citation && (
                <p style={citeLine}>
                  {d.citation}
                  {d.pmid ? <span style={{ color: 'var(--faint)' }}> · PMID {d.pmid}</span> : null}
                </p>
              )}

              {/* Metadata — measured data & literature (Source) */}
              <Provenance kind="source" sub="screen metadata" style={{ marginTop: 18 }} />
              <dl style={dl}>
                {metaRows.filter(([, v]) => v).map(([k, v]) => (
                  <div key={k} style={dlRow}>
                    <dt style={dt}>{k}</dt>
                    <dd style={dd}>{v}</dd>
                  </div>
                ))}
              </dl>
              <p style={faintHint}>
                {d.nHits != null ? `${d.nHits.toLocaleString()} author-called hits` : ''}
                {d.scoresSize != null ? ` across ${d.scoresSize.toLocaleString()} measured genes.` : ''}
                {' '}Open the <b>Raw data</b> tab to read the per-gene score table.
              </p>
            </>
          )}

          {detail.state === 'ok' && d && tab === 'genes' && (
            <>
              <Provenance kind="computed" sub="author-called hits, strongest first" />
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 10, margin: '8px 0 10px' }}>
                <h4 style={mini}>Genes in this screen</h4>
                <span style={{ fontSize: '0.76rem', color: 'var(--faint)' }} className="tnum">
                  {d.nHits != null ? `${d.nHits.toLocaleString()} hits` : ''}
                  {d.scoresSize != null ? ` · ${d.scoresSize.toLocaleString()} measured` : ''}
                </span>
              </div>

              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Filter genes…"
                aria-label="Filter genes"
                style={search}
              />

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, marginTop: 12 }}>
                {tokens.map((g) => (
                  <button
                    key={g.symbol}
                    className="lk"
                    onClick={() => onOpenGene(g.symbol)}
                    title={g.percentile != null ? `percentile ${g.percentile.toFixed(3)}` : undefined}
                    style={{ ...geneTok, ...(g.isHit ? geneTokHit : null) }}
                  >
                    {g.symbol}
                  </button>
                ))}
                {tokens.length === 0 && <p style={muted}>No genes match “{q}”.</p>}
              </div>

              {!showAll && !q && genes.length > tokens.length && (
                <button onClick={() => setShowAll(true)} style={moreBtn}>
                  Show all {genes.length}{d.nHits && d.nHits > genes.length ? ` (of ${d.nHits.toLocaleString()} hits)` : ''}
                </button>
              )}
              <p style={faintHint}>
                Click any gene to open it in the single-gene lookup.
                {d.nHits != null && genes.length < d.nHits && ` Showing the top ${genes.length} hits.`}
              </p>
            </>
          )}

          {detail.state === 'ok' && d && tab === 'raw' && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                <Provenance kind="computed" sub="per-gene scores · raw + harmonized" />
                <button onClick={downloadTable} style={dlBtn} title="Download this table as CSV">
                  <Download size={13} /> CSV
                </button>
              </div>

              {/* Pedagogy: what "raw" vs "harmonized" mean, up front. */}
              <div style={pedagogy}>
                <Info size={14} style={{ flex: '0 0 auto', marginTop: 1, color: 'var(--teal)' }} />
                <div>
                  <b>Raw</b> is the score as the authors deposited it ({rawLabel}); <b>harmonized</b> is
                  RETICLE’s rescaling so screens compare like-for-like (higher = stronger). Hover any
                  column header for its full definition. Rows in <span style={{ color: 'var(--washu-red)', fontWeight: 600 }}>red</span> are author-called hits.
                </div>
              </div>

              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Filter genes…"
                aria-label="Filter genes"
                style={{ ...search, margin: '12px 0 4px' }}
              />

              <div style={{ overflowX: 'auto', marginTop: 8 }}>
                <table className="data-table" style={{ width: '100%', fontSize: '0.8rem' }}>
                  <thead>
                    <tr>
                      {cols.map((c) => (
                        <th
                          key={c.key}
                          title={c.help}
                          onClick={() => toggleSort(c.key)}
                          style={{ ...thSort, textAlign: c.numeric ? 'right' : 'left' }}
                        >
                          {c.label}
                          <span style={sortCaret}>{sort.key === c.key ? (sort.dir === 'asc' ? '▲' : '▼') : '↕'}</span>
                        </th>
                      ))}
                      <th style={{ textAlign: 'center' }} title="Whether the screen's authors called this gene a hit.">Hit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((g) => (
                      <tr key={g.symbol}>
                        <td>
                          <button
                            className="lk"
                            onClick={() => onOpenGene(g.symbol)}
                            style={{ fontWeight: 600, color: g.isHit ? 'var(--washu-red)' : 'var(--fg)' }}
                            title={`Open ${g.symbol}`}
                          >
                            {g.symbol}
                          </button>
                        </td>
                        <td className="tnum" style={numCell}>{fmt(g.rawScore)}</td>
                        <td className="tnum" style={numCell}>{fmt(g.harmonizedScore)}</td>
                        <td className="tnum" style={numCell}>{fmt(g.robustZ)}</td>
                        <td className="tnum" style={numCell}>{g.percentile != null ? g.percentile.toFixed(3) : '—'}</td>
                        <td style={{ textAlign: 'center' }}>
                          {g.isHit ? <span className="badge badge-agree">hit</span> : <span style={{ color: 'var(--faint)' }}>—</span>}
                        </td>
                      </tr>
                    ))}
                    {rows.length === 0 && (
                      <tr><td colSpan={6} style={muted}>No genes match “{q}”.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p style={faintHint}>
                Showing {rows.length.toLocaleString()} of {genes.length.toLocaleString()} loaded rows
                {d.nHits != null && genes.length < d.nHits ? ` (top genes of ${d.nHits.toLocaleString()} hits).` : '.'}
                {' '}Download the CSV for the full loaded table.
              </p>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function fmt(v?: number | null): string {
  if (v == null || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  return a !== 0 && (a < 0.01 || a >= 1e4) ? v.toExponential(2) : v.toFixed(2);
}

/* ---- styles (mirror GeneDrawer) ---- */
const drawer: React.CSSProperties = {
  position: 'fixed', top: 0, right: 0, height: '100vh', width: 560, maxWidth: '96vw',
  background: '#fff', borderLeft: '1px solid var(--border)', boxShadow: 'var(--shadow)',
  transition: 'transform 0.24s cubic-bezier(0.4,0,0.2,1)', zIndex: 55,
  display: 'flex', flexDirection: 'column',
};
const drawerHead: React.CSSProperties = {
  borderTop: '3px solid var(--washu-red)', padding: '18px 22px 0', borderBottom: '1px solid var(--border)',
};
const xclose: React.CSSProperties = { marginLeft: 'auto', color: 'var(--faint)', padding: '0 4px', lineHeight: 1 };
const drawerBody: React.CSSProperties = { overflowY: 'auto', padding: '18px 22px 60px', flex: 1 };
const muted: React.CSSProperties = { color: 'var(--fg-muted)', fontSize: '0.9rem', lineHeight: 1.6 };
const faintHint: React.CSSProperties = { fontSize: '0.8rem', color: 'var(--faint)', lineHeight: 1.55, marginTop: 12 };
const mini: React.CSSProperties = {
  fontSize: '0.7rem', letterSpacing: '0.07em', textTransform: 'uppercase',
  color: 'var(--fg-muted)', margin: 0, fontWeight: 700,
};
const tabBar: React.CSSProperties = { display: 'flex', gap: 4, marginTop: 4 };
const tabBtn: React.CSSProperties = {
  minHeight: 44, padding: '11px 16px', border: 'none', background: 'none', cursor: 'pointer',
  fontSize: '0.84rem', fontWeight: 600, color: 'var(--fg-muted)',
  borderBottom: '3px solid transparent', marginBottom: -1,
  display: 'inline-flex', alignItems: 'center', gap: 6,
};
// Active: bold red label, 3px underline, and a faint tint — three cues so the
// selected tab reads clearly without relying on color alone (a11y).
const tabBtnActive: React.CSSProperties = {
  color: 'var(--washu-red)', fontWeight: 700,
  borderBottomColor: 'var(--washu-red)', background: 'rgba(186,12,47,0.04)',
};
const tabCount: React.CSSProperties = {
  fontSize: '0.68rem', background: 'var(--border)', color: 'var(--fg-muted)',
  borderRadius: 10, padding: '1px 7px', fontWeight: 700,
};
const citeLine: React.CSSProperties = { fontSize: '0.84rem', color: 'var(--fg)', margin: '12px 0 0', lineHeight: 1.5 };
const pedagogy: React.CSSProperties = {
  display: 'flex', gap: 8, marginTop: 12, padding: '10px 12px',
  background: 'rgba(0,124,146,0.05)', border: '1px solid rgba(0,124,146,0.18)',
  borderRadius: 8, fontSize: '0.8rem', color: 'var(--fg-muted)', lineHeight: 1.5,
};
const dl: React.CSSProperties = { margin: '8px 0 0' };
const dlRow: React.CSSProperties = { display: 'grid', gridTemplateColumns: '96px 1fr', gap: 12, padding: '7px 0', borderBottom: '1px solid var(--border)' };
const dt: React.CSSProperties = { fontSize: '0.72rem', fontWeight: 700, color: 'var(--faint)', textTransform: 'uppercase', letterSpacing: '0.05em' };
const dd: React.CSSProperties = { fontSize: '0.88rem', color: 'var(--fg)', margin: 0, lineHeight: 1.5 };
const search: React.CSSProperties = {
  width: '100%', padding: '8px 11px', background: 'var(--white)', border: '1px solid var(--border)',
  borderRadius: 7, color: 'var(--fg)', fontSize: '0.85rem', fontFamily: 'inherit', outline: 'none',
};
const geneTok: React.CSSProperties = {
  padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'var(--white)', color: 'var(--fg-muted)', fontSize: '0.82rem', fontWeight: 500,
};
const geneTokHit: React.CSSProperties = {
  borderColor: 'rgba(186,12,47,0.30)', color: 'var(--washu-red)', fontWeight: 600,
};
const moreBtn: React.CSSProperties = {
  marginTop: 12, fontSize: '0.8rem', color: 'var(--teal)', fontWeight: 600,
};
const linkBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  padding: '7px 12px', borderRadius: 6, border: '1px solid var(--border-2)',
  background: '#fff', color: 'var(--washu-red)', fontSize: '0.8rem', fontWeight: 600, textDecoration: 'none',
};
const dlBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 10px',
  borderRadius: 6, border: '1px solid var(--border-2)', background: '#fff',
  color: 'var(--teal)', fontSize: '0.76rem', fontWeight: 600, cursor: 'pointer',
};
const thSort: React.CSSProperties = { cursor: 'pointer', whiteSpace: 'nowrap', userSelect: 'none' };
const sortCaret: React.CSSProperties = { marginLeft: 4, fontSize: '0.62rem', color: 'var(--faint)' };
const numCell: React.CSSProperties = { textAlign: 'right' };
