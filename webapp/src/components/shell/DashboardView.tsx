import { useState, useEffect } from 'react';
import { ExternalLink } from 'lucide-react';
import DashboardShell, { type ShellSection, type ContextItem } from './DashboardShell';
import GeneDrawer from './GeneDrawer';
import ScreenDrawer from './ScreenDrawer';
import Provenance, { ProvenanceLegend } from '../washu/Provenance';
import {
  fetchPathways, pubmedUrl, orcsUrl,
  type QueryResponse, type PathwayResult, type MatchedScreen,
} from '../../services/reticleApi';

/** The numeric BioGRID ORCS screen id for a matched screen (used to open its
 *  detail + external link). biogridId is the screen_id on real data; strip any
 *  "ORCS-" prefix from mock ids so both paths resolve. */
function screenIdOf(s: MatchedScreen): string {
  const digits = String(s.biogridId ?? '').replace(/\D/g, '');
  return digits || String(s.id);
}

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
  const [detailScreen, setDetailScreen] = useState<string | null>(null);
  const [numScreens, setNumScreens] = useState(false);
  const [numGenes, setNumGenes] = useState(false);
  const [pathways, setPathways] = useState<PathwayResult | null>(null);
  const openGene = (symbol: string) => setDrawerGene(symbol);

  // Pathway enrichment over the query genes (Enrichr). Fails soft — the section
  // keeps its "coming" state if the endpoint is unavailable or returns nothing.
  useEffect(() => {
    const symbols = (genes ?? []).map((g) => g.symbol).filter(Boolean).slice(0, 300);
    if (symbols.length === 0) return;
    const ctrl = new AbortController();
    fetchPathways(symbols, undefined, ctrl.signal)
      .then(setPathways)
      .catch(() => setPathways(null));
    return () => ctrl.abort();
  }, [genes]);

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

  // Client-side export of the matched-screens table. Column names flag the
  // uncalibrated stats so a downstream reader can't mistake them for calibrated.
  const exportResults = () => {
    const header = [
      'screen', 'citation', 'pmid', 'organism', 'modality', 'cell_type', 'direction',
      'shared_genes', 'total_genes', 'raw_rho_uncalibrated', 'fdr_placeholder',
    ];
    const rows = screens.map((s) => [
      s.name, s.citation, s.pmid, s.organism, s.modality, s.cellType, s.directionality,
      s.sharedGenes, s.totalGenes, s.rho, s.fdr,
    ]);
    downloadCsv('reticle-matched-screens.csv', header, rows);
  };

  return (
    <>
      <DashboardShell
        sections={SECTIONS}
        context={context}
        onNewAnalysis={onNewAnalysis}
        onLookupGene={openGene}
        onExport={screens.length > 0 ? exportResults : undefined}
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
          <SecHead
            title="Matched screens"
            right={screens.length > 0 ? <NumbersToggle on={numScreens} onClick={() => setNumScreens((v) => !v)} /> : undefined}
          />
          <Provenance kind="computed" sub="ranked by shared hits · support = shared genes" style={{ marginTop: 8 }} />
          <p style={sub}>Published screens probing biology like yours, ranked by overlap.</p>
          {screens.length > 0 ? (
            <div className="card" style={{ padding: 0, overflow: 'hidden', marginTop: 14 }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Screen</th><th>Shared context</th><th>Direction</th>
                    <th>Shared genes</th><th>Links</th>
                    {numScreens && <th style={{ textAlign: 'right' }}>raw ρ*</th>}
                    {numScreens && <th style={{ textAlign: 'right' }}>FDR*</th>}
                  </tr>
                </thead>
                <tbody>
                  {screens.map((s) => (
                    <tr key={s.id} className="clickable" onClick={() => setDetailScreen(screenIdOf(s))}
                        title="Open this screen's data">
                      <td>
                        <span className="lk" style={{ fontWeight: 600, color: 'var(--washu-red)' }}>{s.name}</span>
                        <div style={faint}>{s.citation}</div>
                      </td>
                      <td>{[s.cellType, s.organism, s.modality].filter(Boolean).join(' · ') || '—'}</td>
                      <td><DirectionBadge d={s.directionality} /></td>
                      <td>
                        <span className="tnum" style={{ color: 'var(--fg-muted)' }}>{s.sharedGenes}/{s.totalGenes}</span>
                        <SharedGeneChips symbols={s.sharedGeneSymbols} onOpen={openGene} />
                      </td>
                      <td><ScreenLinks pmid={s.pmid} screenId={screenIdOf(s)} /></td>
                      {numScreens && <td style={{ textAlign: 'right' }} className="tnum">{s.rho.toFixed(2)}</td>}
                      {numScreens && <td style={{ textAlign: 'right' }} className="tnum">{s.fdr.toExponential(1)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyNote>No matched screens in this result. Run an analysis to populate this list.</EmptyNote>
          )}
          <p style={faintHint}>
            Click a screen to open its data and genes. Shared genes and links open in place or a new tab.
            {' '}
            {numScreens
              ? '* Raw pipeline values: ρ is an uncalibrated aggregate and FDR is a placeholder until the correlation engine reports calibrated statistics. Read support from shared genes for now.'
              : 'Similarity statistics (ρ, FDR) are still uncalibrated — reveal them with “show numbers,” and read with care.'}
          </p>
        </section>

        {/* ── SHARED PATHWAYS ── */}
        <section id="pathways" style={section}>
          <SecHead title="Shared pathways" />
          {pathways && pathways.terms.length > 0 ? (
            <>
              <Provenance kind="computed" sub={`enrichment · ${pathways.library.replace(/_/g, ' ')}`} style={{ marginTop: 8 }} />
              <p style={sub}>Pathways over-represented among your genes, ranked by combined score.</p>
              <div style={{ marginTop: 14 }}>
                {pathways.terms.map((t) => (
                  <div key={t.term} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                      <span style={{ fontWeight: 600, fontSize: '0.92rem' }}>{t.term}</span>
                      <span className="tnum" style={{ color: 'var(--faint)', fontSize: '0.8rem', flex: '0 0 auto' }}>
                        q {t.adj_p_value.toExponential(1)}
                      </span>
                    </div>
                    {t.overlap_genes.length > 0 && (
                      <div style={{ fontSize: '0.8rem', color: 'var(--fg-muted)', marginTop: 3 }}>
                        {t.overlap_genes.slice(0, 8).join(' · ')}{t.overlap_genes.length > 8 ? ' …' : ''}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <Provenance kind="computed" sub="pathway enrichment" style={{ marginTop: 8 }} />
              <ComingNote>
                No enriched pathways to show yet — this populates from Enrichr once an analysis with
                genes is loaded and the enrichment service is reachable.
              </ComingNote>
            </>
          )}
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
          <SecHead
            title="Genes worth a look"
            right={darkGenes.length > 0 ? <NumbersToggle on={numGenes} onClick={() => setNumGenes((v) => !v)} /> : undefined}
          />
          <Provenance kind="computed" sub="dark-matter candidates from your result" style={{ marginTop: 8 }} />
          <p style={sub}>Low-ranked in your list, but the corpus flags them as important. Open any gene.</p>
          {darkGenes.length > 0 ? (
            <div className="card" style={{ padding: 0, overflow: 'hidden', marginTop: 14 }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Gene</th><th style={{ textAlign: 'right' }}>Darkness</th><th style={{ textAlign: 'right' }}>Screens</th>
                    {numGenes && <th style={{ textAlign: 'right' }}>Corr.</th>}
                    {numGenes && <th style={{ textAlign: 'right' }}>Pubs</th>}
                    {numGenes && <th style={{ textAlign: 'right' }}>GO terms</th>}
                  </tr>
                </thead>
                <tbody>
                  {darkGenes.map((g) => (
                    <tr key={g.symbol} className="clickable" onClick={() => openGene(g.symbol)}>
                      <td>
                        <span className="lk" style={{ fontWeight: 600, color: 'var(--washu-red)' }}>{g.symbol}</span>
                        {!g.isBright && g.darkScore >= 6 && (
                          <span className="badge badge-dark" style={{ marginLeft: 8 }}>dark</span>
                        )}
                        {g.isBright && <span className="badge badge-ko" style={{ marginLeft: 8 }}>known</span>}
                      </td>
                      <td style={{ textAlign: 'right' }} className="tnum">{g.darkScore}/10</td>
                      <td style={{ textAlign: 'right' }} className="tnum">{g.screens}</td>
                      {numGenes && <td style={{ textAlign: 'right' }} className="tnum">{g.correlation.toFixed(2)}</td>}
                      {numGenes && <td style={{ textAlign: 'right' }} className="tnum">{g.pubs}</td>}
                      {numGenes && <td style={{ textAlign: 'right' }} className="tnum">{g.goTerms}</td>}
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

      <ScreenDrawer
        screenId={detailScreen}
        onClose={() => setDetailScreen(null)}
        onOpenGene={openGene}
      />
      <GeneDrawer symbol={drawerGene} organism={options?.organism} onClose={() => setDrawerGene(null)} />
    </>
  );
}

/* Shared query genes that are hits in a matched screen — clickable into gene lookup. */
function SharedGeneChips({ symbols, onOpen }: { symbols?: string[]; onOpen: (s: string) => void }) {
  if (!symbols || symbols.length === 0) return null;
  const shown = symbols.slice(0, 6);
  const extra = symbols.length - shown.length;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 6 }}>
      {shown.map((sym) => (
        <button
          key={sym}
          className="lk"
          onClick={(e) => { e.stopPropagation(); onOpen(sym); }}
          style={chip}
          title={`Open ${sym}`}
        >{sym}</button>
      ))}
      {extra > 0 && <span style={{ fontSize: '0.74rem', color: 'var(--faint)', alignSelf: 'center' }}>+{extra}</span>}
    </div>
  );
}

/* PubMed + BioGRID link-outs; stopPropagation so they don't open the drawer. */
function ScreenLinks({ pmid, screenId }: { pmid?: string; screenId: string }) {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
      {pmid && (
        <a href={pubmedUrl(pmid)} target="_blank" rel="noreferrer" title="Open the paper in PubMed"
           style={linkIcon}>PubMed <ExternalLink size={12} /></a>
      )}
      <a href={orcsUrl(screenId)} target="_blank" rel="noreferrer" title="Open the screen in BioGRID ORCS"
         style={linkIcon}>ORCS <ExternalLink size={12} /></a>
    </div>
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
function SecHead({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
      <h2 style={h2}>{title}</h2>
      {right && <><span style={{ flex: 1 }} />{right}</>}
    </div>
  );
}
function NumbersToggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return <button onClick={onClick} style={numBtn}>{on ? 'hide numbers' : 'show numbers'}</button>;
}
function DirectionBadge({ d }: { d: string }) {
  const v = (d || '').toLowerCase();
  if (v.includes('agree') || v.includes('same') || v.includes('concord'))
    return <span className="badge badge-agree">same direction</span>;
  if (v.includes('invert') || v.includes('oppos') || v.includes('discord'))
    return <span className="badge badge-inverted">opposite</span>;
  return <span style={{ color: 'var(--fg-muted)' }}>{d || '—'}</span>;
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
const numBtn: React.CSSProperties = {
  fontSize: '0.78rem', color: 'var(--fg-muted)', border: '1px solid var(--border-2)',
  borderRadius: 6, padding: '6px 11px', background: '#fff',
};
const chip: React.CSSProperties = {
  padding: '2px 8px', borderRadius: 5, border: '1px solid rgba(186,12,47,0.28)',
  background: 'rgba(186,12,47,0.04)', color: 'var(--washu-red)', fontSize: '0.76rem', fontWeight: 600,
};
const linkIcon: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 3,
  fontSize: '0.76rem', color: 'var(--teal)', fontWeight: 600, textDecoration: 'none', whiteSpace: 'nowrap',
};

/* ---- CSV export (client-side) ---- */
function csvCell(v: unknown): string {
  const s = v == null ? '' : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function downloadCsv(filename: string, header: string[], rows: unknown[][]) {
  const text = [header, ...rows].map((r) => r.map(csvCell).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8;' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
