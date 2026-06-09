import { X, ExternalLink, FlaskConical, BookOpen, Lightbulb, Activity } from 'lucide-react';
import { GENE_RATIONALES, DARK_GENES } from '../mockData';

export default function GeneDetailPanel({ symbol, onClose }) {
  if (!symbol) return null;

  const rationale = GENE_RATIONALES[symbol];
  const geneData = DARK_GENES.find(g => g.symbol === symbol);

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
