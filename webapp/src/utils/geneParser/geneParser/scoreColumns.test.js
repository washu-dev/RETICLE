/**
 * scoreColumns.test.js
 * Unit tests for the suggestScoreColumn pure function.
 */
import { suggestScoreColumn } from './scoreColumns.js';

// ---------------------------------------------------------------------------
// MAGeCK
// ---------------------------------------------------------------------------
describe('suggestScoreColumn — MAGeCK', () => {
  const MAGECK_COLS = [
    'id', 'num', 'neg|score', 'neg|p-value', 'neg|fdr', 'neg|rank',
    'neg|goodsgrna', 'neg|lfc', 'pos|score', 'pos|p-value', 'pos|fdr',
    'pos|rank', 'pos|goodsgrna', 'pos|lfc',
  ];

  test('defaultColumn is "neg|lfc" for MAGeCK', () => {
    const { defaultColumn } = suggestScoreColumn(MAGECK_COLS, 'MAGECK');
    expect(defaultColumn).toBe('neg|lfc');
  });

  test('candidates include both lfc and score columns', () => {
    const { candidates } = suggestScoreColumn(MAGECK_COLS, 'MAGECK');
    const values = candidates.map(c => c.value);
    expect(values).toContain('neg|lfc');
    expect(values).toContain('neg|score');
    expect(values).toContain('pos|lfc');
    expect(values).toContain('pos|score');
  });

  test('each candidate has value and label properties', () => {
    const { candidates } = suggestScoreColumn(MAGECK_COLS, 'MAGECK');
    candidates.forEach(c => {
      expect(c).toHaveProperty('value');
      expect(c).toHaveProperty('label');
    });
  });

  test('neg|lfc appears before pos|lfc in candidates', () => {
    const { candidates } = suggestScoreColumn(MAGECK_COLS, 'MAGECK');
    const values = candidates.map(c => c.value);
    expect(values.indexOf('neg|lfc')).toBeLessThan(values.indexOf('pos|lfc'));
  });

  test('falls back to neg|score when neg|lfc absent', () => {
    const cols = ['id', 'num', 'neg|score', 'pos|score', 'pos|lfc'];
    const { defaultColumn } = suggestScoreColumn(cols, 'MAGECK');
    expect(defaultColumn).toBe('neg|score');
  });
});

// ---------------------------------------------------------------------------
// STARS
// ---------------------------------------------------------------------------
describe('suggestScoreColumn — STARS', () => {
  const STARS_COLS = ['Gene', 'q-value', 'p-value', 'LFC', 'Rank'];

  test('defaultColumn is "LFC" for STARS', () => {
    const { defaultColumn } = suggestScoreColumn(STARS_COLS, 'STARS');
    expect(defaultColumn).toBe('LFC');
  });

  test('candidates include q-value', () => {
    const { candidates } = suggestScoreColumn(STARS_COLS, 'STARS');
    const values = candidates.map(c => c.value);
    expect(values).toContain('q-value');
  });

  test('LFC comes before q-value in candidates', () => {
    const { candidates } = suggestScoreColumn(STARS_COLS, 'STARS');
    const values = candidates.map(c => c.value);
    expect(values.indexOf('LFC')).toBeLessThan(values.indexOf('q-value'));
  });
});

// ---------------------------------------------------------------------------
// DESeq2
// ---------------------------------------------------------------------------
describe('suggestScoreColumn — DESeq2', () => {
  const DESEQ2_COLS = ['gene', 'baseMean', 'log2FoldChange', 'lfcSE', 'stat', 'pvalue', 'padj'];

  test('defaultColumn is "log2FoldChange" for DESeq2', () => {
    const { defaultColumn } = suggestScoreColumn(DESEQ2_COLS, 'DESEQ2');
    expect(defaultColumn).toBe('log2FoldChange');
  });

  test('candidates include stat and padj', () => {
    const { candidates } = suggestScoreColumn(DESEQ2_COLS, 'DESEQ2');
    const values = candidates.map(c => c.value);
    expect(values).toContain('stat');
    expect(values).toContain('padj');
  });
});

// ---------------------------------------------------------------------------
// SIMPLE
// ---------------------------------------------------------------------------
describe('suggestScoreColumn — SIMPLE', () => {
  test('defaultColumn is the second column for SIMPLE format', () => {
    const cols = ['gene_symbol', 'score'];
    const { defaultColumn } = suggestScoreColumn(cols, 'SIMPLE');
    expect(defaultColumn).toBe('score');
  });

  test('single-column SIMPLE falls back to first column', () => {
    const cols = ['gene_symbol'];
    const { defaultColumn } = suggestScoreColumn(cols, 'SIMPLE');
    expect(defaultColumn).toBe('gene_symbol');
  });
});

// ---------------------------------------------------------------------------
// UNKNOWN
// ---------------------------------------------------------------------------
describe('suggestScoreColumn — UNKNOWN / edge cases', () => {
  test('empty columns returns empty defaultColumn and candidates', () => {
    const { defaultColumn, candidates } = suggestScoreColumn([], 'UNKNOWN');
    expect(defaultColumn).toBe('');
    expect(candidates).toEqual([]);
  });

  test('null columns returns empty defaultColumn and candidates', () => {
    const { defaultColumn, candidates } = suggestScoreColumn(null, 'UNKNOWN');
    expect(defaultColumn).toBe('');
    expect(candidates).toEqual([]);
  });

  test('UNKNOWN format: defaults to second column when available', () => {
    const cols = ['geneA', 'scoreA', 'extra'];
    const { defaultColumn } = suggestScoreColumn(cols, 'UNKNOWN');
    expect(defaultColumn).toBe('scoreA');
  });
});
