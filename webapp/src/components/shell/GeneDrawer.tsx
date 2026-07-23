import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import Provenance from '../washu/Provenance';
import {
  fetchGeneExplorer,
  fetchGeneContext,
  type GeneExplorer,
  type GeneContext,
} from '../../services/reticleApi';
import { ApiError } from '../../services/api';

/**
 * The gene drawer (W2) — the "interrogate a gene" surface folded into the same
 * screen as the analysis (W1). All three tabs render REAL Explorer data:
 *   Overview   — identity + NCBI summary + the context fingerprint (behavior
 *                across screens, split by assay domain) + darkness
 *   Why a hit  — the per-condition / per-process hit ledgers
 *   Relatives  — STRING functional partners (co-essentiality method); the
 *                hit-based method is labelled as the pending reconciliation
 *
 * Gene behavior (/api/gene, DB) and external context (/api/context, NCBI+STRING)
 * load independently so identity/behavior show immediately while the slower
 * external lookups fill in.
 */

type Tab = 'ov' | 'why' | 'rel';
type RelMethod = 'A' | 'B';
type Load<T> = { state: 'loading' | 'ok' | 'error' | 'notfound'; data: T | null };

const TABS: { id: Tab; label: string }[] = [
  { id: 'ov', label: 'Overview' },
  { id: 'why', label: 'Why a hit / not' },
  { id: 'rel', label: 'Relatives' },
];

const linkouts = (sym: string) => [
  ['NCBI', `https://www.ncbi.nlm.nih.gov/gene/?term=${encodeURIComponent(sym)}`],
  ['UniProt', `https://www.uniprot.org/uniprotkb?query=${encodeURIComponent(sym)}`],
  ['STRING', `https://string-db.org/cgi/network?identifiers=${encodeURIComponent(sym)}`],
  ['PubMed', `https://pubmed.ncbi.nlm.nih.gov/?term=${encodeURIComponent(sym)}`],
];

export default function GeneDrawer({
  symbol,
  organism = 'Homo sapiens',
  onClose,
}: {
  symbol: string | null;
  organism?: string;
  onClose: () => void;
}) {
  const open = symbol != null;
  const [tab, setTab] = useState<Tab>('ov');
  const [method, setMethod] = useState<RelMethod>('B');
  const [gene, setGene] = useState<Load<GeneExplorer>>({ state: 'loading', data: null });
  const [ctx, setCtx] = useState<Load<GeneContext>>({ state: 'loading', data: null });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!symbol) return;
    setTab('ov');
    setMethod('B');
    setGene({ state: 'loading', data: null });
    setCtx({ state: 'loading', data: null });
    const ctrl = new AbortController();

    fetchGeneExplorer(symbol, ctrl.signal)
      .then((d) => setGene({ state: 'ok', data: d }))
      .catch((e) => {
        if (e?.name === 'AbortError') return;
        setGene({ state: e instanceof ApiError && e.status === 404 ? 'notfound' : 'error', data: null });
      });

    fetchGeneContext(symbol, organism, ctrl.signal)
      .then((d) => setCtx({ state: 'ok', data: d }))
      .catch((e) => { if (e?.name !== 'AbortError') setCtx({ state: 'error', data: null }); });

    return () => ctrl.abort();
  }, [symbol, organism]);

  const g = gene.data;
  const c = ctx.data;
  const ann = c?.annotation;
  const metaBits = [
    g?.organism ?? organism,
    ann?.entrez ? `Entrez ${ann.entrez}` : null,
    ann?.name || null,
  ].filter(Boolean);

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
                {metaBits.join(' · ')}
              </div>
            </div>
            <button style={xclose} onClick={onClose} aria-label="Close"><X size={20} /></button>
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
          {gene.state === 'notfound' && (
            <p style={muted}>No screen data for {symbol} in the corpus. Check the symbol or organism.</p>
          )}
          {gene.state === 'error' && (
            <p style={muted}>Couldn't reach the corpus for {symbol}. The API may be offline — try again.</p>
          )}

          {tab === 'ov' && <OverviewPane symbol={symbol!} gene={gene} ctx={ctx} />}
          {tab === 'why' && <WhyPane gene={gene} />}
          {tab === 'rel' && <RelativesPane ctx={ctx} method={method} setMethod={setMethod} />}
        </div>
      </aside>
    </>
  );
}

