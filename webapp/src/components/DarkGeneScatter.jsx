import { useState } from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceArea, Label,
} from 'recharts';
import { DARK_GENES } from '../mockData';
import GeneDetailPanel from './GeneDetailPanel';

const CLUSTERS = [
  { key: 'core-autophagy',      label: 'Core autophagy',      color: '#4f9cf9', x1: 0.61, x2: 0.90, y1: 1.3, y2: 4.9 },
  { key: 'selective-autophagy', label: 'Selective autophagy', color: '#34d399', x1: 0.49, x2: 0.86, y1: 3.6, y2: 7.7 },
  { key: 'dark-matter',         label: 'Dark matter',         color: '#fbbf24', x1: 0.53, x2: 0.76, y1: 7.2, y2: 10  },
];

function CustomDot(props) {
  const { cx, cy, payload, onClick, selected } = props;
  const isDark   = !payload.isBright && payload.darkScore >= 6;
  const isTop    = payload.darkScore >= 8 && payload.correlation >= 0.55;
  const r        = isTop ? 9 : isDark ? 7 : 6;
  const fill     = payload.isBright ? '#4f9cf9' : isTop ? '#fbbf24' : '#f59e0b88';
  const stroke   = selected ? 'white' : payload.isBright ? '#2563b8' : isTop ? '#f59e0b' : '#78450a';
  const sw       = selected ? 2.5 : 1.5;

  return (
    <circle
      cx={cx} cy={cy} r={r}
      fill={fill} stroke={stroke} strokeWidth={sw}
      style={{ cursor: 'pointer', transition: 'r 0.15s' }}
      onClick={() => onClick(payload)}
    />
  );
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{
      background: 'var(--bg-1)', border: '1px solid var(--border)',
      borderRadius: 9, padding: '12px 16px', fontSize: '0.82rem',
      boxShadow: 'var(--shadow)', minWidth: 180,
    }}>
      <div style={{ fontWeight: 700, fontFamily: 'monospace', fontSize: '0.95rem', marginBottom: 6, color: d.isBright ? 'var(--blue)' : 'var(--amber)' }}>
        {d.symbol}
      </div>
      <div style={{ color: 'var(--text-3)', display: 'flex', flexDirection: 'column', gap: 3 }}>
        <span>Pathway correlation: <strong style={{ color: 'var(--text-1)' }}>{d.correlation}</strong></span>
        <span>Darkness score: <strong style={{ color: 'var(--text-1)' }}>{d.darkScore}/10</strong></span>
        <span>Publications: <strong style={{ color: 'var(--text-1)' }}>{d.pubs}</strong></span>
        <span>Matched screens: <strong style={{ color: 'var(--text-1)' }}>{d.screens}</strong></span>
      </div>
      {!d.isBright && d.darkScore >= 6 && (
        <div style={{ marginTop: 8, fontSize: '0.75rem', color: 'var(--amber)', borderTop: '1px solid var(--border)', paddingTop: 6 }}>
          ↑ Dark-matter candidate · click for AI rationale
        </div>
      )}
    </div>
  );
}

