import { useState } from 'react';
import { BarChart2, Dna, Share2, Download, RotateCcw, FlaskConical } from 'lucide-react';
import MatchedScreens from './MatchedScreens';
import DarkGeneScatter from './DarkGeneScatter';
import GraphExplorer from './GraphExplorer';

const TABS = [
  { id: 'screens', label: 'Matched Screens', icon: <BarChart2 size={14} /> },
  { id: 'dark',    label: 'Dark Gene Candidates', icon: <Dna size={14} />, badge: '5 priority' },
  { id: 'graph',   label: 'Graph Explorer', icon: <Share2 size={14} /> },
];

export default function ResultsPage({ genes, onReset }) {
  const [tab, setTab] = useState('screens');

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
          <strong>{genes?.length ?? 25} genes</strong>
          <span style={{ color: 'var(--text-3)' }}>from query screen</span>
        </div>
        {[
          ['Modality', 'KO'],
          ['Organism', 'Human'],
          ['Cell type', 'Macrophages'],
          ['Algorithm', 'MAGeCK'],
          ['Ref. version', 'v2025-06'],
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
                  background: 'rgba(251,191,36,0.15)', color: 'var(--amber)',
                  fontSize: '0.7rem', fontWeight: 600,
                }}>{t.badge}</span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {tab === 'screens' && <MatchedScreens genes={genes} />}
        {tab === 'dark'    && <DarkGeneScatter />}
        {tab === 'graph'   && <GraphExplorer />}
      </div>
    </div>
  );
}
