import { describe, it, expect } from 'vitest'
import { parseGenes } from './parseGenes'

describe('parseGenes', () => {
  it('parses a valid CSV with header', () => {
    const input = 'gene_symbol,score\nATG5,-3.21\nULK1,-2.74\nBECN1,-2.43'
    const result = parseGenes(input)
    expect(result).toHaveLength(3)
    expect(result[0]).toEqual({ symbol: 'ATG5', score: -3.21 })
    expect(result[2]).toEqual({ symbol: 'BECN1', score: -2.43 })
  })

  it('parses a valid TSV', () => {
    const input = 'gene_symbol\tscore\nATG5\t-3.21\nULK1\t-2.74\nBECN1\t-2.43'
    const result = parseGenes(input)
    expect(result).toHaveLength(3)
    expect(result[0].symbol).toBe('ATG5')
    expect(result[0].score).toBe(-3.21)
  })

  it('returns null when fewer than 3 data lines', () => {
    expect(parseGenes('gene_symbol,score\nATG5,-3.21\nULK1,-2.74')).toBeNull()
    expect(parseGenes('gene_symbol,score\nATG5,-3.21')).toBeNull()
    expect(parseGenes('')).toBeNull()
  })

  it('strips whitespace from gene symbols', () => {
    const input = 'gene_symbol,score\n  ATG5  ,-3.21\n  ULK1  ,-2.74\n  BECN1  ,-2.43'
    const result = parseGenes(input)
    expect(result[0].symbol).toBe('ATG5')
    expect(result[1].symbol).toBe('ULK1')
  })

  it('defaults score to 0 when unparseable', () => {
    const input = 'gene_symbol,score\nATG5,bad\nULK1,-2.74\nBECN1,-2.43'
    const result = parseGenes(input)
    expect(result[0].score).toBe(0)
  })

  it('handles positive scores', () => {
    const input = 'gene_symbol,score\nMTOR,1.44\nAKT1,1.67\nRPTOR,1.89'
    const result = parseGenes(input)
    expect(result[0]).toEqual({ symbol: 'MTOR', score: 1.44 })
  })

  it('skips lines with empty symbols', () => {
    const input = 'gene_symbol,score\nATG5,-3.21\n,-2.74\nBECN1,-2.43\nULK1,-2.10'
    const result = parseGenes(input)
    expect(result.every(g => g.symbol)).toBe(true)
  })
})
