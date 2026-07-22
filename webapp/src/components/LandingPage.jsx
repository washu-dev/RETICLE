import { useState } from 'react';
import { Dna, Zap, Search, BarChart3, ArrowRight, FlaskConical } from 'lucide-react';

const STATS = [
  { value: '287', label: 'Harmonized screens' },
  { value: '12,500', label: 'Unique genes' },
  { value: '1.2M', label: 'Gene–screen pairs' },
  { value: '3', label: 'CRISPR modalities' },
];

const FEATURES = [
  {
    icon: <Search size={20} />,
    title: 'Cross-screen comparison',
    body: 'Upload any ranked gene list. RETICLE computes Spearman correlation against 287 harmonized screens from BioGRID ORCS, DepMap, and STRING.',
  },
  {
    icon: <Zap size={20} />,
    title: 'Directionality-aware matching',
    body: 'Knockout and CRISPRa screens are sign-flipped and labelled. An "agree" match means convergent biology; an "inverted" match flags biologically informative opposition.',
  },
  {
    icon: <Dna size={20} />,
    title: 'Dark matter prioritization',
    body: 'Every candidate is scored for "darkness" — low publication count, sparse GO annotation, few prior screens. High-darkness genes correlated with your pathway are the headline output.',
  },
  {
    icon: <BarChart3 size={20} />,
    title: 'AI hypothesis engine',
    body: 'A RAG-grounded LLM synthesizes mechanistic hypotheses for top dark gene candidates, citing the source screens and literature that support them.',
  },
];

export default function LandingPage({ onStart, onExplore }) {
  const [hovered, setHovered] = useState(null);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Nav */}
      <nav style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 40px', borderBottom: '1px solid var(--border)',
        background: 'rgba(11,17,32,0.85)', backdropFilter: 'blur(12px)',
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: 'linear-gradient(135deg, #2563b8, #4f9cf9)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <FlaskConical size={16} color="white" />
          </div>
          <span style={{ fontWeight: 700, fontSize: '1.1rem', letterSpacing: '-0.02em' }}>RETICLE</span>
          <span style={{ color: 'var(--text-3)', fontSize: '0.8rem', marginLeft: 2 }}>beta</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={onExplore}
            style={{
              padding: '8px 20px', borderRadius: 8,
              background: 'var(--bg-3)', color: 'var(--text-2)',
              fontSize: '0.875rem', fontWeight: 500,
            }}
          >Gene Explorer</button>
          <button style={{
            padding: '8px 20px', borderRadius: 8,
            background: 'var(--bg-3)', color: 'var(--text-2)',
            fontSize: '0.875rem', fontWeight: 500,
          }}>Documentation</button>
          <button
            onClick={onStart}
            style={{
              padding: '8px 20px', borderRadius: 8,
              background: 'var(--blue)', color: 'white',
              fontSize: '0.875rem', fontWeight: 600,
            }}
          >Launch app</button>
        </div>
      </nav>

      {/* Hero */}
      <section style={{
        flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        padding: '80px 40px 60px', textAlign: 'center',
        background: 'radial-gradient(ellipse 70% 50% at 50% 0%, rgba(37,99,184,0.18) 0%, transparent 70%)',
      }}>
        {/* Chip */}
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '6px 14px', borderRadius: 100,
          border: '1px solid rgba(79,156,249,0.3)',
          background: 'rgba(79,156,249,0.08)',
          fontSize: '0.8rem', color: 'var(--blue)', fontWeight: 500, marginBottom: 28,
        }}>
          <span className="pulse-dot" />
          WashU DI² · IFNγ Macrophage Program
        </div>

        <h1 style={{
          fontSize: 'clamp(2.2rem, 5vw, 3.8rem)', fontWeight: 800,
          letterSpacing: '-0.04em', lineHeight: 1.1, marginBottom: 22, maxWidth: 800,
          background: 'linear-gradient(135deg, #f0f4ff 30%, #a8b8d8)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
        }}>
          Rationale Engine To<br />Inform CRISPR List Entities
        </h1>

        <p style={{ fontSize: '1.15rem', color: 'var(--text-2)', maxWidth: 600, lineHeight: 1.6, marginBottom: 40 }}>
          Submit a ranked gene list from your CRISPR screen. RETICLE cross-references
          287 harmonized screens, surfaces novel dark-matter candidates, and generates
          AI-grounded mechanistic hypotheses — prioritizing what no one has studied yet.
        </p>

        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'center' }}>
          <button
            onClick={onStart}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '14px 28px', borderRadius: 10,
              background: 'linear-gradient(135deg, #2563b8, #4f9cf9)',
              color: 'white', fontSize: '1rem', fontWeight: 600,
              boxShadow: '0 4px 20px rgba(79,156,249,0.35)',
              transition: 'transform 0.15s, box-shadow 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 6px 28px rgba(79,156,249,0.45)'; }}
            onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = '0 4px 20px rgba(79,156,249,0.35)'; }}
          >
            Upload gene list <ArrowRight size={17} />
          </button>
          <button
            style={{
              padding: '14px 28px', borderRadius: 10,
              background: 'var(--bg-2)', border: '1px solid var(--border)',
              color: 'var(--text-1)', fontSize: '1rem', fontWeight: 500,
            }}
          >
            View documentation
          </button>
        </div>

        {/* Stats row */}
        <div style={{
          display: 'flex', gap: 0, marginTop: 64,
          border: '1px solid var(--border)', borderRadius: 14,
          background: 'var(--bg-2)', overflow: 'hidden',
        }}>
          {STATS.map((s, i) => (
            <div key={i} style={{
              padding: '20px 36px', textAlign: 'center',
              borderRight: i < STATS.length - 1 ? '1px solid var(--border)' : 'none',
            }}>
              <div style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--blue)' }}>{s.value}</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-3)', marginTop: 2 }}>{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Feature grid */}
      <section style={{ padding: '60px 40px 80px', maxWidth: 1100, margin: '0 auto', width: '100%' }}>
        <p style={{ textAlign: 'center', fontSize: '0.8rem', letterSpacing: '0.1em', color: 'var(--text-3)', fontWeight: 600, textTransform: 'uppercase', marginBottom: 40 }}>
          How it works
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 20 }}>
          {FEATURES.map((f, i) => (
            <div
              key={i}
              className="card"
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              style={{
                transition: 'border-color 0.2s, box-shadow 0.2s',
                borderColor: hovered === i ? 'var(--blue-dim)' : 'var(--border)',
                boxShadow: hovered === i ? '0 0 0 1px var(--blue-dim)' : 'none',
              }}
            >
              <div style={{
                width: 38, height: 38, borderRadius: 9,
                background: 'rgba(79,156,249,0.12)', border: '1px solid rgba(79,156,249,0.2)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: 'var(--blue)', marginBottom: 14,
              }}>{f.icon}</div>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{f.title}</div>
              <div style={{ fontSize: '0.875rem', color: 'var(--text-2)', lineHeight: 1.6 }}>{f.body}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
