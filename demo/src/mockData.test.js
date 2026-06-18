import { describe, it, expect } from 'vitest'
import {
  MATCHED_SCREENS,
  DARK_GENES,
  GRAPH_ELEMENTS,
  GENE_RATIONALES,
  STRING_INTERACTORS,
} from './mockData'

describe('GRAPH_ELEMENTS integrity', () => {
  it('has no pub-type nodes', () => {
    const pubNodes = GRAPH_ELEMENTS.nodes.filter(n => n.data.type === 'pub')
    expect(pubNodes).toHaveLength(0)
  })

  it('every screen node has a citation and pmid', () => {
    const screens = GRAPH_ELEMENTS.nodes.filter(n => n.data.type === 'screen')
    screens.forEach(s => {
      expect(s.data.citation, `${s.data.label} missing citation`).toBeTruthy()
      expect(s.data.pmid, `${s.data.label} missing pmid`).toBeTruthy()
    })
  })

  it('all edge source/target ids reference real nodes', () => {
    const nodeIds = new Set(GRAPH_ELEMENTS.nodes.map(n => n.data.id))
    GRAPH_ELEMENTS.edges.forEach(e => {
      expect(nodeIds.has(e.data.source), `unknown source ${e.data.source}`).toBe(true)
      expect(nodeIds.has(e.data.target), `unknown target ${e.data.target}`).toBe(true)
    })
  })

  it('all gene/dark nodes have a label', () => {
    GRAPH_ELEMENTS.nodes
      .filter(n => n.data.type === 'gene' || n.data.type === 'dark')
      .forEach(n => expect(n.data.label).toBeTruthy())
  })
})

describe('MATCHED_SCREENS', () => {
  it('has 8 screens', () => {
    expect(MATCHED_SCREENS).toHaveLength(8)
  })

  it('every screen has required fields', () => {
    MATCHED_SCREENS.forEach(s => {
      expect(s.pmid).toBeTruthy()
      expect(s.rho).toBeDefined()
      expect(s.fdr).toBeDefined()
      expect(['agree', 'inverted', 'unknown']).toContain(s.directionality)
    })
  })

  it('rho values are in [-1, 1]', () => {
    MATCHED_SCREENS.forEach(s => {
      expect(Math.abs(s.rho)).toBeLessThanOrEqual(1)
    })
  })
})

describe('DARK_GENES', () => {
  it('has 16 entries', () => {
    expect(DARK_GENES).toHaveLength(16)
  })

  it('every entry has a darkScore in [0, 10]', () => {
    DARK_GENES.forEach(g => {
      expect(g.darkScore).toBeGreaterThanOrEqual(0)
      expect(g.darkScore).toBeLessThanOrEqual(10)
    })
  })

  it('correlation values are in [0, 1]', () => {
    DARK_GENES.forEach(g => {
      expect(g.correlation).toBeGreaterThanOrEqual(0)
      expect(g.correlation).toBeLessThanOrEqual(1)
    })
  })
})

describe('GENE_RATIONALES', () => {
  it('CCDC6 rationale has required fields', () => {
    const r = GENE_RATIONALES.CCDC6
    expect(r.hypothesis).toBeTruthy()
    expect(r.mechanisticContext).toBeTruthy()
    expect(r.citations).toBeInstanceOf(Array)
    expect(r.citations.length).toBeGreaterThan(0)
    expect(r.suggestedValidation).toBeTruthy()
  })

  it('every citation has a pmid', () => {
    Object.values(GENE_RATIONALES).forEach(r => {
      r.citations.forEach(c => expect(c.pmid).toBeTruthy())
    })
  })
})
