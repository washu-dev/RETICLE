/**
 * screenSignals.test.js
 * Unit tests for deriveScreenSignals / directionLabel.
 */
import { deriveScreenSignals, directionLabel } from './screenSignals.js';

describe('deriveScreenSignals — ORCS (human, hit flags)', () => {
  const detected = {
    format: 'ORCS',
    columns: ['SCREEN_ID', 'OFFICIAL_SYMBOL', 'ORGANISM_OFFICIAL', 'SCORE.1', 'HIT'],
    hitColumn: 'HIT',
  };
  const genes = [
    { symbol: 'POLR2L', score: -1.98, isHit: true,  extra: { ORGANISM_OFFICIAL: 'Homo sapiens' } },
    { symbol: 'PSMB3',  score: -1.89, isHit: true,  extra: { ORGANISM_OFFICIAL: 'Homo sapiens' } },
    { symbol: 'PUF60',  score: -1.80, isHit: false, extra: { ORGANISM_OFFICIAL: 'Homo sapiens' } },
    { symbol: 'SARS',   score: -1.80, isHit: false, extra: { ORGANISM_OFFICIAL: 'Homo sapiens' } },
    { symbol: 'SNRPD1', score: -1.78, isHit: true,  extra: { ORGANISM_OFFICIAL: 'Homo sapiens' } },
  ];

  test('detects human organism', () => {
    expect(deriveScreenSignals(detected, genes).organism).toBe('Human');
  });

  test('coverage FULL when a mix of hit/non-hit rows present', () => {
    const sig = deriveScreenSignals(detected, genes);
    expect(sig.coverageAvailability).toBe('FULL');
    expect(sig.hitCount).toBe(3);
  });

  test('coverage HITS_ONLY when every row is a hit', () => {
    const allHits = genes.map(g => ({ ...g, isHit: true }));
    expect(deriveScreenSignals(detected, allHits).coverageAvailability).toBe('HITS_ONLY');
  });
});

describe('deriveScreenSignals — RESIDUAL (mouse, bidirectional)', () => {
  const detected = {
    format: 'RESIDUAL',
    columns: ['Gene', 'condition', 'mean_lfc', 'z_score', 'ascending_rank', 'descending_rank'],
  };
  const genes = [
    { symbol: 'Ifngr2', score: 5.88,  extra: { condition: 'GammaTNF' } },
    { symbol: 'Ifngr1', score: 5.12,  extra: { condition: 'GammaTNF' } },
    { symbol: 'Fip1l1', score: 4.39,  extra: { condition: 'GammaTNF' } },
    { symbol: 'Rela',   score: -3.10, extra: { condition: 'GammaTNF' } },
    { symbol: 'Adam17', score: -2.90, extra: { condition: 'GammaTNF' } },
  ];

  test('direction is bidirectional when ascending+descending ranks present', () => {
    expect(deriveScreenSignals(detected, genes).direction).toBe('bidirectional');
  });

  test('condition is read from extra', () => {
    expect(deriveScreenSignals(detected, genes).condition).toBe('GammaTNF');
  });

  test('geneCount reflects parsed rows', () => {
    expect(deriveScreenSignals(detected, genes).geneCount).toBe(5);
  });
});

describe('directionLabel', () => {
  test('maps known directions to plain language', () => {
    expect(directionLabel('bidirectional')).toMatch(/resistance/);
    expect(directionLabel('depletion')).toMatch(/dropout/);
    expect(directionLabel(null)).toMatch(/not detected/);
  });
});
