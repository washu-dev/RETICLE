/**
 * parseGeneList.test.js
 * Unit tests for the parseGeneList pure function.
 */
import { parseGeneList } from './parseGeneList.js';

// ---------------------------------------------------------------------------
// Helpers — representative file snippets
// ---------------------------------------------------------------------------

// Minimal MAGeCK gene_summary (3 data rows)
const MAGECK_RAW_SMALL = `id\tnum\tneg|score\tneg|p-value\tneg|fdr\tneg|rank\tneg|goodsgrna\tneg|lfc\tpos|score\tpos|p-value\tpos|fdr\tpos|rank\tpos|goodsgrna\tpos|lfc
ATG5\t4\t8.4e-11\t1.8e-05\t3.3e-04\t1\t4\t-2.31\t0.99\t0.82\t0.97\t523\t0\t0.17
ATG7\t4\t1.2e-09\t4.5e-05\t5.1e-04\t2\t4\t-1.98\t0.98\t0.79\t0.96\t501\t0\t0.14
ULK1\t3\t3.7e-08\t9.1e-05\t8.2e-04\t3\t3\t-1.75\t0.97\t0.77\t0.95\t489\t0\t0.12`;

// MAGeCK with 7 data rows (>= MIN_GENES=5)
const MAGECK_RAW = `id\tnum\tneg|score\tneg|p-value\tneg|fdr\tneg|rank\tneg|goodsgrna\tneg|lfc\tpos|score\tpos|lfc
ATG5\t4\t8.4e-11\t1.8e-05\t3.3e-04\t1\t4\t-2.31\t0.99\t0.17
ATG7\t4\t1.2e-09\t4.5e-05\t5.1e-04\t2\t4\t-1.98\t0.98\t0.14
ULK1\t3\t3.7e-08\t9.1e-05\t8.2e-04\t3\t3\t-1.75\t0.97\t0.12
IRGM\t3\t2.1e-07\t1.2e-04\t9.3e-04\t4\t3\t-1.62\t0.96\t0.09
BECN1\t2\t5.4e-07\t2.3e-04\t1.1e-03\t5\t2\t-1.44\t0.95\t0.07
PIK3C3\t2\t9.8e-07\t3.5e-04\t1.3e-03\t6\t2\t-1.31\t0.94\t0.05
ATG14\t2\t1.7e-06\t4.8e-04\t1.5e-03\t7\t2\t-1.18\t0.93\t0.04`;

// STARS with 6 rows
const STARS_RAW = `Gene\tq-value\tp-value\tLFC\tRank
ATG5\t0.0001\t0.00001\t-2.31\t1
ATG7\t0.0003\t0.00005\t-1.98\t2
ULK1\t0.0007\t0.0001\t-1.75\t3
IRGM\t0.0012\t0.0002\t-1.62\t4
BECN1\t0.0025\t0.0004\t-1.44\t5
PIK3C3\t0.0041\t0.0007\t-1.31\t6`;

// DESeq2 with 6 rows
const DESEQ2_RAW = `gene\tbaseMean\tlog2FoldChange\tlfcSE\tstat\tpvalue\tpadj
ATG5\t234.5\t-2.31\t0.45\t-5.13\t2.8e-07\t1.1e-05
ATG7\t312.1\t-1.98\t0.41\t-4.83\t1.3e-06\t3.2e-05
ULK1\t189.7\t-1.75\t0.39\t-4.49\t7.1e-06\t1.1e-04
IRGM\t88.4\t-1.62\t0.38\t-4.26\t2.1e-05\t2.4e-04
BECN1\t421.3\t-1.44\t0.35\t-4.11\t3.9e-05\t3.8e-04
PIK3C3\t167.9\t-1.31\t0.33\t-3.97\t7.2e-05\t6.1e-04`;

// EXAMPLE_GENE_LIST from mockData.js (copied verbatim)
const EXAMPLE_GENE_LIST = `gene_symbol,score
ATG5,-3.21
ATG7,-2.98
ULK1,-2.74
IRGM,-2.61
BECN1,-2.43
PIK3C3,-2.31
ATG14,-2.18
RUBCN,-2.05
ATG16L1,-1.94
MAP1LC3B,-1.82
SQSTM1,-1.71
CCDC6,-1.63
FAM114A1,-1.55
ZSWIM8,-1.44
C1orf43,-1.38
ANKRD36C,-1.27
TMEM106B,-1.19
VAMP8,-1.11
STK38L,-1.04
BNIP3L,-0.97
RAB7A,-0.89
TBK1,1.22
MTOR,1.44
AKT1,1.67
RPTOR,1.89`;

