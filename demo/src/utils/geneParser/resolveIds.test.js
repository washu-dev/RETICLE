/**
 * resolveIds.test.js
 * Unit tests for the resolveIdentifiers pure function.
 */
import { resolveIdentifiers } from './resolveIds.js';

// ---------------------------------------------------------------------------
// Minimal crosswalk fixture (mirrors crosswalk.min.json subset)
// ---------------------------------------------------------------------------
const crosswalk = {
  entrez: {
    '9474':   'ATG5',
    '10533':  'ATG7',
    '8408':   'ULK1',
    '345611': 'IRGM',
    '29110':  'TBK1',
  },
  ensembl: {
    'ENSG00000057663': 'ATG5',
    'ENSG00000197548': 'ATG7',
    'ENSG00000177169': 'ULK1',
  },
  ortholog: {
    'Atg5':  'ATG5',
    'Atg7':  'ATG7',
    'Ulk1':  'ULK1',
    'Irgm1': 'IRGM',
    'Becn1': 'BECN1',
  },
};

function makeGene(rawId, score = 0) {
  return { symbol: rawId, score, rawId };
}

// ---------------------------------------------------------------------------
// HGNC passthrough (Human, symbol already correct)
// ---------------------------------------------------------------------------
describe('resolveIdentifiers — HGNC passthrough', () => {
  test('HGNC symbol passes through unchanged for Human organism', () => {
    const genes = [makeGene('ATG5', -3.21)];
    const { genes: out, resolved, unmapped } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(out[0].symbol).toBe('ATG5');
    expect(resolved).toBe(0);      // no crosswalk lookup was needed
    expect(unmapped).toHaveLength(0);
  });

  test('multiple HGNC symbols all pass through', () => {
    const genes = [makeGene('ATG5'), makeGene('ATG7'), makeGene('ULK1')];
    const { genes: out } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(out.map(g => g.symbol)).toEqual(['ATG5', 'ATG7', 'ULK1']);
  });

  test('score is preserved on passthrough', () => {
    const genes = [makeGene('ATG5', -3.21)];
    const { genes: out } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(out[0].score).toBeCloseTo(-3.21);
  });
});

// ---------------------------------------------------------------------------
// Entrez ID resolution
// ---------------------------------------------------------------------------
describe('resolveIdentifiers — Entrez ID', () => {
  test('numeric Entrez ID resolves to HGNC symbol', () => {
    const genes = [makeGene('9474')];   // ATG5
    const { genes: out, resolved } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(out[0].symbol).toBe('ATG5');
    expect(resolved).toBe(1);
  });

  test('multiple Entrez IDs all resolve', () => {
    const genes = [makeGene('9474'), makeGene('10533'), makeGene('8408')];
    const { genes: out, resolved } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(out[0].symbol).toBe('ATG5');
    expect(out[1].symbol).toBe('ATG7');
    expect(out[2].symbol).toBe('ULK1');
    expect(resolved).toBe(3);
  });

  test('unknown Entrez ID goes into unmapped', () => {
    const genes = [makeGene('99999999')];
    const { unmapped, warnings } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(unmapped).toHaveLength(1);
    expect(unmapped[0].rawId).toBe('99999999');
    expect(warnings.length).toBeGreaterThan(0);
  });

  test('rawId is preserved even after Entrez resolution', () => {
    const genes = [makeGene('9474', -1.5)];
    const { genes: out } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(out[0].rawId).toBe('9474');
  });
});

// ---------------------------------------------------------------------------
// Ensembl ID resolution
// ---------------------------------------------------------------------------
describe('resolveIdentifiers — Ensembl ID', () => {
  test('Ensembl ID resolves to HGNC symbol', () => {
    const genes = [makeGene('ENSG00000057663')];  // ATG5
    const { genes: out, resolved } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(out[0].symbol).toBe('ATG5');
    expect(resolved).toBe(1);
  });

  test('Ensembl ID with version suffix strips the version', () => {
    const genes = [makeGene('ENSG00000057663.12')];
    const { genes: out, resolved } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(out[0].symbol).toBe('ATG5');
    expect(resolved).toBe(1);
  });

  test('unknown Ensembl ID goes into unmapped', () => {
    const genes = [makeGene('ENSG00000000000')];
    const { unmapped } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(unmapped).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Mouse ortholog resolution
// ---------------------------------------------------------------------------
describe('resolveIdentifiers — Mouse ortholog', () => {
  test('mouse symbol maps to human ortholog', () => {
    const genes = [makeGene('Atg5')];
    const { genes: out, resolved } = resolveIdentifiers(genes, 'Mouse', crosswalk);
    expect(out[0].symbol).toBe('ATG5');
    expect(resolved).toBe(1);
  });

  test('multiple mouse symbols resolved', () => {
    const genes = [makeGene('Atg5'), makeGene('Atg7'), makeGene('Becn1')];
    const { genes: out, resolved } = resolveIdentifiers(genes, 'Mouse', crosswalk);
    expect(out[0].symbol).toBe('ATG5');
    expect(out[1].symbol).toBe('ATG7');
    expect(out[2].symbol).toBe('BECN1');
    expect(resolved).toBe(3);
  });

  test('mouse symbol with no ortholog goes into unmapped', () => {
    const genes = [makeGene('Xyz999NoOrtholog')];
    const { unmapped } = resolveIdentifiers(genes, 'Mouse', crosswalk);
    expect(unmapped).toHaveLength(1);
    expect(unmapped[0].rawId).toBe('Xyz999NoOrtholog');
  });

  test('no-ortholog mouse gene is still returned (passed through uppercased)', () => {
    const genes = [makeGene('Xyz999NoOrtholog')];
    const { genes: out } = resolveIdentifiers(genes, 'Mouse', crosswalk);
    // Gene still present in output despite being unmapped
    expect(out).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Missing crosswalk
// ---------------------------------------------------------------------------
describe('resolveIdentifiers — missing crosswalk', () => {
  test('null crosswalk returns genes unchanged with a warning', () => {
    const genes = [makeGene('ATG5')];
    const { genes: out, resolved, warnings } = resolveIdentifiers(genes, 'Human', null);
    expect(out[0].symbol).toBe('ATG5');
    expect(resolved).toBe(0);
    expect(warnings.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Mixed batch
// ---------------------------------------------------------------------------
describe('resolveIdentifiers — mixed batch', () => {
  test('correctly processes a mixed batch of HGNC, Entrez, and Ensembl IDs', () => {
    const genes = [
      makeGene('ATG5',            -3.21),  // HGNC passthrough
      makeGene('9474',            -2.98),  // Entrez → ATG5
      makeGene('ENSG00000197548', -2.74),  // Ensembl → ATG7
    ];
    const { genes: out, resolved } = resolveIdentifiers(genes, 'Human', crosswalk);
    expect(out[0].symbol).toBe('ATG5');
    expect(out[1].symbol).toBe('ATG5');
    expect(out[2].symbol).toBe('ATG7');
    expect(resolved).toBe(2);  // Entrez + Ensembl resolved; HGNC passed through (not counted)
  });
});
