import React, { useState, useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import './App.css';
import GraphView from './components/GraphView';
import DetailPanel from './components/DetailPanel';
import ScreenGeneTable from './components/ScreenGeneTable';
import GeneScreenTable from './components/GeneScreenTable';

function App() {
  const [graphData, setGraphData] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [view, setView] = useState('graph'); // 'graph', 'screen-genes', 'gene-screens'
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Fetch initial graph data
  useEffect(() => {
    const fetchGraph = async () => {
      try {
        setLoading(true);
        const response = await fetch('/api/graph/overview');
        const data = await response.json();
        setGraphData(data);
        setError(null);
      } catch (err) {
        setError('Failed to load graph data: ' + err.message);
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchGraph();
  }, []);

  const handleNodeClick = (node) => {
    setSelectedNode(node);
  };

  const handleDrillDown = (nodeType, nodeId) => {
    if (nodeType === 'screen') {
      setView('screen-genes');
      setSelectedNode({ id: nodeId, type: 'screen' });
    } else if (nodeType === 'gene') {
      setView('gene-screens');
      setSelectedNode({ id: nodeId, type: 'gene' });
    }
  };

  const handleBack = () => {
    setView('graph');
    setSelectedNode(null);
  };

  if (loading) {
    return <div className="app loading">Loading graph data...</div>;
  }

  if (error) {
    return <div className="app error">{error}</div>;
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>🧬 RETICLE: Screen-Gene-Publication Explorer</h1>
        {view !== 'graph' && (
          <button onClick={handleBack} className="btn-back">← Back to Graph</button>
        )}
      </header>

      <div className="app-content">
        {view === 'graph' && graphData && (
          <>
            <GraphView
              data={graphData}
              onNodeClick={handleNodeClick}
              selectedNode={selectedNode}
            />
            {selectedNode && (
              <DetailPanel
                node={selectedNode}
                onDrillDown={handleDrillDown}
              />
            )}
          </>
        )}

        {view === 'screen-genes' && selectedNode && (
          <ScreenGeneTable
            screenId={selectedNode.id}
            onGeneClick={(geneId) => handleDrillDown('gene', geneId)}
          />
        )}

        {view === 'gene-screens' && selectedNode && (
          <GeneScreenTable
            geneId={selectedNode.id}
            onScreenClick={(screenId) => handleDrillDown('screen', screenId)}
          />
        )}
      </div>
    </div>
  );
}

export default App;
