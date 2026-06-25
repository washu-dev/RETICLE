import { ExternalLink, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { MATCHED_SCREENS as MOCK_SCREENS } from '../mockData';

function DirectionalityBadge({ d }) {
  if (d === 'agree')    return <span className="badge badge-agree"><TrendingUp size={11} /> Agree</span>;
  if (d === 'inverted') return <span className="badge badge-inverted"><TrendingDown size={11} /> Inverted</span>;
  return <span className="badge badge-unknown"><Minus size={11} /> Unknown</span>;
}

function ModalityBadge({ m }) {
  if (m === 'CRISPRa') return <span className="badge badge-crispra">CRISPRa</span>;
  return <span className="badge badge-ko">KO</span>;
}

function RhoBar({ rho }) {
  const pct   = Math.abs(rho) * 100;
  const color = rho > 0 ? 'var(--blue)' : 'var(--orange)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 140 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3, transition: 'width 0.6s' }} />
      </div>
      <span style={{ fontSize: '0.875rem', fontWeight: 600, color, width: 44, textAlign: 'right', fontFamily: 'monospace' }}>
        {rho > 0 ? '+' : ''}{rho.toFixed(2)}
      </span>
    </div>
  );
}

export default function MatchedScreens({ genes, screens }) {
  const displayScreens = screens ?? MOCK_SCREENS;
  const sigCount       = displayScreens.filter(s => s.fdr < 0.05).length;

  return (
    <div>
      {/* Summary row */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
        {[
          { label: 'Screens compared',    value: '287',                                                        note: 'reference set' },
          { label: 'Significant matches', value: sigCount,                                                     note: 'FDR < 5%' },
          { label: 'Agree directionality',value: displayScreens.filter(s => s.directionality === 'agree').length, note: 'of top 8' },
          { label: 'Query genes',         value: genes?.length ?? 25,                                         note: 'after ID resolution' },
        ].map(s => (
          <div key={s.label} className="card" style={{ flex: '1 1 140px', padding: '16px 20px' }}>
            <div style={{ fontSize: '1.7rem', fontWeight: 800, color: 'var(--blue)' }}>{s.value}</div>
            <div style={{ fontSize: '0.8rem', fontWeight: 600, marginTop: 2 }}>{s.label}</div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-3)', marginTop: 1 }}>{s.note}</div>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 600 }}>Top matched screens</span>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-3)' }}>ranked by Spearman ρ · FDR-corrected</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Screen</th>
                <th>Citation</th>
                <th>Modality</th>
                <th>Organism / Cell type</th>
                <th>Spearman ρ</th>
                <th>FDR</th>
                <th>Directionality</th>
                <th>Shared genes</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {displayScreens.map((s, i) => (
                <tr key={s.id}>
                  <td style={{ color: 'var(--text-3)', fontWeight: 600, fontFamily: 'monospace' }}>#{i + 1}</td>
                  <td>
                    <div style={{ fontWeight: 500 }}>{s.name.length > 48 ? s.name.slice(0, 48) + '…' : s.name}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-3)', fontFamily: 'monospace', marginTop: 2 }}>{s.biogridId}</div>
                  </td>
                  <td style={{ fontSize: '0.8rem', color: 'var(--text-2)', whiteSpace: 'nowrap' }}>{s.citation}</td>
                  <td><ModalityBadge m={s.modality} /></td>
                  <td>
                    <div style={{ fontSize: '0.85rem' }}>{s.organism}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-3)' }}>{s.cellType}</div>
                  </td>
                  <td><RhoBar rho={s.rho} /></td>
                  <td style={{ fontFamily: 'monospace', fontSize: '0.82rem', color: s.fdr < 0.05 ? 'var(--green)' : 'var(--text-3)' }}>
                    {s.fdr.toFixed(4)}
                  </td>
                  <td><DirectionalityBadge d={s.directionality} /></td>
                  <td style={{ fontFamily: 'monospace', fontSize: '0.82rem', color: 'var(--text-2)' }}>
                    {s.sharedGenes} / {Math.round(s.totalGenes / 100) * 100}
                  </td>
                  <td>
                    <a
                      href={`https://pubmed.ncbi.nlm.nih.gov/${s.pmid}`}
                      target="_blank" rel="noreferrer"
                      style={{ color: 'var(--text-3)' }}
                      title="Open in PubMed"
                    >
                      <ExternalLink size={14} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Legend */}
      <div style={{ marginTop: 16, display: 'flex', gap: 20, fontSize: '0.78rem', color: 'var(--text-3)', flexWrap: 'wrap' }}>
        <span><span className="badge badge-agree" style={{ fontSize: '0.7rem' }}>Agree</span> — same directional effect in matched screen</span>
        <span><span className="badge badge-inverted" style={{ fontSize: '0.7rem' }}>Inverted</span> — opposite effect; KO vs. CRISPRa or opposing selection</span>
        <span><span className="badge badge-unknown" style={{ fontSize: '0.7rem' }}>Unknown</span> — FDR &gt; 0.1; insufficient evidence to call</span>
      </div>
    </div>
  );
}
