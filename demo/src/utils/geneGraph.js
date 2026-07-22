import { GRAPH_ELEMENTS } from '../mockData'

export function getConnectedScreens(nodeId) {
  return GRAPH_ELEMENTS.edges
    .filter(e => e.data.source === nodeId || e.data.target === nodeId)
    .map(e => {
      const otherId = e.data.source === nodeId ? e.data.target : e.data.source
      const other = GRAPH_ELEMENTS.nodes.find(n => n.data.id === otherId)
      return other?.data.type === 'screen' ? { ...other.data, rho: e.data.rho } : null
    })
    .filter(Boolean)
    .sort((a, b) => Math.abs(b.rho) - Math.abs(a.rho))
}

export function getConnectedGenes(nodeId) {
  return GRAPH_ELEMENTS.edges
    .filter(e => e.data.source === nodeId || e.data.target === nodeId)
    .map(e => {
      const otherId = e.data.source === nodeId ? e.data.target : e.data.source
      const other = GRAPH_ELEMENTS.nodes.find(n => n.data.id === otherId)
      return (other?.data.type === 'gene' || other?.data.type === 'dark')
        ? { ...other.data, rho: e.data.rho } : null
    })
    .filter(Boolean)
    .sort((a, b) => Math.abs(b.rho) - Math.abs(a.rho))
}
