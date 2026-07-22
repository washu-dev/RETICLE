export function getConnectedScreens(nodeId, graphElements) {
  return graphElements.edges
    .filter(e => e.data.source === nodeId || e.data.target === nodeId)
    .map(e => {
      const otherId = e.data.source === nodeId ? e.data.target : e.data.source;
      const other = graphElements.nodes.find(n => n.data.id === otherId);
      return other?.data.type === 'screen' ? { ...other.data, rho: e.data.rho } : null;
    })
    .filter(Boolean)
    .sort((a, b) => Math.abs(b.rho) - Math.abs(a.rho));
}

export function getConnectedGenes(nodeId, graphElements) {
  return graphElements.edges
    .filter(e => e.data.source === nodeId || e.data.target === nodeId)
    .map(e => {
      const otherId = e.data.source === nodeId ? e.data.target : e.data.source;
      const other = graphElements.nodes.find(n => n.data.id === otherId);
      return (other?.data.type === 'gene' || other?.data.type === 'dark')
        ? { ...other.data, rho: e.data.rho } : null;
    })
    .filter(Boolean)
    .sort((a, b) => Math.abs(b.rho) - Math.abs(a.rho));
}