/* ─────────────────────────── Overview ─────────────────────────── */
function OverviewPane({ symbol, gene, ctx }: { symbol: string; gene: Load<GeneExplorer>; ctx: Load<GeneContext> }) {
  const g = gene.data;
  const c = ctx.data;
  const hits =
    (g?.fitness?.n_hits ?? 0) + (g?.stress?.n_hits ?? 0) + (g?.reporter?.n_hits ?? 0);
  const assayed = g?.n_total ?? 0;

  return (
    <>
      {/* NCBI summary — Source, not AI */}
      {ctx.state === 'ok' && c?.annotation?.summary ? (
        <div>
          <Provenance kind="source" sub="NCBI gene summary" />
          <p style={{ marginTop: 8, fontSize: '0.95rem', lineHeight: 1.6 }}>{c.annotation.summary}</p>
        </div>
      ) : ctx.state === 'loading' ? (
        <p style={muted}>Loading corpus context for {symbol}…</p>
      ) : null}

      {/* Behavior across screens — the context fingerprint */}
      {gene.state === 'ok' && g && (
        <>
          <Provenance kind="computed" sub="behavior across screens" style={{ marginTop: 20 }} />
          <h4 style={mini}>Hit across the corpus</h4>
          <Meter label={`hit in ${hits} of ${assayed} assayed`} value={assayed ? hits / assayed : 0} />

          <h4 style={mini}>Context fingerprint</h4>
          {g.fitness && (
            <FpBar label="proliferation / fitness" value={g.fitness.hit_rate} note={`${leanWord(g.fitness.lean)} · ${g.fitness.n_hits}/${g.fitness.n} hit`} />
          )}
          {g.stress && (
            <FpBar label="stress / selection" value={g.stress.n ? g.stress.n_hits / g.stress.n : 0} note={`${g.stress.n_hits}/${g.stress.n} hit`} />
          )}
          {g.reporter && g.reporter.n > 0 && (
            <FpBar label="reporter / marker" value={g.reporter.n ? g.reporter.n_hits / g.reporter.n : 0} note={`${g.reporter.n_hits}/${g.reporter.n} hit`} />
          )}
        </>
      )}

      {/* Darkness */}
      {ctx.state === 'ok' && c?.darkness && (
        <>
          <Provenance kind="computed" sub="publication & annotation density" style={{ marginTop: 20 }} />
          <h4 style={mini}>How well studied</h4>
          <FpBar
            label={c.darkness.band === 'dark' ? 'rarely studied' : c.darkness.band === 'grey' ? 'moderately studied' : 'well characterized'}
            value={c.darkness.score / 10}
            note={`darkness ${c.darkness.score.toFixed(1)} · ${c.darkness.pubmed_count} pubs`}
            dark
          />
        </>
      )}

      {/* Links */}
      <h4 style={mini}>Links</h4>
      <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap' }}>
        {linkouts(symbol).map(([label, href]) => (
          <a key={label} href={href} target="_blank" rel="noreferrer" style={linkBtn}>{label}</a>
        ))}
      </div>
    </>
  );
}

