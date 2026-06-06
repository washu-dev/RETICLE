import React, { useState, useEffect } from 'react';

function ScreenGeneTable({ screenId, onGeneClick }) {
  const [genes, setGenes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchGenes = async () => {
      try {
        setLoading(true);
        const response = await fetch(`/api/screen/${screenId}/genes`);
        const data = await response.json();
        setGenes(data.genes);
        setError(null);
      } catch (err) {
        setError('Failed to load genes: ' + err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchGenes();
  }, [screenId]);

  if (loading) {
    return <div className="table-container"><p>Loading genes...</p></div>;
  }

  if (error) {
    return <div className="table-container"><p style={{ color: '#d32f2f' }}>{error}</p></div>;
  }

  return (
    <div className="table-container">
      <h2 className="table-title">🧬 Genes in Screen #{screenId}</h2>
      <table>
        <thead>
          <tr>
            <th>Gene Symbol</th>
            <th>Entrez ID</th>
            <th>Publications</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {genes.map(gene => (
            <tr key={gene.gene_id}>
              <td><strong>{gene.gene_symbol}</strong></td>
              <td><code>{gene.entrez_id}</code></td>
              <td>{gene.num_publications}</td>
              <td>
                <button
                  onClick={() => onGeneClick(gene.gene_id)}
                  style={{
                    padding: '6px 12px',
                    background: '#667eea',
                    color: 'white',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '12px'
                  }}
                >
                  View Screens →
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ marginTop: '16px', fontSize: '12px', color: '#666' }}>
        Total: {genes.length} genes
      </p>
    </div>
  );
}

export default ScreenGeneTable;
