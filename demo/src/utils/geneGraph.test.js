import { describe, it, expect } from 'vitest'
import { getConnectedScreens, getConnectedGenes } from './geneGraph'

// g4 = CCDC6 (dark), connected to s1 (rho 0.71), s2 (rho 0.62), s3 (rho 0.54)
describe('getConnectedScreens', () => {
  it('returns screens connected to a gene node', () => {
    const screens = getConnectedScreens('g4')
    expect(screens).toHaveLength(3)
    expect(screens.every(s => s.type === 'screen')).toBe(true)
  })

  it('includes the rho value from the edge', () => {
    const screens = getConnectedScreens('g4')
    const labels = screens.map(s => s.label)
    expect(labels).toContain('Orvedahl 2019')
    const orvedahl = screens.find(s => s.label === 'Orvedahl 2019')
    expect(orvedahl.rho).toBe(0.71)
  })

  it('sorts results by absolute rho descending', () => {
    const screens = getConnectedScreens('g4')
    for (let i = 1; i < screens.length; i++) {
      expect(Math.abs(screens[i - 1].rho)).toBeGreaterThanOrEqual(Math.abs(screens[i].rho))
    }
  })

  it('includes citation and pmid on screen nodes', () => {
    const screens = getConnectedScreens('g4')
    screens.forEach(s => {
      expect(s.citation).toBeTruthy()
      expect(s.pmid).toBeTruthy()
    })
  })

  it('returns empty array for a node with no screen edges', () => {
    expect(getConnectedScreens('nonexistent')).toEqual([])
  })
})

// s1 = Orvedahl 2019, connected to g1 (ATG5), g2 (ATG7), g3 (IRGM), g4 (CCDC6)
describe('getConnectedGenes', () => {
  it('returns genes connected to a screen node', () => {
    const genes = getConnectedGenes('s1')
    expect(genes.length).toBeGreaterThan(0)
    expect(genes.every(g => g.type === 'gene' || g.type === 'dark')).toBe(true)
  })

  it('sorts results by absolute rho descending', () => {
    const genes = getConnectedGenes('s1')
    for (let i = 1; i < genes.length; i++) {
      expect(Math.abs(genes[i - 1].rho)).toBeGreaterThanOrEqual(Math.abs(genes[i].rho))
    }
  })

  it('includes ATG5 for Orvedahl screen', () => {
    const genes = getConnectedGenes('s1')
    expect(genes.map(g => g.label)).toContain('ATG5')
  })

  it('returns empty array for a node with no gene edges', () => {
    expect(getConnectedGenes('nonexistent')).toEqual([])
  })
})
