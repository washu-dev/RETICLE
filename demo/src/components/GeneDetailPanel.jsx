import { useState } from 'react';
import { X, ExternalLink, FlaskConical, BookOpen, Lightbulb, Activity, ChevronDown, ChevronUp, Network } from 'lucide-react';
import { GENE_RATIONALES, DARK_GENES, STRING_INTERACTORS } from '../mockData';

const DIRECTION_STYLE = {
  upregulated:   { color: 'var(--green)',  label: '↑ up'   },
  downregulated: { color: 'var(--orange)', label: '↓ down' },
  unknown:       { color: 'var(--text-3)', label: '— ?'    },
};

export default function GeneDetailPanel({ symbol, onClose }) {
  const [stringOpen, setStringOpen] = useState(false);

  if (!symbol) return null;

  const rationale  = GENE_RATIONALES[symbol];
  const geneData   = DARK_GENES.find(g => g.symbol === symbol);
  const interactors = STRING_INTERACTORS[symbol] ?? null;

  return (
    <>
      <div className="overlay" onClick={onClose} />
      <div className="slide-over">
        {/* Header */}
        <div style={{
          padding: '20px 24px', borderBottom: '1px solid var(--border)',
          position: 'sticky', top: 0, background: 'var(--bg-1)', zIndex: 1,
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
              <span className="badge badge-dark">Dark candidate</span>
              {geneData && <span style={{ fontSize: '0.78rem', color: 'var(--text-3)' }}>Darkness score: <strong style={{ color: 'var(--amber)' }}>{geneData.darkScore}</strong>/10</span>}
            </div>
            <h2 style={{ fontSize: '1.6rem', fontWeight: 800, letterSpacing: '-0.02em', fontFamily: '"JetBrains Mono",monospace' }}>{symbol}</h2>
            {geneData && (
              <div style={{ display: 'flex', gap: 16, marginTop: 6, fontSize: '0.8rem', color: 'var(--text-3)' }}>
                <span>{geneData.pubs} publications</span>
                <span>·</span>
                <span>{geneData.screens} matched screens</span>
                <span>·</span>
                <span>Pathway correlation: <strong style={{ color: 'var(--blue)' }}>{geneData.correlation}</strong></span>
              </div>
            )}
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-3)', padding: 4, borderRadius: 6, marginLeft: 12 }}>
            <X size={20} />
          </button>
        </div>

        <div style={{ padding: '24px' }}>
          {rationale ? (
            <>
              {/* Hypothesis */}
              <Section icon={<Lightbulb size={15} />} title="AI Hypothesis">
                <p style={{ fontSize: '0.9rem', color: 'var(--text-2)', lineHeight: 1.7 }}>{rationale.hypothesis}</p>
              </Section>

              {/* Mechanistic context */}
              <Section icon={<Activity size={15} />} title="Mechanistic context">
                <p style={{ fontSize: '0.9rem', color: 'var(--text-2)', lineHeight: 1.7 }}>{rationale.mechanisticContext}</p>
              </Section>

              {/* Supporting screens */}
              <Section icon={<FlaskConical size={15} />} title="Supporting screens">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {rationale.citations.map((c, i) => (
                    <a
                      key={i}
                      href={`https://pubmed.ncbi.nlm.nih.gov/${c.pmid}`}
                      target="_blank" rel="noreferrer"
                      style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '10px 14px', borderRadius: 8, gap: 10,
                        background: 'var(--bg-2)', border: '1px solid var(--border)',
                        color: 'var(--text-2)', fontSize: '0.85rem', textDecoration: 'none',
                        transition: 'border-color 0.15s',
                      }}
                      onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--blue)'}
                      onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
                    >
                      <span>{c.text}</span>
                      <ExternalLink size={13} style={{ flexShrink: 0, color: 'var(--text-3)' }} />
                    </a>
                  ))}
                </div>
              </Section>

              {/* Suggested validation */}
              <Section icon={<BookOpen size={15} />} title="Suggested next step">
                <div style={{
                  padding: '14px 16px', borderRadius: 9,
                  background: 'rgba(79,156,249,0.06)', border: '1px solid rgba(79,156,249,0.2)',
                  fontSize: '0.875rem', color: 'var(--text-2)', lineHeight: 1.6,
                }}>
                  {rationale.suggestedValidation}
                </div>
              </Section>

              {/* STRING interactors */}
              <StringSection symbol={symbol} interactors={interactors} open={stringOpen} onToggle={() => setStringOpen(o => !o)} />

              {/* External links */}
              <Section icon={null} title="External resources">
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {[
                    { label: 'NCBI Gene', url: `https://www.ncbi.nlm.nih.gov/gene?term=${symbol}[sym]` },
                    { label: 'UniProt',   url: `https://www.uniprot.org/uniprotkb?query=${symbol}+AND+organism_id:9606` },
                    { label: 'BioGRID',  url: `https://orcs.thebiogrid.org/` },
                    { label: 'STRING',   url: `https://string-db.org/network/${symbol}` },
                  ].map(l => (
                    <a
                      key={l.label}
                      href={l.url}
                      target="_blank" rel="noreferrer"
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                        padding: '7px 14px', borderRadius: 7,
                        background: 'var(--bg-2)', border: '1px solid var(--border)',
                        color: 'var(--text-2)', fontSize: '0.82rem', textDecoration: 'none',
                      }}
                    >
                      {l.label} <ExternalLink size={11} />
                    </a>
                  ))}
                </div>
              </Section>
            </>
          ) : (
            /* Generic gene view */
            <>
              <Section icon={<Activity size={15} />} title="Summary">
                <p style={{ fontSize: '0.9rem', color: 'var(--text-2)', lineHeight: 1.7 }}>
                  <strong style={{ color: 'var(--text-1)' }}>{symbol}</strong> appears in {geneData?.screens ?? '—'} matched screens
                  with a pathway correlation of <strong style={{ color: 'var(--blue)' }}>{geneData?.correlation ?? '—'}</strong>.
                  It has <strong style={{ color: 'var(--amber)' }}>{geneData?.pubs ?? '—'} indexed publications</strong> and a darkness score of{' '}
                  <strong style={{ color: 'var(--amber)' }}>{geneData?.darkScore ?? '—'}/10</strong>,
                  making it a priority dark-matter candidate for validation.
                </p>
              </Section>

              <StringSection symbol={symbol} interactors={interactors} open={stringOpen} onToggle={() => setStringOpen(o => !o)} />

              <Section icon={<BookOpen size={15} />} title="External resources">
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {[
                    { label: 'NCBI Gene', url: `https://www.ncbi.nlm.nih.gov/gene?term=${symbol}[sym]` },
                    { label: 'UniProt',   url: `https://www.uniprot.org/uniprotkb?query=${symbol}+AND+organism_id:9606` },
                    { label: 'BioGRID',  url: `https://orcs.thebiogrid.org/` },
                  ].map(l => (
                    <a key={l.label} href={l.url} target="_blank" rel="noreferrer" style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      padding: '7px 14px', borderRadius: 7,
                      background: 'var(--bg-2)', border: '1px solid var(--border)',
                      color: 'var(--text-2)', fontSize: '0.82rem', textDecoration: 'none',
                    }}>
                      {l.label} <ExternalLink size={11} />
                    </a>
                  ))}
                </div>
              </Section>
            </>
          )}
        </div>
      </div>
    </>
  );
}

