import { useEffect, useState } from 'react';

const STEPS = [
  { label: 'Resolving gene identifiers via canonical crosswalk',         pct: 15 },
  { label: 'Querying 287 harmonized screens in reference set',           pct: 32 },
  { label: 'Computing Spearman ρ correlations',                          pct: 50 },
  { label: 'Applying directionality labels (KO ↔ CRISPRa)',             pct: 64 },
  { label: 'Scoring darkness: publication count × GO term specificity',  pct: 78 },
  { label: 'Generating AI hypotheses for top dark-gene candidates',      pct: 90 },
  { label: 'Assembling results package',                                 pct: 100 },
];

export default function LoadingAnalysis({ geneCount, onDone }) {
  const [step, setStep] = useState(0);
  const [pct, setPct] = useState(0);

  useEffect(() => {
    let s = 0;
    const interval = setInterval(() => {
      s++;
      if (s >= STEPS.length) {
        clearInterval(interval);
        setTimeout(onDone, 500);
      } else {
        setStep(s);
        setPct(STEPS[s].pct);
      }
    }, 600);
    setPct(STEPS[0].pct);
    return () => clearInterval(interval);
  }, [onDone]);

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', padding: 40,
      background: 'radial-gradient(ellipse 60% 40% at 50% 40%, rgba(37,99,184,0.15) 0%, transparent 70%)',
    }}>
      <div style={{ width: '100%', maxWidth: 520, textAlign: 'center' }}>
        <div className="spinner" style={{ margin: '0 auto 28px' }} />

        <h2 style={{ fontSize: '1.4rem', fontWeight: 700, marginBottom: 6 }}>Analyzing {geneCount} genes</h2>
        <p style={{ color: 'var(--text-2)', marginBottom: 36, fontSize: '0.9rem' }}>
          Cross-referencing your screen against the harmonized reference set…
        </p>

        {/* Progress bar */}
        <div className="progress-bar" style={{ marginBottom: 20 }}>
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>

        {/* Step list */}
        <div style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {STEPS.map((s, i) => {
            const done = i < step;
            const active = i === step;
            return (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                opacity: i > step ? 0.3 : 1,
                transition: 'opacity 0.3s',
              }}>
                <div style={{
                  width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
                  background: done ? 'var(--green)' : active ? 'var(--blue)' : 'var(--border)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '0.65rem', color: 'white', fontWeight: 700,
                  boxShadow: active ? '0 0 0 4px rgba(79,156,249,0.2)' : 'none',
                  transition: 'all 0.3s',
                }}>
                  {done ? '✓' : i + 1}
                </div>
                <span style={{
                  fontSize: '0.85rem',
                  color: active ? 'var(--text-1)' : done ? 'var(--text-2)' : 'var(--text-3)',
                  fontWeight: active ? 500 : 400,
                }}>{s.label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