// ---------------------------------------------------------------------------
// MAGeCK parsing
// ---------------------------------------------------------------------------
describe('parseGeneList — MAGeCK', () => {
  const opts = {
    format: 'MAGECK',
    delimiter: '\t',
    idColumn: 'id',
    scoreColumn: 'neg|lfc',
  };

  test('parses 7 genes from MAGeCK raw', () => {
    const { genes } = parseGeneList(MAGECK_RAW, opts);
    expect(genes).toHaveLength(7);
  });

  test('first gene has correct symbol and score', () => {
    const { genes } = parseGeneList(MAGECK_RAW, opts);
    expect(genes[0].symbol).toBe('ATG5');
    expect(genes[0].score).toBeCloseTo(-2.31);
  });

  test('each gene has symbol, score, rawId', () => {
    const { genes } = parseGeneList(MAGECK_RAW, opts);
    genes.forEach(g => {
      expect(g).toHaveProperty('symbol');
      expect(g).toHaveProperty('score');
      expect(g).toHaveProperty('rawId');
      expect(typeof g.score).toBe('number');
    });
  });

  test('extra fields captured (num, neg|score, pos|score etc.)', () => {
    const { genes } = parseGeneList(MAGECK_RAW, opts);
    expect(genes[0]).toHaveProperty('extra');
  });

  test('no warnings when valid MAGeCK with >=5 genes', () => {
    const { warnings } = parseGeneList(MAGECK_RAW, opts);
    expect(warnings).toHaveLength(0);
  });

  test('fewer than 5 genes returns warning and empty genes array (MAGECK_RAW_SMALL has 3 rows)', () => {
    const { genes, warnings } = parseGeneList(MAGECK_RAW_SMALL, opts);
    expect(genes).toHaveLength(0);
    expect(warnings.some(w => w.toLowerCase().includes('at least'))).toBe(true);
  });

  test('switching scoreColumn to pos|lfc gives correct scores', () => {
    const optsPos = { ...opts, scoreColumn: 'pos|lfc' };
    const { genes } = parseGeneList(MAGECK_RAW, optsPos);
    expect(genes[0].score).toBeCloseTo(0.17);
  });
});

// ---------------------------------------------------------------------------
// STARS parsing
// ---------------------------------------------------------------------------
describe('parseGeneList — STARS', () => {
  const opts = {
    format: 'STARS',
    delimiter: '\t',
    idColumn: 'Gene',
    scoreColumn: 'LFC',
  };

  test('parses 6 genes from STARS raw', () => {
    const { genes } = parseGeneList(STARS_RAW, opts);
    expect(genes).toHaveLength(6);
  });

  test('gene symbols are correct', () => {
    const { genes } = parseGeneList(STARS_RAW, opts);
    expect(genes.map(g => g.symbol)).toEqual(['ATG5', 'ATG7', 'ULK1', 'IRGM', 'BECN1', 'PIK3C3']);
  });

  test('LFC scores are parsed as numbers', () => {
    const { genes } = parseGeneList(STARS_RAW, opts);
    expect(genes[0].score).toBeCloseTo(-2.31);
    expect(genes[5].score).toBeCloseTo(-1.31);
  });
});

// ---------------------------------------------------------------------------
// DESeq2 parsing
// ---------------------------------------------------------------------------
describe('parseGeneList — DESeq2', () => {
  const opts = {
    format: 'DESEQ2',
    delimiter: '\t',
    idColumn: 'gene',
    scoreColumn: 'log2FoldChange',
  };

  test('parses 6 genes from DESeq2 raw', () => {
    const { genes } = parseGeneList(DESEQ2_RAW, opts);
    expect(genes).toHaveLength(6);
  });

  test('log2FoldChange values are parsed correctly', () => {
    const { genes } = parseGeneList(DESEQ2_RAW, opts);
    expect(genes[0].score).toBeCloseTo(-2.31);
  });
});

