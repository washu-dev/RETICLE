import { useState } from 'react';
import { BarChart2, Dna, Share2, Download, RotateCcw, FlaskConical, List, ArrowRight } from 'lucide-react';
import MatchedScreens from './MatchedScreens';
import DarkGeneScatter from './DarkGeneScatter';
import GraphExplorer from './GraphExplorer';
import { DARK_GENES, GRAPH_ELEMENTS } from '../mockData';

const GRAPH_GENE_LABELS = new Set(
  GRAPH_ELEMENTS.nodes
    .filter(n => n.data.type === 'gene' || n.data.type === 'dark')
    .map(n => n.data.label)
);

function QueryGenesTab({ genes, onExploreGene }) {
  const [filter, setFilter] = useState('all');

  const enriched = genes.map(g => {
    const dark = DARK_GENES.find(d => d.symbol === g.symbol);
    return { ...g, dark };
  });

  const displayed = filter === 'dark'
    ? enriched.filter(g => g.dark && !g.dark.isBright && g.dark.darkScore >= 6)
    : filter === 'bright'
    ? enriched.filter(g => g.dark?.isBright)
    : enriched;

  const darkCount   = enriched.filter(g => g.dark && !g.dark.isBright && g.dark.darkScore >= 6).length;
  const brightCount = enriched.filter(g => g.dark?.isBright).length;

  return (
    <div>
      {/* Summary chips */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        <div style={{
          padding: '12px 18px', borderRadius: 10, flex: '1 1 180px',
          background: 'var(--bg-2)', border: '1px solid var(--border)',
        }}>
          <div style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--text-1)' }}>{genes.length}</div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-3)', marginTop: 2 }}>genes from your screen</div>
        </div>
        <div style={{
          padding: '12px 18px', borderRadius: 10, flex: '1 1 180px',
          background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.25)',
        }}>
          <div style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--amber)' }}>{darkCount}</div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-3)', marginTop: 2 }}>dark-matter candidates</div>
        </div>
        <div style={{
          padding: '12px 18px', borderRadius: 10, flex: '1 1 180px',
          background: 'rgba(79,156,249,0.06)', border: '1px solid rgba(79,156,249,0.2)',
        }}>
          <div style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--blue)' }}>{brightCount}</div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-3)', marginTop: 2 }}>known pathway genes</div>
        </div>
      </div>

      {/* Filter row */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
        {[['all', 'All genes'], ['dark', 'Dark candidates'], ['bright', 'Known genes']].map(([key, label]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            style={{
              padding: '5px 14px', borderRadius: 6, fontSize: '0.82rem',
              background: filter === key ? 'rgba(79,156,249,0.12)' : 'var(--bg-2)',
              border: `1px solid ${filter === key ? 'var(--blue)' : 'var(--border)'}`,
              color: filter === key ? 'var(--blue)' : 'var(--text-2)',
              fontWeight: filter === key ? 600 : 400,
            }}
          >{label}</button>
        ))}
      </div>

      {/* Gene table */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
          <thead>
            <tr style={{
              background: 'var(--bg-2)',
              fontSize: '0.72rem', color: 'var(--text-3)',
              textTransform: 'uppercase', letterSpacing: '0.06em',
            }}>
              <th style={{ padding: '10px 16px', textAlign: 'left', fontWeight: 600 }}>Gene</th>
              <th style={{ padding: '10px 16px', textAlign: 'right', fontWeight: 600 }}>Score</th>
              <th style={{ padding: '10px 16px', textAlign: 'right', fontWeight: 600 }}>Darkness</th>
              <th style={{ padding: '10px 16px', textAlign: 'right', fontWeight: 600 }}>Corr.</th>
              <th style={{ padding: '10px 16px', textAlign: 'right', fontWeight: 600 }}>Screens</th>
              <th style={{ padding: '10px 16px', textAlign: 'center', fontWeight: 600 }}>Explore</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((g, i) => {
              const isDark     = g.dark && !g.dark.isBright && g.dark.darkScore >= 6;
              const isBright   = g.dark?.isBright;
              const inGraph    = GRAPH_GENE_LABELS.has(g.symbol);
              const scoreColor = g.score < 0 ? 'var(--blue)' : 'var(--orange)';

              return (
                <tr
                  key={g.symbol}
                  style={{
                    borderTop: i === 0 ? 'none' : '1px solid var(--border)',
                    background: isDark ? 'rgba(251,191,36,0.03)' : 'transparent',
                  }}
                >
                  <td style={{ padding: '10px 16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{
                        fontFamily: 'monospace', fontWeight: 700,
                        color: isDark ? 'var(--amber)' : isBright ? 'var(--blue)' : 'var(--text-1)',
                        fontSize: '0.88rem',
                      }}>{g.symbol}</span>
                      {isDark && (
                        <span style={{
                          fontSize: '0.65rem', padding: '1px 6px', borderRadius: 100,
                          background: 'rgba(251,191,36,0.15)', color: 'var(--amber)', fontWeight: 700,
                        }}>dark</span>
                      )}
                      {isBright && (
                        <span style={{
                          fontSize: '0.65rem', padding: '1px 6px', borderRadius: 100,
                          background: 'rgba(79,156,249,0.12)', color: 'var(--blue)', fontWeight: 700,
                        }}>known</span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '10px 16px', textAlign: 'right', fontFamily: 'monospace', color: scoreColor, fontWeight: 600 }}>
                    {g.score.toFixed(2)}
                  </td>
                  <td style={{ padding: '10px 16px', textAlign: 'right', fontFamily: 'monospace', color: g.dark ? 'var(--amber)' : 'var(--text-3)' }}>
                    {g.dark ? `${g.dark.darkScore}/10` : '—'}
                  </td>
                  <td style={{ padding: '10px 16px', textAlign: 'right', fontFamily: 'monospace', color: 'var(--text-2)' }}>
                    {g.dark ? g.dark.correlation.toFixed(2) : '—'}
                  </td>
                  <td style={{ padding: '10px 16px', textAlign: 'right', color: 'var(--text-2)' }}>
                    {g.dark ? g.dark.screens : '—'}
                  </td>
                  <td style={{ padding: '10px 16px', textAlign: 'center' }}>
                    {inGraph ? (
                      <button
                        onClick={() => onExploreGene(g.symbol)}
                        style={{
                          display: 'inline-flex', alignItems: 'center', gap: 4,
                          padding: '4px 10px', borderRadius: 6, fontSize: '0.75rem',
                          background: 'rgba(79,156,249,0.08)', border: '1px solid rgba(79,156,249,0.3)',
                          color: 'var(--blue)', fontWeight: 600, cursor: 'pointer',
                          transition: 'all 0.15s',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(79,156,249,0.16)'; }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'rgba(79,156,249,0.08)'; }}
                      >
                        Graph <ArrowRight size={11} />
                      </button>
                    ) : (
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-3)' }}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function ResultsPage({ genes, options, onReset }) {
  const [tab, setTab]           = useState('screens');
  const [focusGene, setFocusGene] = useState(null);

  function handleExploreGene(symbol) {
    setFocusGene(symbol);
    setTab('graph');
  }

  const geneCount = genes?.length ?? 25;

  const TABS = [
    { id: 'query',   label: 'Query Genes',         icon: <List size={14} />,     badge: `${geneCount}` },
    { id: 'screens', label: 'Matched Screens',      icon: <BarChart2 size={14} /> },
    { id: 'dark',    label: 'Dark Gene Candidates', icon: <Dna size={14} />,      badge: '5 priority' },
    { id: 'graph',   label: 'Graph Explorer',       icon: <Share2 size={14} /> },
  ];

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Nav */}
      <nav style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 40px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-0)', position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 7,
            background: 'linear-gradient(135deg, #2563b8, #4f9cf9)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <FlaskConical size={14} color="white" />
          </div>
          <span style={{ fontWeight: 700, fontSize: '1.05rem', letterSpacing: '-0.02em' }}>RETICLE</span>
          <span style={{ color: 'var(--text-3)', fontSize: '0.8rem' }}>/ Results</span>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={onReset}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 8,
              border: '1px solid var(--border)', color: 'var(--text-2)', fontSize: '0.85rem',
              background: 'var(--bg-2)',
            }}
          >
            <RotateCcw size={13} /> New query
          </button>
          <button style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '7px 14px', borderRadius: 8,
            border: '1px solid var(--border)', color: 'var(--text-2)', fontSize: '0.85rem',
            background: 'var(--bg-2)',
          }}>
            <Download size={13} /> Export CSV
          </button>
        </div>
      </nav>

      {/* Query summary bar */}
      <div style={{
        padding: '12px 40px', background: 'var(--bg-2)', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap', fontSize: '0.85rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="pulse-dot" />
          <strong>{geneCount} genes</strong>
          <span style={{ color: 'var(--text-3)' }}>from query screen</span>
        </div>
        {[
          ['Modality',    options?.modalities?.join(', ') ?? 'KO'],
          ['Organism',    options?.organism  ?? 'Human'],
          ['Cell type',   'Macrophages'],
          ['Algorithm',   options?.algorithm ?? 'MAGeCK'],
          ['Ref. version','v2025-06'],
        ].map(([k, v]) => (
          <div key={k} style={{ display: 'flex', gap: 5 }}>
            <span style={{ color: 'var(--text-3)' }}>{k}:</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>

      <div style={{ flex: 1, padding: '28px 40px', maxWidth: 1200, width: '100%', margin: '0 auto' }}>
        {/* Tabs */}
        <div className="tabs" style={{ marginBottom: 28 }}>
          {TABS.map(t => (
            <button
              key={t.id}
              className={`tab-btn${tab === t.id ? ' active' : ''}`}
              onClick={() => setTab(t.id)}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
            >
              {t.icon}
              {t.label}
              {t.badge && tab !== t.id && (
                <span style={{
                  padding: '1px 7px', borderRadius: 100,
                  background: t.id === 'dark' ? 'rgba(251,191,36,0.15)' : 'rgba(79,156,249,0.12)',
                  color: t.id === 'dark' ? 'var(--amber)' : 'var(--blue)',
                  fontSize: '0.7rem', fontWeight: 600,
                }}>{t.badge}</span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {tab === 'query'   && (
          <QueryGenesTab
            genes={genes ?? []}
            onExploreGene={handleExploreGene}
          />
        )}
        {tab === 'screens' && <MatchedScreens genes={genes} />}
        {tab === 'dark'    && (
          <DarkGeneScatter
            pathwayAnalysis={options?.pathwayAnalysis ?? false}
            onSelectGene={handleExploreGene}
          />
        )}
        {tab === 'graph'   && (
          <GraphExplorer
            focusGene={focusGene}
            onGeneSelect={setFocusGene}
          />
        )}
      </div>
    </div>
  );
}
