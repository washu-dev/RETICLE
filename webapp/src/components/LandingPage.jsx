import { useState } from 'react';
import { Dna, Zap, Search, BarChart3, ArrowRight } from 'lucide-react';
import WashuLogo from './washu/WashuLogo';

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
    body: 'Upload a ranked gene list or a full screen. RETICLE ranks the published screens probing biology like yours, with the shared context named.',
  },
  {
    icon: <Zap size={20} />,
    title: 'Directionality-aware matching',
    body: 'Knockout and CRISPRa screens are sign-flipped and labelled. A same-direction match means convergent biology; an opposite match flags informative opposition.',
  },
  {
    icon: <Dna size={20} />,
    title: 'Dark-matter prioritization',
    body: 'Every candidate is scored for darkness — few publications, sparse annotation, few prior screens. High-darkness genes that track your biology are the headline output.',
  },
  {
    icon: <BarChart3 size={20} />,
    title: 'Gene as a list entity',
    body: 'Open any gene to see everything the corpus measured about it across screens, extended to the literature with a cited, hypothesis-generating AI read.',
  },
];

export default function LandingPage({ onStart, onExplore }) {
  const [hovered, setHovered] = useState(null);

  const navBtn = {
    padding: '8px 18px', borderRadius: 6, fontSize: '0.875rem', fontWeight: 600,
    border: '1px solid var(--border-2)', background: 'var(--white)', color: 'var(--fg-muted)',
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Nav */}
      <nav style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '11px 40px', borderTop: '3px solid var(--washu-red)',
        borderBottom: '1px solid var(--border)', background: 'var(--white)',
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <WashuLogo height={30} />
          <span style={{ fontWeight: 700, letterSpacing: '0.02em', paddingLeft: 16, borderLeft: '1px solid var(--border-2)' }}>
            RETI<span style={{ color: 'var(--washu-red)' }}>C</span>LE
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={onExplore} style={navBtn}>Gene Explorer</button>
          <button style={navBtn}>Documentation</button>
          <button
            onClick={onStart}
            style={{ ...navBtn, background: 'var(--washu-red)', color: '#fff', border: '2px solid var(--washu-red)' }}
          >Launch app</button>
        </div>
      </nav>

      {/* Hero */}
      <section style={{
        display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
        padding: '80px 40px 56px', maxWidth: 1100, margin: '0 auto', width: '100%',
      }}>
        <div className="eyebrow" style={{ marginBottom: 20 }}>WashU DI² · CRISPR screen intelligence</div>
        <h1 style={{
          fontSize: 'clamp(2.2rem, 5vw, 3.6rem)', fontWeight: 700,
          letterSpacing: '-0.02em', lineHeight: 1.08, marginBottom: 22, maxWidth: 880, color: 'var(--fg)',
        }}>
          How does your screen compare to <span className="emph">every</span> screen in the corpus?
        </h1>
        <p style={{ fontSize: '1.15rem', color: 'var(--fg-muted)', maxWidth: 620, lineHeight: 1.6, marginBottom: 36 }}>
          Bring a few favorite genes or a full screen. RETICLE finds the published screens secretly
          asking your question, surfaces the dark-matter genes worth a look, and reads back what the
          corpus sees — in plain language, with the numbers a step away.
        </p>

        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <button
            onClick={onStart}
            style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '13px 26px', borderRadius: 6,
              background: 'var(--washu-red)', color: '#fff', fontSize: '1rem', fontWeight: 700,
              border: '2px solid var(--washu-red)',
            }}
          >
            Compare to the corpus <ArrowRight size={17} />
          </button>
          <button
            onClick={onExplore}
            style={{
              padding: '13px 26px', borderRadius: 6, background: 'var(--white)',
              border: '2px solid var(--washu-red)', color: 'var(--washu-red)', fontSize: '1rem', fontWeight: 700,
            }}
          >
            Look up a gene
          </button>
        </div>

        {/* Stats row */}
        <div style={{
          display: 'flex', flexWrap: 'wrap', marginTop: 60,
          border: '1px solid var(--border)', borderRadius: 12,
          background: 'var(--white)', overflow: 'hidden',
        }}>
          {STATS.map((s, i) => (
            <div key={i} style={{
              padding: '20px 40px',
              borderRight: i < STATS.length - 1 ? '1px solid var(--border)' : 'none',
            }}>
              <div style={{ fontSize: '1.7rem', fontWeight: 700, color: 'var(--washu-red)' }} className="tnum">{s.value}</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--faint)', marginTop: 2 }}>{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Feature grid */}
      <section style={{ padding: '20px 40px 80px', maxWidth: 1100, margin: '0 auto', width: '100%' }}>
        <p className="eyebrow" style={{ marginBottom: 24 }}>How it works</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 18 }}>
          {FEATURES.map((f, i) => (
            <div
              key={i}
              className="card"
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              style={{
                transition: 'border-color 0.2s, box-shadow 0.2s',
                borderColor: hovered === i ? 'var(--washu-red)' : 'var(--border)',
              }}
            >
              <div style={{
                width: 38, height: 38, borderRadius: 8,
                background: 'var(--teal-wash)', border: '1px solid var(--teal-line)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: 'var(--teal)', marginBottom: 14,
              }}>{f.icon}</div>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>{f.title}</div>
              <div style={{ fontSize: '0.875rem', color: 'var(--fg-muted)', lineHeight: 1.6 }}>{f.body}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
