import { useEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import { runQuery } from '../services/reticleApi';

// High-level, honest progress steps. These narrate the query at a level that is
// actually true; they intentionally avoid claiming specific computations (e.g.
// a calibrated Spearman ρ or AI hypotheses) that the backend does not yet run.
const STEPS = [
  { label: 'Resolving gene identifiers',                pct: 18 },
  { label: 'Comparing your screen against the corpus',  pct: 42 },
  { label: 'Ranking screens by shared hits',            pct: 64 },
  { label: 'Scoring dark-matter candidates',            pct: 84 },
  { label: 'Assembling your results',                   pct: 100 },
];

export default function LoadingAnalysis({ geneCount, genes, options, onDone }) {
  const [step, setStep] = useState(0);
  const [pct, setPct] = useState(0);

  // Stable refs so the effect never re-fires due to parent re-renders.
  const genesRef   = useRef(genes);
  const optionsRef = useRef(options);

  useEffect(() => {
    let mounted = true;
    let apiResults = undefined; // undefined = still in-flight
    let animDone   = false;

    function finish() {
      // Only call onDone once both the API and animation have settled.
      if (!mounted || !animDone || apiResults === undefined) return;
      onDone(apiResults ?? null);
    }

    // Fire the API query immediately alongside the animation.
    runQuery(genesRef.current ?? [], optionsRef.current ?? {})
      .then(results => {
        if (!mounted) return;
        apiResults = results;
        finish();
      })
      .catch(() => {
        if (!mounted) return;
        apiResults = null; // signal error; ResultsPage falls back to mock data
        finish();
      });

    // Run the step animation independently.
    let s = 0;
    let doneTimer;
    const interval = setInterval(() => {
      s++;
      if (s >= STEPS.length) {
        clearInterval(interval);
        doneTimer = setTimeout(() => {
          if (!mounted) return;
          animDone = true;
          finish();
        }, 500);
      } else if (mounted) {
        setStep(s);
        setPct(STEPS[s].pct);
      }
    }, 600);

    setPct(STEPS[0].pct);

    return () => {
      mounted = false;
      clearInterval(interval);
      clearTimeout(doneTimer);
    };
  }, [onDone]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', padding: 40,
      background: 'radial-gradient(ellipse 60% 40% at 50% 40%, rgba(186,12,47,0.05) 0%, transparent 70%)',
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
            const done   = i < step;
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
                  boxShadow: active ? '0 0 0 4px rgba(0,125,138,0.2)' : 'none',
                  transition: 'all 0.3s',
                }}>
                  {done ? <Check size={11} /> : i + 1}
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
