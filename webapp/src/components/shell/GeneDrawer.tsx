import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import Provenance from '../washu/Provenance';
import { fetchGeneDetail, type GeneDetail } from '../../services/reticleApi';

/**
 * The gene drawer (W2) — the "interrogate a gene" surface, folded into the same
 * screen as the analysis (W1) so there's no page-hopping. Opens whenever a gene
 * is clicked anywhere in the app.
 *
 * Phase 1: chrome + tabs, Overview backed by the existing /api/genes/{symbol}
 * endpoint. Phase 2 replaces this with the full Explorer-backed list entity
 * (context fingerprint, STRING network, reconciled relatives methods).
 */

type Tab = 'ov' | 'why' | 'rel';

const TABS: { id: Tab; label: string }[] = [
  { id: 'ov', label: 'Overview' },
  { id: 'why', label: 'Why a hit / not' },
  { id: 'rel', label: 'Relatives' },
];

export default function GeneDrawer({ symbol, onClose }: { symbol: string | null; onClose: () => void }) {
  const open = symbol != null;
  const [tab, setTab] = useState<Tab>('ov');
  const [detail, setDetail] = useState<GeneDetail | null>(null);
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle');

  // Esc to close.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Load gene detail when the symbol changes.
  useEffect(() => {
    if (!symbol) return;
    setTab('ov');
    setDetail(null);
    setState('loading');
    const ctrl = new AbortController();
    fetchGeneDetail(symbol, ctrl.signal)
      .then((d) => { setDetail(d); setState('idle'); })
      .catch((e) => { if (e?.name !== 'AbortError') setState('error'); });
    return () => ctrl.abort();
  }, [symbol]);

  return (
    <>
      <div
        className={`overlay${open ? '' : ' hidden'}`}
        style={{ display: open ? 'block' : 'none' }}
        onClick={onClose}
      />
      <aside
        className="drawer"
        style={{ ...drawer, transform: open ? 'none' : 'translateX(100%)' }}
        aria-label="Gene entity"
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
      >
        <div style={drawerHead}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <div>
              <div className="eyebrow">The list entity</div>
              <h3 style={{ fontWeight: 700, fontSize: '1.5rem', margin: '6px 0 0' }}>{symbol ?? ''}</h3>
              <div style={{ fontSize: '0.8rem', color: 'var(--faint)', marginTop: 4 }}>
                {detail?.symbol ? `${detail.screens ?? '—'} screens · ${detail.pubs ?? '—'} publications` : ''}
              </div>
            </div>
            <button style={xclose} onClick={onClose} aria-label="Close">
              <X size={20} />
            </button>
          </div>
          <div style={tabs} role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={tab === t.id}
                onClick={() => setTab(t.id)}
                style={{ ...tabBtn, ...(tab === t.id ? tabBtnOn : null) }}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div style={drawerBody}>
          {tab === 'ov' && (
            <>
              {state === 'loading' && <p style={muted}>Looking up {symbol} across the corpus…</p>}
              {state === 'error' && (
                <p style={muted}>Couldn't load {symbol}. Check the symbol, or try again.</p>
              )}
              {state === 'idle' && detail && (
                <>
                  {detail.hypothesis && (
                    <div className="ai-panel">
                      <Provenance kind="ai" sub="hypothesis-generating; verify against sources" />
                      <p style={{ marginTop: 8 }}>{detail.hypothesis}</p>
                    </div>
                  )}
                  {detail.mechanisticContext && (
                    <p style={{ marginTop: 16, fontSize: '0.95rem', lineHeight: 1.6 }}>
                      {detail.mechanisticContext}
                    </p>
                  )}
                  {detail.citations?.length > 0 && (
                    <>
                      <h4 style={mini}>Citations</h4>
                      {detail.citations.map((c, i) => (
                        <div key={i} style={{ fontSize: '0.85rem', color: 'var(--fg-muted)', marginBottom: 6 }}>
                          {c.text}{' '}
                          {c.pmid && (
                            <a href={`https://pubmed.ncbi.nlm.nih.gov/${c.pmid}`} target="_blank" rel="noreferrer">
                              PMID {c.pmid}
                            </a>
                          )}
                        </div>
                      ))}
                    </>
                  )}
                </>
              )}
            </>
          )}

          {tab === 'why' && (
            <div>
              <Provenance kind="source" sub="coming in a later pass" />
              <p style={{ ...muted, marginTop: 10 }}>
                Where {symbol} is a hit — and where it's measured but not — grouped by phenotype and
                pressure. Wiring to the corpus lands with the Explorer data pass.
              </p>
            </div>
          )}

          {tab === 'rel' && (
            <div>
              <Provenance kind="computed" sub="coming in a later pass" />
              <p style={{ ...muted, marginTop: 10 }}>
                Genes that behave like {symbol}, with the reconciled hit-based and co-essentiality
                methods. Lands with the Explorer data pass.
              </p>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

/* ---- styles ---- */
const drawer: React.CSSProperties = {
  position: 'fixed', top: 0, right: 0, height: '100vh', width: 452, maxWidth: '94vw',
  background: '#fff', borderLeft: '1px solid var(--border)', boxShadow: 'var(--shadow)',
  transition: 'transform 0.24s cubic-bezier(0.4,0,0.2,1)', zIndex: 60,
  display: 'flex', flexDirection: 'column',
};
const drawerHead: React.CSSProperties = {
  borderTop: '3px solid var(--washu-red)', padding: '18px 22px 0', borderBottom: '1px solid var(--border)',
};
const xclose: React.CSSProperties = { marginLeft: 'auto', color: 'var(--faint)', padding: '0 4px', lineHeight: 1 };
const tabs: React.CSSProperties = { display: 'flex', gap: 4, marginTop: 12 };
const tabBtn: React.CSSProperties = {
  padding: '12px', fontSize: '0.84rem', fontWeight: 600, color: 'var(--fg-muted)',
  borderBottom: '2px solid transparent', marginBottom: -1,
};
const tabBtnOn: React.CSSProperties = { color: 'var(--washu-red)', borderBottomColor: 'var(--washu-red)' };
const drawerBody: React.CSSProperties = { overflowY: 'auto', padding: '20px 22px 60px', flex: 1 };
const muted: React.CSSProperties = { color: 'var(--fg-muted)', fontSize: '0.9rem', lineHeight: 1.6 };
const mini: React.CSSProperties = {
  fontSize: '0.7rem', letterSpacing: '0.07em', textTransform: 'uppercase',
  color: 'var(--fg-muted)', margin: '20px 0 8px', fontWeight: 700,
};
