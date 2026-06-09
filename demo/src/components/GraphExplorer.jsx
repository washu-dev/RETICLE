import { useEffect, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import { GRAPH_ELEMENTS } from '../mockData';
import { Info } from 'lucide-react';

const STYLES = [
  {
    selector: 'node[type="screen"]',
    style: {
      'background-color': '#2563b8',
      'border-color': '#4f9cf9',
      'border-width': 2,
      width: 60, height: 60,
      label: 'data(label)',
      'text-valign': 'bottom', 'text-halign': 'center',
      'color': '#a8b8d8', 'font-size': 10,
      'text-margin-y': 6,
      'text-wrap': 'wrap', 'text-max-width': 80,
    },
  },
  {
    selector: 'node[type="gene"]',
    style: {
      'background-color': '#5b21b6',
      'border-color': '#a78bfa',
      'border-width': 2,
      width: 40, height: 40,
      label: 'data(label)',
      'text-valign': 'bottom', 'text-halign': 'center',
      'color': '#a8b8d8', 'font-size': 10,
      'text-margin-y': 5,
    },
  },
  {
    selector: 'node[type="dark"]',
    style: {
      'background-color': '#78450a',
      'border-color': '#fbbf24',
      'border-width': 2.5,
      width: 42, height: 42,
      label: 'data(label)',
      'text-valign': 'bottom', 'text-halign': 'center',
      'color': '#fbbf24', 'font-size': 10, 'font-weight': 'bold',
      'text-margin-y': 5,
    },
  },
  {
    selector: 'node[type="pub"]',
    style: {
      'background-color': '#831843',
      'border-color': '#f472b6',
      'border-width': 2,
      width: 34, height: 34,
      label: 'data(label)',
      'text-valign': 'bottom', 'text-halign': 'center',
      'color': '#a8b8d8', 'font-size': 9,
      'text-margin-y': 5,
    },
  },
  {
    selector: 'edge',
    style: {
      'line-color': '#2a3a5c',
      width: 1.5,
      'curve-style': 'bezier',
      opacity: 0.7,
    },
  },
  {
    selector: 'node:selected',
    style: {
      'border-color': 'white',
      'border-width': 3,
    },
  },
  {
    selector: 'node.highlighted',
    style: { opacity: 1 },
  },
  {
    selector: 'node.faded',
    style: { opacity: 0.2 },
  },
  {
    selector: 'edge.faded',
    style: { opacity: 0.05 },
  },
];

export default function GraphExplorer() {
  const cyRef = useRef(null);
  const containerRef = useRef(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [layout, setLayout] = useState('cose');

  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: [...GRAPH_ELEMENTS.nodes, ...GRAPH_ELEMENTS.edges],
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

      cy.nodes().removeClass('highlighted faded');
      cy.edges().removeClass('faded');

      const connected = node.neighborhood().nodes();
      cy.nodes().not(node).not(connected).addClass('faded');
      cy.edges().not(node.connectedEdges()).addClass('faded');
      node.addClass('highlighted');
      connected.addClass('highlighted');
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        setSelectedNode(null);
        cy.nodes().removeClass('highlighted faded');
        cy.edges().removeClass('faded');
      }
    });

    cyRef.current = cy;
    return () => cy.destroy();
  }, [layout]);

  const typeLabel = {
    screen: 'CRISPR Screen',
    gene: 'Gene',
    dark: 'Dark Candidate',
    pub: 'Publication',
  };

  const typeColor = {
    screen: 'var(--blue)',
    gene: 'var(--purple)',
    dark: 'var(--amber)',
    pub: 'var(--pink)',
  };

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>Screen–Gene–Publication graph</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-3)' }}>Click any node to explore connections</div>
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

      <div style={{ display: 'flex', gap: 16 }}>
        {/* Cytoscape canvas */}
        <div className="card" style={{ flex: 1, padding: 0, overflow: 'hidden' }}>
          <div ref={containerRef} className="cy-container" />
        </div>

        {/* Info panel */}
        <div style={{ width: 220 }}>
          {selectedNode ? (
            <div className="card" style={{ height: '100%' }}>
              <div style={{ marginBottom: 12 }}>
                <span style={{
                  fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em',
                  color: typeColor[selectedNode.type] ?? 'var(--text-3)',
                }}>
                  {typeLabel[selectedNode.type] ?? selectedNode.type}
                </span>
              </div>
              <div style={{ fontWeight: 700, fontSize: '1rem', fontFamily: 'monospace', marginBottom: 10 }}>
                {selectedNode.label}
              </div>
              <div style={{ fontSize: '0.82rem', color: 'var(--text-2)', lineHeight: 1.6 }}>
                {selectedNode.detail}
              </div>
              {selectedNode.type === 'dark' && (
                <div style={{
                  marginTop: 12, padding: '10px 12px', borderRadius: 8,
                  background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)',
                  fontSize: '0.78rem', color: 'var(--amber)',
                }}>
                  Dark-matter candidate — minimal prior characterization
                </div>
              )}
            </div>
          ) : (
            <div className="card" style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-3)', fontSize: '0.8rem', marginBottom: 4 }}>
                <Info size={14} /> Node legend
              </div>
              {[
                { color: '#2563b8', border: '#4f9cf9', label: 'Screen', desc: `${GRAPH_ELEMENTS.nodes.filter(n => n.data.type === 'screen').length} in view` },
                { color: '#5b21b6', border: '#a78bfa', label: 'Gene',   desc: `${GRAPH_ELEMENTS.nodes.filter(n => n.data.type === 'gene').length} known` },
                { color: '#78450a', border: '#fbbf24', label: 'Dark candidate', desc: `${GRAPH_ELEMENTS.nodes.filter(n => n.data.type === 'dark').length} novel` },
                { color: '#831843', border: '#f472b6', label: 'Publication', desc: `${GRAPH_ELEMENTS.nodes.filter(n => n.data.type === 'pub').length} papers` },
              ].map(n => (
                <div key={n.label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 14, height: 14, borderRadius: '50%', background: n.color, border: `2px solid ${n.border}`, flexShrink: 0 }} />
                  <div>
                    <div style={{ fontSize: '0.82rem', fontWeight: 500 }}>{n.label}</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-3)' }}>{n.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
