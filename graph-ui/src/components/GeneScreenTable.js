import React, { useState, useEffect } from 'react';

function GeneScreenTable({ geneId, onScreenClick }) {
  const [screens, setScreens] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchScreens = async () => {
      try {
        setLoading(true);
        const response = await fetch(`/api/gene/${geneId}/screens`);
        const data = await response.json();
        setScreens(data.screens);
        setError(null);
      } catch (err) {
        setError('Failed to load screens: ' + err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchScreens();
  }, [geneId]);

  if (loading) {
    return <div className="table-container"><p>Loading screens...</p></div>;
  }

  if (error) {
    return <div className="table-container"><p style={{ color: '#d32f2f' }}>{error}</p></div>;
  }

  return (
    <div className="table-container">
      <h2 className="table-title">🔬 Screens with Gene #{geneId}</h2>
      <table>
        <thead>
          <tr>
            <th>BioGrid Screen ID</th>
            <th>Organism</th>
            <th>Source</th>
            <th>Publications</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {screens.map(screen => (
            <tr key={screen.screen_id}>
              <td><strong>{screen.biogrid_screen_id}</strong></td>
              <td>{screen.organism}</td>
              <td>{screen.annotation_source}</td>
              <td>{screen.num_publications}</td>
              <td>
                <button
                  onClick={() => onScreenClick(screen.screen_id)}
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
                  View Genes →
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ marginTop: '16px', fontSize: '12px', color: '#666' }}>
        Total: {screens.length} screens
      </p>
    </div>
  );
}

export default GeneScreenTable;