export default function DarkGeneScatter({ pathwayAnalysis = false, onSelectGene }) {
  const [selected, setSelected] = useState(null);

  const handleClick = (payload) => {
    const next = payload.symbol === selected ? null : payload.symbol;
    setSelected(next);
    if (next && onSelectGene) onSelectGene(next);
  };

  const darkCount = DARK_GENES.filter(g => !g.isBright && g.darkScore >= 6).length;
  const topCount  = DARK_GENES.filter(g => !g.isBright && g.darkScore >= 8 && g.correlation >= 0.55).length;

  return (
    <div>
      {/* Callout box */}
      <div style={{
        display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap',
      }}>
        <div style={{
          flex: '1 1 300px', padding: '16px 20px', borderRadius: 10,
          background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.25)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <span style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--amber)' }}>{darkCount}</span>
            <span className="badge badge-dark">Dark candidates</span>
          </div>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-2)', lineHeight: 1.5 }}>
            Genes correlated with your pathway but with fewer than 100 publications and sparse GO annotation.
            These are systematically overlooked in standard analyses.
          </p>
        </div>
        <div style={{
          flex: '1 1 220px', padding: '16px 20px', borderRadius: 10,
          background: 'var(--bg-2)', border: '1px solid var(--border)',
        }}>
          <div style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--blue)', marginBottom: 4 }}>{topCount}</div>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 2 }}>Priority targets</div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-3)' }}>Darkness ≥ 8 · correlation ≥ 0.55</div>
        </div>
        <div style={{
          flex: '1 1 220px', padding: '16px 20px', borderRadius: 10,
          background: 'var(--bg-2)', border: '1px solid var(--border)',
        }}>
          <div style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--green)', marginBottom: 4 }}>
            {DARK_GENES.filter(g => g.isBright).length}
          </div>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 2 }}>Known pathway genes</div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-3)' }}>High correlation, well-characterized</div>
        </div>
      </div>

      {/* Chart */}
      <div className="card" style={{ padding: '20px 20px 12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>Dark gene landscape</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-3)' }}>
              Upper-right quadrant = high pathway correlation AND high darkness. Click any gene for AI rationale.
            </div>
          </div>
          {/* Legend */}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: '0.78rem', color: 'var(--text-2)' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="var(--amber)" /></svg>
              Dark candidate
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="var(--blue)" /></svg>
              Known gene
            </span>
            {pathwayAnalysis && CLUSTERS.map(c => (
              <span key={c.key} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <svg width="12" height="12"><rect x="1" y="1" width="10" height="10" rx="2" fill={c.color} fillOpacity={0.25} stroke={c.color} strokeWidth={1} /></svg>
                {c.label}
              </span>
            ))}
          </div>
        </div>

        <ResponsiveContainer width="100%" height={400}>
          <ScatterChart margin={{ top: 10, right: 30, bottom: 40, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(42,58,92,0.6)" />
            <XAxis
              type="number" dataKey="correlation" domain={[0, 1]}
              stroke="var(--text-3)" tick={{ fill: 'var(--text-3)', fontSize: 11 }}
              tickFormatter={v => v.toFixed(1)}
            >
              <Label value="Pathway correlation (Spearman ρ)" offset={-10} position="insideBottom" fill="var(--text-3)" fontSize={11} />
            </XAxis>
            <YAxis
              type="number" dataKey="darkScore" domain={[0, 10]}
              stroke="var(--text-3)" tick={{ fill: 'var(--text-3)', fontSize: 11 }}
            >
              <Label value="Darkness score" angle={-90} position="insideLeft" fill="var(--text-3)" fontSize={11} offset={10} />
            </YAxis>
            <Tooltip content={<CustomTooltip />} cursor={false} />

            {/* Quadrant lines */}
            <ReferenceLine x={0.6} stroke="rgba(251,191,36,0.25)" strokeDasharray="6 3" />
            <ReferenceLine y={6}   stroke="rgba(251,191,36,0.25)" strokeDasharray="6 3" />

            {/* Pathway co-significance cluster regions */}
            {pathwayAnalysis && CLUSTERS.map(c => (
              <ReferenceArea
                key={c.key}
                x1={c.x1} x2={c.x2} y1={c.y1} y2={c.y2}
                fill={c.color} fillOpacity={0.07}
                stroke={c.color} strokeOpacity={0.3} strokeWidth={1}
                label={{ value: c.label, position: 'insideTopRight', fontSize: 9, fill: c.color, fontWeight: 600 }}
              />
            ))}

            <Scatter
              data={DARK_GENES}
              shape={(props) => (
                <CustomDot
                  {...props}
                  selected={selected === props.payload?.symbol}
                  onClick={handleClick}
                />
              )}
            />
          </ScatterChart>
        </ResponsiveContainer>

        {/* Gene labels under chart */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
          {DARK_GENES.filter(g => !g.isBright && g.darkScore >= 6).map(g => (
            <button
              key={g.symbol}
              onClick={() => {
                const next = g.symbol === selected ? null : g.symbol;
                setSelected(next);
                if (next && onSelectGene) onSelectGene(next);
              }}
              style={{
                padding: '4px 10px', borderRadius: 6, fontSize: '0.78rem', fontFamily: 'monospace', fontWeight: 600,
                background: selected === g.symbol ? 'rgba(251,191,36,0.2)' : 'var(--bg-1)',
                border: `1px solid ${selected === g.symbol ? 'var(--amber)' : 'var(--border)'}`,
                color: selected === g.symbol ? 'var(--amber)' : 'var(--text-2)',
                transition: 'all 0.15s',
              }}
            >
              {g.symbol}
            </button>
          ))}
        </div>
      </div>

      {/* Detail panel */}
      <GeneDetailPanel symbol={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
