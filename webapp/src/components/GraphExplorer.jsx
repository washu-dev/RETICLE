import { useEffect, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import { GRAPH_ELEMENTS as MOCK_GRAPH_ELEMENTS } from '../mockData';
import { getConnectedScreens, getConnectedGenes } from '../utils/geneGraph';
import { Info, GitBranch, ExternalLink, BookOpen } from 'lucide-react';

const STYLES = [
  {
    selector: 'node[type="screen"]',
    style: {
      'background-color': '#1a2a4a',
      'border-color': '#2563b8',
      'border-width': 2,
      width: 52, height: 52,
      label: 'data(label)',
      'text-valign': 'bottom', 'text-halign': 'center',
      'color': '#7a9cc8', 'font-size': 9,
      'text-margin-y': 6,
      'text-wrap': 'wrap', 'text-max-width': 80,
    },
  },
  {
    selector: 'node[type="gene"]',
    style: {
      'background-color': '#2d1b69',
      'border-color': '#7c3aed',
      'border-width': 2.5,
      width: 52, height: 52,
      label: 'data(label)',
      'text-valign': 'bottom', 'text-halign': 'center',
      'color': '#c4b5fd', 'font-size': 11, 'font-weight': 'bold',
      'text-margin-y': 6,
    },
  },
  {
    selector: 'node[type="dark"]',
    style: {
      'background-color': '#78350f',
      'border-color': '#fbbf24',
      'border-width': 3,
      width: 58, height: 58,
      label: 'data(label)',
      'text-valign': 'bottom', 'text-halign': 'center',
      'color': '#fbbf24', 'font-size': 11, 'font-weight': 'bold',
      'text-margin-y': 6,
    },
  },
  {
    selector: 'edge',
    style: {
      'line-color': '#1e3a5f',
      width: 1.5,
      'curve-style': 'bezier',
      opacity: 0.6,
    },
  },
  {
    selector: 'edge:selected',
    style: { 'line-color': '#4f9cf9', width: 2.5, opacity: 1 },
  },
  {
    selector: 'node:selected',
    style: { 'border-color': 'white', 'border-width': 3 },
  },
  {
    selector: 'node.highlighted',
    style: { opacity: 1 },
  },
  {
    selector: 'node.faded',
    style: { opacity: 0.15 },
  },
  {
    selector: 'edge.faded',
    style: { opacity: 0.04 },
  },
];

export default function GraphExplorer({ graphElements, focusGene, onGeneSelect }) {
  const elements     = graphElements ?? MOCK_GRAPH_ELEMENTS;
  const geneNodes    = elements.nodes.filter(n => n.data.type === 'gene' || n.data.type === 'dark');
  const cyRef        = useRef(null);
  const containerRef = useRef(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [layout, setLayout] = useState('cose');

  function applyFocus(cy, label) {
    const node = cy.nodes().filter(n => n.data('label') === label)[0];
    if (!node) return;
    const data = node.data();
    setSelectedNode(data);
    setSelectedEdge(null);
    cy.nodes().removeClass('highlighted faded');
    cy.edges().removeClass('faded');
    const connected = node.neighborhood().nodes();
    cy.nodes().not(node).not(connected).addClass('faded');
    cy.edges().not(node.connectedEdges()).addClass('faded');
    node.addClass('highlighted');
    connected.addClass('highlighted');
    cy.animate({ fit: { eles: node.union(connected), padding: 60 }, duration: 400 });
  }

  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: [...elements.nodes, ...elements.edges],
      style: STYLES,
      layout: { name: layout, animate: true, animationDuration: 600, padding: 40 },
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
    });

    cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      const data = node.data();
      setSelectedNode(data);
      setSelectedEdge(null);
      if (onGeneSelect && (data.type === 'gene' || data.type === 'dark')) {
        onGeneSelect(data.label);
      }
      cy.nodes().removeClass('highlighted faded');
      cy.edges().removeClass('faded');
      const connected = node.neighborhood().nodes();
      cy.nodes().not(node).not(connected).addClass('faded');
      cy.edges().not(node.connectedEdges()).addClass('faded');
      node.addClass('highlighted');
      connected.addClass('highlighted');
    });

    cy.on('tap', 'edge', (evt) => {
      const edge = evt.target;
      setSelectedEdge(edge.data());
      setSelectedNode(null);
      cy.nodes().removeClass('highlighted faded');
      cy.edges().removeClass('faded');
      const src = edge.source();
      const tgt = edge.target();
      cy.nodes().not(src).not(tgt).addClass('faded');
      cy.edges().not(edge).addClass('faded');
      src.addClass('highlighted');
      tgt.addClass('highlighted');
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        setSelectedNode(null);
        setSelectedEdge(null);
        cy.nodes().removeClass('highlighted faded');
        cy.edges().removeClass('faded');
      }
    });

    cyRef.current = cy;

    if (focusGene) applyFocus(cy, focusGene);

    return () => cy.destroy();
  }, [layout]); // eslint-disable-line react-hooks/exhaustive-deps

  // Respond to focusGene changes after mount
  useEffect(() => {
    if (focusGene && cyRef.current) applyFocus(cyRef.current, focusGene);
  }, [focusGene]);

  const typeColor = {
    screen: 'var(--blue)',
    gene:   'var(--purple)',
    dark:   'var(--amber)',
  };

  function renderInfoPanel() {
    if (selectedEdge) {
      const srcNode = elements.nodes.find(n => n.data.id === selectedEdge.source)?.data;
      const tgtNode = elements.nodes.find(n => n.data.id === selectedEdge.target)?.data;
      const rhoColor = selectedEdge.rho >= 0 ? 'var(--blue)' : 'var(--orange)';
      return (
        <div className="card" style={{ height: '100%' }}>
          <div style={{ fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', marginBottom: 10 }}>
            Connection
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: '0.82rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ color: 'var(--text-3)', fontSize: '0.72rem' }}>FROM</span>
              <span style={{ fontWeight: 600, color: typeColor[srcNode?.type] ?? 'var(--text-1)' }}>{srcNode?.label}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ color: 'var(--text-3)', fontSize: '0.72rem' }}>TO</span>
              <span style={{ fontWeight: 600, color: typeColor[tgtNode?.type] ?? 'var(--text-1)', fontFamily: 'monospace' }}>{tgtNode?.label}</span>
            </div>
            {selectedEdge.rho !== null && (
              <div style={{
                marginTop: 4, padding: '10px 12px', borderRadius: 8,
                background: 'var(--bg-2)', border: '1px solid var(--border)',
              }}>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-3)', marginBottom: 4 }}>SPEARMAN ρ</div>
                <div style={{ fontSize: '1.3rem', fontWeight: 800, color: rhoColor, fontFamily: 'monospace' }}>
                  {selectedEdge.rho > 0 ? '+' : ''}{selectedEdge.rho.toFixed(2)}
                </div>
              </div>
            )}
          </div>
        </div>
      );
    }

    if (selectedNode) {
      const isGene    = selectedNode.type === 'gene' || selectedNode.type === 'dark';
      const isScreen  = selectedNode.type === 'screen';
      const connectedScreens = isGene   ? getConnectedScreens(selectedNode.id, elements) : [];
      const connectedGenes   = isScreen ? getConnectedGenes(selectedNode.id, elements)   : [];

      return (
        <div className="card" style={{ height: '100%', overflowY: 'auto' }}>
          <div style={{ marginBottom: 8 }}>
            <span style={{
              fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: '0.08em', color: typeColor[selectedNode.type] ?? 'var(--text-3)',
            }}>
              {selectedNode.type === 'dark' ? 'Dark Candidate' : selectedNode.type === 'gene' ? 'Gene' : 'CRISPR Screen'}
            </span>
          </div>
          <div style={{ fontWeight: 700, fontSize: '1.05rem', fontFamily: 'monospace', marginBottom: 4 }}>
            {selectedNode.label}
          </div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-2)', marginBottom: 12, lineHeight: 1.5 }}>
            {selectedNode.detail}
          </div>

          {/* Gene: show screens + embedded paper */}
          {isGene && connectedScreens.length > 0 && (
            <div>
              <div style={{
                fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase',
                letterSpacing: '0.08em', color: 'var(--text-3)', marginBottom: 8,
                display: 'flex', alignItems: 'center', gap: 5,
              }}>
                <GitBranch size={11} /> {connectedScreens.length} screen{connectedScreens.length !== 1 ? 's' : ''} · papers
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {connectedScreens.map(s => (
                  <div key={s.id} style={{
                    padding: '10px 12px', borderRadius: 8,
                    background: 'var(--bg-2)', border: '1px solid var(--border)',
                    fontSize: '0.78rem',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                      <span style={{ fontWeight: 600, color: 'var(--blue)', lineHeight: 1.3, flex: 1, marginRight: 6 }}>{s.label}</span>
                      {s.rho !== null && (
                        <span style={{
                          color: s.rho >= 0 ? 'var(--blue)' : 'var(--orange)',
                          fontFamily: 'monospace', fontWeight: 700, fontSize: '0.8rem', flexShrink: 0,
                        }}>
                          ρ {s.rho > 0 ? '+' : ''}{s.rho.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <div style={{ color: 'var(--text-3)', fontSize: '0.72rem', marginBottom: 5 }}>{s.detail}</div>
                    {s.citation && (
                      <a
                        href={`https://pubmed.ncbi.nlm.nih.gov/${s.pmid}`}
                        target="_blank" rel="noreferrer"
                        style={{
                          display: 'inline-flex', alignItems: 'center', gap: 4,
                          color: 'var(--text-3)', fontSize: '0.7rem', textDecoration: 'none',
                          borderTop: '1px solid var(--border)', paddingTop: 5, marginTop: 2, width: '100%',
                        }}
                        onMouseEnter={e => e.currentTarget.style.color = 'var(--blue)'}
                        onMouseLeave={e => e.currentTarget.style.color = 'var(--text-3)'}
                      >
                        <BookOpen size={10} />
                        {s.citation}
                        <ExternalLink size={9} style={{ marginLeft: 'auto', flexShrink: 0 }} />
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Screen: show genes */}
          {isScreen && (
            <>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-3)', marginBottom: 10 }}>
                <strong style={{ color: 'var(--blue)' }}>{selectedNode.geneCount?.toLocaleString()}</strong> genes screened
              </div>
              {selectedNode.citation && (
                <a
                  href={`https://pubmed.ncbi.nlm.nih.gov/${selectedNode.pmid}`}
                  target="_blank" rel="noreferrer"
                  style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    padding: '8px 10px', borderRadius: 7, marginBottom: 12,
                    background: 'var(--bg-2)', border: '1px solid var(--border)',
                    color: 'var(--text-2)', fontSize: '0.75rem', textDecoration: 'none',
                  }}
                  onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--blue)'}
                  onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
                >
                  <BookOpen size={12} style={{ flexShrink: 0 }} />
                  <span style={{ flex: 1, lineHeight: 1.3 }}>{selectedNode.citation}</span>
                  <ExternalLink size={10} style={{ flexShrink: 0 }} />
                </a>
              )}
              {connectedGenes.length > 0 && (
                <div>
                  <div style={{
                    fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase',
                    letterSpacing: '0.08em', color: 'var(--text-3)', marginBottom: 8,
                    display: 'flex', alignItems: 'center', gap: 5,
                  }}>
                    <GitBranch size={11} /> {connectedGenes.length} gene{connectedGenes.length !== 1 ? 's' : ''} in view
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    {connectedGenes.map(g => (
                      <div key={g.id} style={{
                        padding: '6px 10px', borderRadius: 7,
                        background: 'var(--bg-2)', border: '1px solid var(--border)',
                        fontSize: '0.78rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      }}>
                        <span style={{ fontWeight: 600, color: g.type === 'dark' ? 'var(--amber)' : 'var(--purple)', fontFamily: 'monospace' }}>{g.label}</span>
                        {g.rho !== null && (
                          <span style={{ color: g.rho >= 0 ? 'var(--blue)' : 'var(--orange)', fontFamily: 'monospace', fontSize: '0.75rem' }}>
                            ρ {g.rho > 0 ? '+' : ''}{g.rho.toFixed(2)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {selectedNode.type === 'dark' && (
            <div style={{
              marginTop: 12, padding: '8px 10px', borderRadius: 7,
              background: 'rgba(251,191,36,0.07)', border: '1px solid rgba(251,191,36,0.2)',
              fontSize: '0.75rem', color: 'var(--amber)',
            }}>
              Dark-matter candidate — minimal prior characterization
            </div>
          )}
        </div>
      );
    }

    // Legend (nothing selected)
    return (
      <div className="card" style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-3)', fontSize: '0.8rem', marginBottom: 2 }}>
          <Info size={14} /> Node legend
        </div>
        {[
          { color: '#1a2a4a', border: '#2563b8', label: 'Screen',         desc: `${elements.nodes.filter(n => n.data.type === 'screen').length} matched · includes paper` },
          { color: '#2d1b69', border: '#7c3aed', label: 'Gene',           desc: `${elements.nodes.filter(n => n.data.type === 'gene').length} known pathway genes` },
          { color: '#78350f', border: '#fbbf24', label: 'Dark candidate', desc: `${elements.nodes.filter(n => n.data.type === 'dark').length} novel low-pub genes` },
        ].map(n => (
          <div key={n.label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 14, height: 14, borderRadius: '50%', background: n.color, border: `2px solid ${n.border}`, flexShrink: 0 }} />
            <div>
              <div style={{ fontSize: '0.82rem', fontWeight: 500 }}>{n.label}</div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-3)' }}>{n.desc}</div>
            </div>
          </div>
        ))}
        <div style={{ marginTop: 4, paddingTop: 10, borderTop: '1px solid var(--border)', fontSize: '0.72rem', color: 'var(--text-3)', lineHeight: 1.6 }}>
          Click a <strong>gene</strong> to see every screen and paper that mentions it.<br />
          Click a <strong>screen</strong> to see its paper and constituent genes.
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12, gap: 16, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>Gene → Screen → Paper graph</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-3)' }}>
            Click a gene to see every screen and paper that mentions it
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['cose', 'breadthfirst', 'circle'].map(l => (
            <button
              key={l}
              onClick={() => setLayout(l)}
              style={{
                padding: '6px 14px', borderRadius: 7, fontSize: '0.8rem',
                background: layout === l ? 'var(--bg-3)' : 'var(--bg-2)',
                border: `1px solid ${layout === l ? 'var(--blue-dim)' : 'var(--border)'}`,
                color: layout === l ? 'var(--text-1)' : 'var(--text-3)',
              }}
            >{l}</button>
          ))}
        </div>
      </div>

      {/* Gene quick-select chips */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-3)', alignSelf: 'center', marginRight: 4 }}>Select gene:</span>
        {geneNodes.map(n => {
          const isActive = selectedNode?.id === n.data.id || focusGene === n.data.label;
          return (
            <button
              key={n.data.id}
              onClick={() => cyRef.current && applyFocus(cyRef.current, n.data.label)}
              style={{
                padding: '4px 10px', borderRadius: 6, fontSize: '0.78rem',
                fontFamily: 'monospace', fontWeight: 600,
                background: isActive
                  ? (n.data.type === 'dark' ? 'rgba(251,191,36,0.18)' : 'rgba(124,58,237,0.18)')
                  : 'var(--bg-2)',
                border: `1px solid ${isActive
                  ? (n.data.type === 'dark' ? 'var(--amber)' : 'var(--purple)')
                  : 'var(--border)'}`,
                color: isActive
                  ? (n.data.type === 'dark' ? 'var(--amber)' : 'var(--purple)')
                  : 'var(--text-2)',
                transition: 'all 0.15s',
              }}
            >
              {n.data.label}
            </button>
          );
        })}
        {selectedNode && (
          <button
            onClick={() => {
              setSelectedNode(null);
              setSelectedEdge(null);
              if (cyRef.current) {
                cyRef.current.nodes().removeClass('highlighted faded');
                cyRef.current.edges().removeClass('faded');
              }
            }}
            style={{
              padding: '4px 10px', borderRadius: 6, fontSize: '0.78rem',
              background: 'var(--bg-2)', border: '1px solid var(--border)',
              color: 'var(--text-3)',
            }}
          >
            ✕ Clear
          </button>
        )}
      </div>

      <div style={{ display: 'flex', gap: 16 }}>
        {/* Cytoscape canvas */}
        <div className="card" style={{ flex: 1, padding: 0, overflow: 'hidden' }}>
          <div ref={containerRef} className="cy-container" />
        </div>

        {/* Info panel */}
        <div style={{ width: 240 }}>
          {renderInfoPanel()}
        </div>
      </div>
    </div>
  );
}