/* ─────────────────────────── Why a hit ─────────────────────────── */
function WhyPane({ gene }: { gene: Load<GeneExplorer> }) {
  const g = gene.data;
  if (gene.state === 'loading') return <p style={muted}>Loading hit contexts…</p>;
  if (!g) return null;

  const hasFitnessLean = g.fitness && g.fitness.lean !== 'mixed';
  const stress = g.stress?.ledger ?? [];
  const reporter = g.reporter?.ledger ?? [];
  const nothing = !hasFitnessLean && stress.length === 0 && reporter.length === 0;

  return (
    <>
      <Provenance kind="source" sub="author-called hits across the corpus" />
      <h4 style={mini}>Where it's a hit</h4>
      {nothing && <p style={muted}>No author-called hits recorded for this gene.</p>}

      {hasFitnessLean && g.fitness && (
        <Row
          head="Proliferation / fitness"
          sub={`${leanWord(g.fitness.lean)} — a hit in ${g.fitness.n_hits} of ${g.fitness.n} fitness screens`}
        />
      )}
      {stress.map((s) => (
        <Row
          key={s.condition}
          head={s.condition}
          sub={`${directionWord(s.direction)} · ${s.n_screens} screen${s.n_screens === 1 ? '' : 's'} across ${s.n_papers} paper${s.n_papers === 1 ? '' : 's'}`}
          tag={s.class}
        />
      ))}
      {reporter.map((r) => (
        <Row
          key={r.process}
          head={`Regulates ${r.process}`}
          sub={`${r.n_screens} screen${r.n_screens === 1 ? '' : 's'} across ${r.n_papers} paper${r.n_papers === 1 ? '' : 's'}`}
        />
      ))}

      <p style={{ ...faintHint, marginTop: 16 }}>
        "Not a hit" isn't shown as a list — a gene is measured in {g.n_total} screens here; the rest
        fall under a different phenotype or pressure, or below that screen's own cutoff.
      </p>
    </>
  );
}

/* ─────────────────────────── Relatives ─────────────────────────── */
function RelativesPane({ ctx, method, setMethod }: { ctx: Load<GeneContext>; method: RelMethod; setMethod: (m: RelMethod) => void }) {
  const partners = ctx.data?.string_partners ?? [];
  return (
    <>
      <div style={{ fontSize: '0.78rem', color: 'var(--fg-muted)', marginBottom: 12 }}>
        Method:{' '}
        <span style={seg}>
          <button style={{ ...segBtn, ...(method === 'A' ? segBtnOn : null) }} onClick={() => setMethod('A')}>Hit-based</button>
          <button style={{ ...segBtn, ...(method === 'B' ? segBtnOn : null) }} onClick={() => setMethod('B')}>Co-essentiality</button>
        </span>
      </div>

      {method === 'B' ? (
        <>
          <Provenance kind="computed" sub="STRING functional partners" />
          {ctx.state === 'loading' && <p style={{ ...muted, marginTop: 10 }}>Loading partners…</p>}
          {ctx.state === 'ok' && partners.length === 0 && (
            <p style={{ ...muted, marginTop: 10 }}>No STRING functional partners returned.</p>
          )}
          {partners.length > 0 && (
            <div style={{ marginTop: 10 }}>
              {partners.map((p) => (
                <div key={p.partner} style={partnerRow}>
                  <span style={{ fontWeight: 600 }}>{p.partner}</span>
                  <span className="tnum" style={{ color: 'var(--faint)' }}>STRING {p.score.toFixed(3)}</span>
                </div>
              ))}
            </div>
          )}
          <p style={{ ...faintHint, marginTop: 12 }}>
            Functional partners from STRING stand in for co-essentiality until the pure-CRISPR
            co-essentiality network is served from the pipeline.
          </p>
        </>
      ) : (
        <>
          <Provenance kind="computed" sub="coming with the relatedness pipeline" />
          <p style={{ ...muted, marginTop: 10 }}>
            The hit-based method (co-hit · specificity · co-citation · context, folding in literature)
            comes from the relatedness fact tables — the backend track that reconciles the two methods.
          </p>
        </>
      )}
    </>
  );
}

