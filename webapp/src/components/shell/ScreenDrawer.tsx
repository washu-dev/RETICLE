import { useEffect, useMemo, useState } from 'react';
import { X, ExternalLink } from 'lucide-react';
import Provenance from '../washu/Provenance';
import { fetchScreenDetail, type ScreenDetail } from '../../services/reticleApi';
import { ApiError } from '../../services/api';
import { labelFor, ASSAY_DOMAIN, MODALITY } from '../../data/screenVocab';

/**
 * The screen drawer — opens a matched screen's own data without leaving the
 * results view (mirrors GeneDrawer's overlay). Shows the screen's metadata,
 * link-outs to the paper (PubMed) and the original screen (BioGRID ORCS), and
 * the screen's genes as clickable tokens that route into the single-gene lookup.
 *
 * Sits at z-index 55 — below GeneDrawer (60) — so a gene opened from here stacks
 * on top of the screen it came from.
 */

type Load<T> = { state: 'loading' | 'ok' | 'error' | 'notfound'; data: T | null };

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
  const [showAll, setShowAll] = useState(false);
  const [q, setQ] = useState('');

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!screenId) return;
    setDetail({ state: 'loading', data: null });
    setShowAll(false);
    setQ('');
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
  const filtered = useMemo(() => {
    const needle = q.trim().toUpperCase();
    const base = needle ? genes.filter((g) => g.symbol.toUpperCase().includes(needle)) : genes;
    return showAll || needle ? base : base.slice(0, 40);
  }, [genes, q, showAll]);

  const metaRows: [string, string | null | undefined][] = d ? [
    ['Rationale', d.rationale],
    ['Cell line', d.cellLine],
    ['Cell type', d.cellType],
    ['Phenotype', d.phenotype],
    ['Condition', d.conditionName],
    ['Analysis', d.analysis],
    ['Coverage', d.coverageType],
  ] : [];

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
        </div>

        <div style={drawerBody}>
          {detail.state === 'loading' && <p style={muted}>Loading screen…</p>}
          {detail.state === 'notfound' && <p style={muted}>Screen {screenId} isn't in the corpus.</p>}
          {detail.state === 'error' && <p style={muted}>Couldn't reach the corpus for this screen — try again.</p>}

          {detail.state === 'ok' && d && (
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

              {/* Metadata — measured data & literature (Source) */}
              <Provenance kind="source" sub="screen metadata" style={{ marginTop: 20 }} />
              <dl style={dl}>
                {metaRows.filter(([, v]) => v).map(([k, v]) => (
                  <div key={k} style={dlRow}>
                    <dt style={dt}>{k}</dt>
                    <dd style={dd}>{v}</dd>
                  </div>
                ))}
              </dl>

              {/* Genes */}
              <Provenance kind="computed" sub="author-called hits, strongest first" style={{ marginTop: 22 }} />
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
                {filtered.map((g) => (
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
                {filtered.length === 0 && <p style={muted}>No genes match “{q}”.</p>}
              </div>

              {!showAll && !q && genes.length > filtered.length && (
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
        </div>
      </aside>
    </>
  );
}

/* ---- styles (mirror GeneDrawer) ---- */
const drawer: React.CSSProperties = {
  position: 'fixed', top: 0, right: 0, height: '100vh', width: 520, maxWidth: '96vw',
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
