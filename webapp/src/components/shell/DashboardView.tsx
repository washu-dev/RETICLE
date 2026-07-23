import { useState } from 'react';
import DashboardShell, { type ShellSection, type ContextItem } from './DashboardShell';
import GeneDrawer from './GeneDrawer';
import Provenance, { ProvenanceLegend } from '../washu/Provenance';
import type { QueryResponse } from '../../services/reticleApi';

/**
 * The unified analysis view (W1) — one scrolling dashboard skinned in the WashU
 * Medicine system, with the gene drawer (W2) folded in. Sections render real
 * data where the backend provides it and honest "coming" states where it does
 * not, per the backend-readiness-first sequencing.
 */

const SECTIONS: ShellSection[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'screens', label: 'Matched screens' },
  { id: 'pathways', label: 'Shared pathways' },
  { id: 'surprises', label: 'Surprises' },
  { id: 'genes', label: 'Genes worth a look' },
];

interface DashboardViewProps {
  genes: { symbol: string; score: number }[] | null;
  options: { organism?: string; modalities?: string[]; algorithm?: string } | null;
  queryResults: QueryResponse | null;
  onNewAnalysis: () => void;
}

export default function DashboardView({ genes, options, queryResults, onNewAnalysis }: DashboardViewProps) {
  const [drawerGene, setDrawerGene] = useState<string | null>(null);
  const openGene = (symbol: string) => setDrawerGene(symbol);

  const geneCount = genes?.length ?? 0;
  const context: ContextItem[] = [
    { k: 'Screen', v: 'Your screen' },
    { k: 'Organism', v: options?.organism ?? '—' },
    { k: 'Modality', v: options?.modalities?.join(', ') ?? '—' },
    { k: 'Genes', v: geneCount ? geneCount.toLocaleString() : '—' },
  ];

  const stats = queryResults?.stats;
  const screens = queryResults?.matchedScreens ?? [];
  const darkGenes = queryResults?.darkGenes ?? [];

  return (
    <>
      <DashboardShell
        sections={SECTIONS}
        context={context}
        onNewAnalysis={onNewAnalysis}
        onLookupGene={openGene}
      >
        <ProvenanceLegend style={{ marginBottom: 4 }} />

        {/* ── OVERVIEW ── */}
        <section id="overview" style={section}>
          <div style={hero}>
            <div className="eyebrow">Screen comparison</div>
            <h1 style={heroH1}>
              Your screen, in <span className="emph">context</span>
            </h1>
            <p style={heroLead}>
              How your {geneCount ? geneCount.toLocaleString() : ''} genes compare against the harmonized corpus.
            </p>

            <div className="ai-panel" style={{ marginTop: 22 }}>
              <Provenance kind="ai" sub="coming with the AI narrative pass" />
              <p style={{ marginTop: 8 }}>
                A plain-language read of what the corpus sees in your screen — the shared contexts and
                what the model noticed that you may not have — lands once the narrative endpoint is wired.
              </p>
            </div>

            <div style={{ marginTop: 22 }}>
              <Provenance kind="computed" sub="counts from your result & the corpus" />
              <div style={statGrid}>
                <Stat n={stats?.screensCompared} label="screens compared" />
                <Stat n={stats?.significantMatches} label="strong matches" />
                <Stat n={stats?.agreeDirectionality} label="same-direction matches" />
                <Stat n={stats?.queryGeneCount ?? geneCount} label="genes queried" />
              </div>
            </div>
          </div>
        </section>

        {/* ── MATCHED SCREENS ── */}
        <section id="screens" style={section}>
          <SecHead title="Matched screens" />
          <Provenance kind="computed" sub="ranked by shared hits · support = shared genes" style={{ marginTop: 8 }} />
          <p style={sub}>Published screens probing biology like yours, ranked by overlap.</p>
          {screens.length > 0 ? (
            <div className="card" style={{ padding: 0, overflow: 'hidden', marginTop: 14 }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Screen</th><th>Shared context</th><th>Direction</th><th style={{ textAlign: 'right' }}>Shared genes</th>
                  </tr>
                </thead>
                <tbody>
                  {screens.map((s) => (
                    <tr key={s.id}>
                      <td><b>{s.name}</b><div style={faint}>{s.citation}</div></td>
                      <td>{[s.cellType, s.modality].filter(Boolean).join(' · ') || '—'}</td>
                      <td>{s.directionality}</td>
                      <td style={{ textAlign: 'right' }} className="tnum">{s.sharedGenes}/{s.totalGenes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyNote>No matched screens in this result. Run an analysis to populate this list.</EmptyNote>
          )}
          <p style={faintHint}>
            Similarity statistics (ρ, FDR) are shown as plain support here until the correlation
            engine reports calibrated values — see the backend track.
          </p>
        </section>

        {/* ── SHARED PATHWAYS (unbacked) ── */}
        <section id="pathways" style={section}>
          <SecHead title="Shared pathways" />
          <Provenance kind="computed" sub="coming with pathway enrichment" style={{ marginTop: 8 }} />
          <ComingNote>
            Pathways enriched across the matched screens — including de-novo annotations proposed from
            the CRISPR results — arrive when the enrichment endpoint is built.
          </ComingNote>
        </section>

        {/* ── SURPRISES (unbacked) ── */}
        <section id="surprises" style={section}>
          <SecHead title="Surprises" />
          <Provenance kind="computed" sub="coming with residual analysis" style={{ marginTop: 8 }} />
          <ComingNote>
            Novel dependencies — genes that scored strongly here but the corpus wouldn't predict —
            rank on the residual signal once it's surfaced from the pipeline.
          </ComingNote>
        </section>

        {/* ── GENES WORTH A LOOK ── */}
        <section id="genes" style={{ ...section, borderBottom: 'none' }}>
          <SecHead title="Genes worth a look" />
          <Provenance kind="computed" sub="dark-matter candidates from your result" style={{ marginTop: 8 }} />
          <p style={sub}>Low-ranked in your list, but the corpus flags them as important. Open any gene.</p>
          {darkGenes.length > 0 ? (
            <div className="card" style={{ padding: 0, overflow: 'hidden', marginTop: 14 }}>
              <table className="data-table">
                <thead>
                  <tr><th>Gene</th><th style={{ textAlign: 'right' }}>Darkness</th><th style={{ textAlign: 'right' }}>Screens</th></tr>
                </thead>
                <tbody>
                  {darkGenes.map((g) => (
                    <tr key={g.symbol} className="clickable" onClick={() => openGene(g.symbol)}>
                      <td>
                        <span className="lk" style={{ fontWeight: 600, color: 'var(--washu-red)' }}>{g.symbol}</span>
                        {!g.isBright && g.darkScore >= 6 && (
                          <span className="badge badge-dark" style={{ marginLeft: 8 }}>dark</span>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }} className="tnum">{g.darkScore}/10</td>
                      <td style={{ textAlign: 'right' }} className="tnum">{g.screens}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyNote>No dark-gene candidates in this result.</EmptyNote>
          )}
        </section>
      </DashboardShell>

      <GeneDrawer symbol={drawerGene} organism={options?.organism} onClose={() => setDrawerGene(null)} />
    </>
  );
}

/* ---- small pieces ---- */
function Stat({ n, label }: { n?: number; label: string }) {
  return (
    <div style={statCell}>
      <div style={statN} className="tnum">{n != null ? n.toLocaleString() : '—'}</div>
      <div style={statL}>{label}</div>
    </div>
  );
}
function SecHead({ title }: { title: string }) {
  return <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}><h2 style={h2}>{title}</h2></div>;
}
function ComingNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="card" style={{ marginTop: 14, borderStyle: 'dashed', color: 'var(--fg-muted)', fontSize: '0.92rem', lineHeight: 1.6 }}>
      {children}
    </div>
  );
}
function EmptyNote({ children }: { children: React.ReactNode }) {
  return <p style={{ ...faintHint, marginTop: 14 }}>{children}</p>;
}

/* ---- styles ---- */
const section: React.CSSProperties = { padding: '26px 0', borderBottom: '1px solid var(--border)', scrollMarginTop: 132 };
const hero: React.CSSProperties = { background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 10, padding: '30px 32px', marginTop: 14 };
const heroH1: React.CSSProperties = { fontWeight: 700, fontSize: '2.4rem', lineHeight: 1.1, letterSpacing: '-0.01em', margin: '8px 0 4px' };
const heroLead: React.CSSProperties = { color: 'var(--fg-muted)', fontSize: '1.1rem', margin: 0 };
const statGrid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 1, background: 'var(--border)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', marginTop: 6 };
const statCell: React.CSSProperties = { background: '#fff', padding: '19px 22px' };
const statN: React.CSSProperties = { fontWeight: 700, fontSize: '2.2rem', lineHeight: 1, color: 'var(--washu-red)' };
const statL: React.CSSProperties = { fontSize: '0.875rem', color: 'var(--fg-muted)', marginTop: 8, lineHeight: 1.35 };
const h2: React.CSSProperties = { fontWeight: 700, fontSize: '1.55rem', lineHeight: 1.15, margin: 0 };
const sub: React.CSSProperties = { color: 'var(--fg-muted)', fontSize: '1rem', maxWidth: '72ch', margin: '6px 0 0' };
const faint: React.CSSProperties = { fontSize: '0.78rem', color: 'var(--faint)', marginTop: 2 };
const faintHint: React.CSSProperties = { fontSize: '0.82rem', color: 'var(--faint)', marginTop: 10 };