/* ─────────────────────────── small pieces ─────────────────────────── */
function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div style={{ margin: '9px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', color: 'var(--fg-muted)', marginBottom: 4 }}>
        <span>{label}</span>
      </div>
      <div style={track}><i style={{ ...trackFill, width: `${clamp(value)}%` }} /></div>
    </div>
  );
}
function FpBar({ label, value, note, dark }: { label: string; value: number; note: string; dark?: boolean }) {
  return (
    <div style={fpb}>
      <span style={{ color: 'var(--fg-muted)' }}>{label}</span>
      <span style={fpTrack}><i style={{ ...fpFill, width: `${clamp(value)}%`, background: dark ? '#8a8078' : 'var(--washu-red)' }} /></span>
      <span className="tnum" style={{ color: 'var(--faint)', textAlign: 'right', fontSize: '0.72rem' }}>{note}</span>
    </div>
  );
}
function Row({ head, sub, tag }: { head: string; sub: string; tag?: string }) {
  return (
    <div style={ledgerRow}>
      <div>
        <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{head}</div>
        <div style={{ fontSize: '0.8rem', color: 'var(--fg-muted)' }}>{sub}</div>
      </div>
      {tag && <span className="badge badge-unknown" style={{ flex: '0 0 auto' }}>{tag}</span>}
    </div>
  );
}

const clamp = (v: number) => Math.max(0, Math.min(100, Math.round(v * 100)));
const leanWord = (l: string) => (l === 'essential' ? 'essential' : l === 'advantageous' ? 'growth-advantageous' : 'mixed');
const directionWord = (d: string) => (d === 'resist' ? 'resistance (KO helps)' : d === 'sensitise' ? 'sensitization (KO hurts)' : 'mixed direction');

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
  padding: '12px 10px', fontSize: '0.82rem', fontWeight: 600, color: 'var(--fg-muted)',
  borderBottom: '2px solid transparent', marginBottom: -1,
};
const tabBtnOn: React.CSSProperties = { color: 'var(--washu-red)', borderBottomColor: 'var(--washu-red)' };
const drawerBody: React.CSSProperties = { overflowY: 'auto', padding: '20px 22px 60px', flex: 1 };
const muted: React.CSSProperties = { color: 'var(--fg-muted)', fontSize: '0.9rem', lineHeight: 1.6 };
const faintHint: React.CSSProperties = { fontSize: '0.8rem', color: 'var(--faint)', lineHeight: 1.55 };
const mini: React.CSSProperties = {
  fontSize: '0.7rem', letterSpacing: '0.07em', textTransform: 'uppercase',
  color: 'var(--fg-muted)', margin: '18px 0 8px', fontWeight: 700,
};
const track: React.CSSProperties = { height: 7, background: 'var(--warm-gray)', border: '1px solid var(--border)', borderRadius: 100, overflow: 'hidden' };
const trackFill: React.CSSProperties = { display: 'block', height: '100%', background: 'var(--washu-red)' };
const fpb: React.CSSProperties = { display: 'grid', gridTemplateColumns: '128px 1fr 92px', gap: 10, alignItems: 'center', margin: '7px 0', fontSize: '0.78rem' };
const fpTrack: React.CSSProperties = { height: 8, background: 'var(--warm-gray)', border: '1px solid var(--border)', borderRadius: 100, overflow: 'hidden' };
const fpFill: React.CSSProperties = { display: 'block', height: '100%', borderRadius: 100 };
const ledgerRow: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--border)' };
const partnerRow: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', padding: '9px 0', borderBottom: '1px solid var(--border)', fontSize: '0.88rem' };
const linkBtn: React.CSSProperties = {
  padding: '7px 12px', borderRadius: 6, border: '1px solid var(--border-2)',
  background: '#fff', color: 'var(--washu-red)', fontSize: '0.8rem', fontWeight: 600, textDecoration: 'none',
};
const seg: React.CSSProperties = { display: 'inline-flex', border: '1px solid var(--border-2)', borderRadius: 6, overflow: 'hidden', verticalAlign: 'middle' };
const segBtn: React.CSSProperties = { padding: '5px 11px', fontSize: '0.78rem', fontWeight: 600, color: 'var(--fg-muted)', borderRight: '1px solid var(--border-2)' };
const segBtnOn: React.CSSProperties = { background: 'var(--warm-gray)', color: 'var(--washu-red)' };