function StringSection({ symbol, interactors, open, onToggle }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <button
        onClick={onToggle}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', borderRadius: open ? '8px 8px 0 0' : 8,
          background: open ? 'rgba(79,156,249,0.08)' : 'var(--bg-2)',
          border: `1px solid ${open ? 'rgba(79,156,249,0.3)' : 'var(--border)'}`,
          color: open ? 'var(--blue)' : 'var(--text-2)',
          fontSize: '0.82rem', transition: 'all 0.15s',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <Network size={14} />
          <span style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', fontSize: '0.75rem' }}>
            STRING protein interactions
          </span>
          {interactors && (
            <span style={{
              padding: '1px 7px', borderRadius: 100,
              background: 'rgba(79,156,249,0.15)', color: 'var(--blue)',
              fontSize: '0.7rem', fontWeight: 700,
            }}>{interactors.length}</span>
          )}
        </span>
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>

      {open && (
        <div style={{
          padding: '12px 14px', borderRadius: '0 0 8px 8px',
          background: 'var(--bg-2)', border: '1px solid rgba(79,156,249,0.3)', borderTop: 'none',
        }}>
          {interactors ? (
            <>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                <thead>
                  <tr style={{ color: 'var(--text-3)', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    <th style={{ textAlign: 'left', paddingBottom: 8, fontWeight: 600 }}>Gene</th>
                    <th style={{ textAlign: 'right', paddingBottom: 8, fontWeight: 600 }}>Combined score</th>
                    <th style={{ textAlign: 'right', paddingBottom: 8, fontWeight: 600 }}>Direction</th>
                  </tr>
                </thead>
                <tbody>
                  {interactors.map((r, i) => {
                    const d = DIRECTION_STYLE[r.direction] ?? DIRECTION_STYLE.unknown;
                    return (
                      <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
                        <td style={{ padding: '7px 0', fontFamily: 'monospace', fontWeight: 600, color: 'var(--text-1)' }}>{r.symbol}</td>
                        <td style={{ padding: '7px 0', textAlign: 'right', color: 'var(--text-2)', fontFamily: 'monospace' }}>{r.combinedScore.toFixed(3)}</td>
                        <td style={{ padding: '7px 0', textAlign: 'right' }}>
                          <span style={{ color: d.color, fontWeight: 600, fontSize: '0.75rem' }}>{d.label}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div style={{ marginTop: 10, fontSize: '0.72rem', color: 'var(--text-3)', fontStyle: 'italic' }}>
                Data shown is illustrative for demo purposes
              </div>
            </>
          ) : (
            <div style={{ fontSize: '0.82rem', color: 'var(--text-3)' }}>
              No STRING data available for <strong style={{ fontFamily: 'monospace' }}>{symbol}</strong> in this demo.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ icon, title, children }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 12 }}>
        {icon && <span style={{ color: 'var(--blue)' }}>{icon}</span>}
        <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.09em', color: 'var(--text-3)' }}>{title}</span>
      </div>
      {children}
    </div>
  );
}