// ---------------------------------------------------------------------------
// SIMPLE regression — EXAMPLE_GENE_LIST
// ---------------------------------------------------------------------------
describe('parseGeneList — SIMPLE (EXAMPLE_GENE_LIST regression)', () => {
  const opts = {
    format: 'SIMPLE',
    delimiter: ',',
    idColumn: 'gene_symbol',
    scoreColumn: 'score',
  };

  test('parses all 25 genes from EXAMPLE_GENE_LIST', () => {
    const { genes } = parseGeneList(EXAMPLE_GENE_LIST, opts);
    expect(genes).toHaveLength(25);
  });

  test('gene symbols match expected order', () => {
    const { genes } = parseGeneList(EXAMPLE_GENE_LIST, opts);
    const symbols = genes.map(g => g.symbol);
    expect(symbols[0]).toBe('ATG5');
    expect(symbols[24]).toBe('RPTOR');
  });

  test('scores parsed correctly including negative and positive', () => {
    const { genes } = parseGeneList(EXAMPLE_GENE_LIST, opts);
    expect(genes[0].score).toBeCloseTo(-3.21);
    expect(genes[21].score).toBeCloseTo(1.22);  // TBK1
    expect(genes[24].score).toBeCloseTo(1.89);  // RPTOR
  });

  test('no warnings on full example list', () => {
    const { warnings } = parseGeneList(EXAMPLE_GENE_LIST, opts);
    expect(warnings).toHaveLength(0);
  });

  test('rawId equals symbol for SIMPLE format passthrough', () => {
    const { genes } = parseGeneList(EXAMPLE_GENE_LIST, opts);
    genes.forEach(g => {
      expect(g.rawId).toBe(g.symbol);
    });
  });
});

// ---------------------------------------------------------------------------
// Fewer-than-5 genes warning
// ---------------------------------------------------------------------------
describe('parseGeneList — fewer than 5 genes warning', () => {
  const opts = {
    format: 'SIMPLE',
    delimiter: ',',
    idColumn: 'gene_symbol',
    scoreColumn: 'score',
  };

  test('returns warning and empty array when only 3 genes given', () => {
    const short = `gene_symbol,score\nATG5,-3.21\nATG7,-2.98\nULK1,-2.74`;
    const { genes, warnings } = parseGeneList(short, opts);
    expect(genes).toHaveLength(0);
    expect(warnings.some(w => w.toLowerCase().includes('at least'))).toBe(true);
  });

  test('returns warning and empty array when 4 genes given', () => {
    const four = `gene_symbol,score\nATG5,-3.21\nATG7,-2.98\nULK1,-2.74\nIRGM,-2.61`;
    const { genes, warnings } = parseGeneList(four, opts);
    expect(genes).toHaveLength(0);
    expect(warnings.length).toBeGreaterThan(0);
  });

  test('exactly 5 genes passes without that warning', () => {
    const five = `gene_symbol,score\nATG5,-3.21\nATG7,-2.98\nULK1,-2.74\nIRGM,-2.61\nBECN1,-2.43`;
    const { genes, warnings } = parseGeneList(five, opts);
    expect(genes).toHaveLength(5);
    expect(warnings.some(w => w.toLowerCase().includes('at least'))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Empty input warning
// ---------------------------------------------------------------------------
describe('parseGeneList — empty input', () => {
  const opts = {
    format: 'SIMPLE',
    delimiter: ',',
    idColumn: 'gene_symbol',
    scoreColumn: 'score',
  };

  test('empty string returns warning', () => {
    const { genes, warnings } = parseGeneList('', opts);
    expect(genes).toHaveLength(0);
    expect(warnings.length).toBeGreaterThan(0);
  });

  test('whitespace-only returns warning', () => {
    const { genes, warnings } = parseGeneList('   \n\n  ', opts);
    expect(genes).toHaveLength(0);
    expect(warnings.length).toBeGreaterThan(0);
  });

  test('header-only (no data rows) returns warning', () => {
    const headerOnly = 'gene_symbol,score';
    const { genes, warnings } = parseGeneList(headerOnly, opts);
    expect(genes).toHaveLength(0);
    expect(warnings.length).toBeGreaterThan(0);
  });
});
