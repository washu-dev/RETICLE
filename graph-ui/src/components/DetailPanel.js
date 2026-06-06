import React from 'react';
import './DetailPanel.css';

function DetailPanel({ node, onDrillDown }) {
  if (!node) return null;

  const getExternalLinks = () => {
    if (node.type === 'screen') {
      return [];
    }

    if (node.type === 'gene') {
      return [
        { label: '🔬 NCBI Gene', url: `https://www.ncbi.nlm.nih.gov/gene/${node.entrez_id}` },
        { label: '📚 UniProt', url: `https://www.uniprot.org/search?query=${node.label}` }
      ];
    }

    if (node.type === 'publication') {
      const links = [];
      if (node.pmid) {
        links.push({ label: '📄 PubMed', url: `https://pubmed.ncbi.nlm.nih.gov/${node.pmid}/` });
        links.push({ label: '📑 PMC', url: `https://www.ncbi.nlm.nih.gov/pmc/?term=${node.pmid}` });
      }
      if (node.doi) {
        links.push({ label: '🔗 DOI', url: `https://doi.org/${node.doi}` });
      }
      return links;
    }

    return [];
  };

  const badgeClass = `detail-badge badge-${node.type}`;
  const externalLinks = getExternalLinks();

  return (
    <div className="detail-panel">
      <div className="detail-node">
        <div className="detail-header">
          <span className={badgeClass}>
            {node.type === 'screen' && '🔬 Screen'}
            {node.type === 'gene' && '🧬 Gene'}
            {node.type === 'publication' && '📄 Publication'}
          </span>
        </div>

        <div className="detail-title">
          {node.label}
        </div>

        <div className="detail-info">
          {node.type === 'screen' && (
            <>
              <div className="detail-row">
                <span className="detail-label">ID:</span>
                <span className="detail-value">{node.biogrid_id}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Genes:</span>
                <span className="detail-value">{node.num_genes}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Publications:</span>
                <span className="detail-value">{node.num_publications}</span>
              </div>
            </>
          )}

          {node.type === 'gene' && (
            <>
              <div className="detail-row">
                <span className="detail-label">Symbol:</span>
                <span className="detail-value">{node.label}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Entrez ID:</span>
                <span className="detail-value">{node.entrez_id}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Screens:</span>
                <span className="detail-value">{node.num_screens}</span>
              </div>
            </>
          )}

          {node.type === 'publication' && (
            <>
              <div className="detail-row">
                <span className="detail-label">PMID:</span>
                <span className="detail-value">{node.pmid}</span>
              </div>
              {node.doi && (
                <div className="detail-row">
                  <span className="detail-label">DOI:</span>
                  <span className="detail-value" style={{ fontSize: '11px', wordBreak: 'break-all' }}>
                    {node.doi}
                  </span>
                </div>
              )}
              <div className="detail-row">
                <span className="detail-label">Screens:</span>
                <span className="detail-value">{node.num_screens}</span>
              </div>
            </>
          )}
        </div>

        {externalLinks.length > 0 && (
          <div className="external-links">
            {externalLinks.map((link, idx) => (
              <a
                key={idx}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="link-btn"
              >
                {link.label}
                <span>→</span>
              </a>
            ))}
          </div>
        )}

        {(node.type === 'screen' || node.type === 'gene') && (
          <div className="drilldown-btns">
            {node.type === 'screen' && (
              <button
                onClick={() => onDrillDown('screen', node.id)}
                className="btn-drilldown"
              >
                <span>📊 View Genes in Screen</span>
                <span>→</span>
              </button>
            )}
            {node.type === 'gene' && (
              <button
                onClick={() => onDrillDown('gene', node.id)}
                className="btn-drilldown"
              >
                <span>📋 View Screens with Gene</span>
                <span>→</span>
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default DetailPanel;
