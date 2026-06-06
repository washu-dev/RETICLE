import React, { useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import './GraphView.css';

cytoscape.use(coseBilkent);

function GraphView({ data, onNodeClick, selectedNode }) {
  const containerRef = useRef(null);
  const cyRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !data) return;

    // Create nodes
    const nodes = [];

    // Screen nodes
    data.screens.forEach(screen => {
      nodes.push({
        data: {
          id: `screen-${screen.screen_id}`,
          label: `S${screen.screen_id}`,
          type: 'screen',
          biogrid_id: screen.biogrid_screen_id,
          num_genes: screen.num_genes,
          num_publications: screen.num_publications,
          nodeId: screen.screen_id
        }
      });
    });

    // Gene nodes
    data.genes.forEach(gene => {
      nodes.push({
        data: {
          id: `gene-${gene.gene_id}`,
          label: gene.gene_symbol,
          type: 'gene',
          entrez_id: gene.entrez_id,
          num_screens: gene.num_screens,
          nodeId: gene.gene_id
        }
      });
    });

    // Publication nodes
    data.publications.forEach(pub => {
      nodes.push({
        data: {
          id: `pub-${pub.publication_id}`,
          label: `PMID: ${pub.pmid}`,
          type: 'publication',
          pmid: pub.pmid,
          doi: pub.doi,
          num_screens: pub.num_screens,
          nodeId: pub.publication_id
        }
      });
    });

    // Create edges
    const edges = [];
    const edgeSet = new Set();

    data.links.forEach(link => {
      const screenNodeId = `screen-${link.screen_id}`;
      const geneNodeId = `gene-${link.gene_id}`;
      const pubNodeId = `pub-${link.publication_id}`;

      // Screen -> Gene
      const sg_key = `${screenNodeId}-${geneNodeId}`;
      if (!edgeSet.has(sg_key)) {
        edges.push({
          data: {
            id: `edge-${sg_key}`,
            source: screenNodeId,
            target: geneNodeId,
            type: 'screen-gene'
          }
        });
        edgeSet.add(sg_key);
      }

      // Screen -> Publication
      const sp_key = `${screenNodeId}-${pubNodeId}`;
      if (!edgeSet.has(sp_key)) {
        edges.push({
          data: {
            id: `edge-${sp_key}`,
            source: screenNodeId,
            target: pubNodeId,
            type: 'screen-pub'
          }
        });
        edgeSet.add(sp_key);
      }

      // Gene -> Publication (optional: if available in DB)
      const gp_key = `${geneNodeId}-${pubNodeId}`;
      if (!edgeSet.has(gp_key)) {
        edges.push({
          data: {
            id: `edge-${gp_key}`,
            source: geneNodeId,
            target: pubNodeId,
            type: 'gene-pub'
          }
        });
        edgeSet.add(gp_key);
      }
    });

    // Initialize Cytoscape
    const cy = cytoscape({
      container: containerRef.current,
      elements: [...nodes, ...edges],
      style: [
        {
          selector: 'node',
          style: {
            'content': 'data(label)',
            'text-valign': 'center',
            'text-halign': 'center',
            'background-color': '#667eea',
            'width': '50px',
            'height': '50px',
            'font-size': '12px',
            'color': 'white',
            'font-weight': 'bold',
            'border-width': '2px',
            'border-color': '#f5f5f5',
            'padding': '10px'
          }
        },
        {
          selector: 'node[type="screen"]',
          style: {
            'background-color': '#1976d2',
            'width': '60px',
            'height': '60px'
          }
        },
        {
          selector: 'node[type="gene"]',
          style: {
            'background-color': '#7b1fa2',
            'width': '50px',
            'height': '50px'
          }
        },
        {
          selector: 'node[type="publication"]',
          style: {
            'background-color': '#c2185b',
            'width': '55px',
            'height': '55px',
            'font-size': '10px'
          }
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': '3px',
            'border-color': '#ffd700',
            'box-shadow': '0 0 15px rgba(255, 215, 0, 0.5)'
          }
        },
        {
          selector: 'edge',
          style: {
            'target-arrow-shape': 'triangle',
            'line-color': '#ccc',
            'target-arrow-color': '#ccc',
            'width': '1px',
            'opacity': 0.5,
            'curve-style': 'bezier'
          }
        }
      ],
      layout: {
        name: 'cose-bilkent',
        nodeDimensionsIncludeLabels: true,
        randomize: false,
        animate: true,
        animationDuration: 500,
        nodeSeparation: 50,
        gravity: 0.5
      }
    });

    // Handle node clicks
    cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      const nodeData = node.data();
      onNodeClick({
        ...nodeData,
        id: nodeData.nodeId,
        type: nodeData.type,
        label: nodeData.label
      });

      // Highlight selected node
      cy.elements().removeClass('selected');
      node.addClass('selected');
    });

    // Highlight related nodes on hover
    cy.on('mouseover', 'node', (evt) => {
      const node = evt.target;
      node.addClass('hovered');
      node.successors().addClass('connected');
      node.predecessors().addClass('connected');
    });

    cy.on('mouseout', 'node', (evt) => {
      const node = evt.target;
      node.removeClass('hovered');
      cy.elements().removeClass('connected');
    });

    cyRef.current = cy;

    // Cleanup
    return () => {
      cy.destroy();
    };
  }, [data, onNodeClick]);

  // Update selection on prop change
  useEffect(() => {
    if (cyRef.current && selectedNode) {
      const nodeId = `${selectedNode.type}-${selectedNode.id}`;
      const node = cyRef.current.getElementById(nodeId);
      if (node.length) {
        cyRef.current.elements().removeClass('selected');
        node.addClass('selected');
      }
    }
  }, [selectedNode]);

  return (
    <div className="graph-container">
      <div ref={containerRef} className="cytoscape-container" />
      <div className="graph-info">
        <p>📊 Screens: {data?.screens?.length || 0} | 🧬 Genes: {data?.genes?.length || 0} | 📄 Publications: {data?.publications?.length || 0}</p>
      </div>
    </div>
  );
}

export default GraphView;
