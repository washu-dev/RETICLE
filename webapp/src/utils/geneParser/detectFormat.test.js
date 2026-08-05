/**
 * detectFormat.test.js
 * Unit tests for the detectFormat pure function.
 */
import { detectFormat } from './detectFormat.js';

// ---------------------------------------------------------------------------
// MAGeCK
// ---------------------------------------------------------------------------
describe('detectFormat — MAGeCK', () => {
  const MAGECK_HEADER =
    'id\tnum\tneg|score\tneg|p-value\tneg|fdr\tneg|rank\tneg|goodsgrna\tneg|lfc\tpos|score\tpos|p-value\tpos|fdr\tpos|rank\tpos|goodsgrna\tpos|lfc';

  const MAGECK_RAW = `${MAGECK_HEADER}
ATG5\t4\t8.4e-11\t1.8e-05\t3.3e-04\t1\t4\t-2.31\t0.99\t0.82\t0.97\t523\t0\t0.17`;

  test('returns MAGECK format for canonical header with id column', () => {
    const result = detectFormat(MAGECK_RAW);
    expect(result.format).toBe('MAGECK');
  });

  test('confidence is HIGH (>=0.9) when id column present', () => {
    const result = detectFormat(MAGECK_RAW);
    expect(result.confidence).toBeGreaterThanOrEqual(0.9);
  });

  test('idColumn is "id"', () => {
    const result = detectFormat(MAGECK_RAW);
    expect(result.idColumn.toLowerCase()).toBe('id');
  });

  test('delimiter is tab', () => {
    const result = detectFormat(MAGECK_RAW);
    expect(result.delimiter).toBe('\t');
  });

  test('returns MAGECK (medium confidence) even without "id" column if pipe cols present', () => {
    const noid = 'gene\tneg|score\tneg|lfc\tpos|score\tpos|lfc\nATG5\t0.1\t-2.3\t0.9\t0.2';
    const result = detectFormat(noid);
    expect(result.format).toBe('MAGECK');
    expect(result.confidence).toBeGreaterThanOrEqual(0.5);
  });

  test('columns array includes all header tokens', () => {
    const result = detectFormat(MAGECK_RAW);
    expect(result.columns).toContain('neg|lfc');
    expect(result.columns).toContain('pos|lfc');
  });
});

// ---------------------------------------------------------------------------
// STARS
// ---------------------------------------------------------------------------
describe('detectFormat — STARS', () => {
  const STARS_RAW = `Gene\tq-value\tp-value\tLFC\tRank
ATG5\t0.0001\t0.00001\t-2.31\t1`;

  test('returns STARS format', () => {
    const result = detectFormat(STARS_RAW);
    expect(result.format).toBe('STARS');
  });

  test('confidence is HIGH when all required STARS columns present', () => {
    const result = detectFormat(STARS_RAW);
    expect(result.confidence).toBeGreaterThanOrEqual(0.9);
  });

  test('idColumn is "Gene"', () => {
    const result = detectFormat(STARS_RAW);
    expect(result.idColumn).toBe('Gene');
  });

  test('partial STARS header (3 matching cols) still detected as STARS with medium confidence', () => {
    const partial = `Gene\tq-value\tLFC\nsomegene\t0.01\t1.5`;
    const result = detectFormat(partial);
    expect(result.format).toBe('STARS');
    expect(result.confidence).toBeLessThan(0.9);
  });
});

// ---------------------------------------------------------------------------
// DESeq2
// ---------------------------------------------------------------------------
describe('detectFormat — DESeq2', () => {
  const DESEQ2_RAW = `gene\tbaseMean\tlog2FoldChange\tlfcSE\tstat\tpvalue\tpadj
ATG5\t234.5\t-2.31\t0.45\t-5.13\t2.8e-07\t1.1e-05`;

  test('returns DESEQ2 format', () => {
    const result = detectFormat(DESEQ2_RAW);
    expect(result.format).toBe('DESEQ2');
  });

  test('confidence is HIGH when all three required cols + optional cols present', () => {
    const result = detectFormat(DESEQ2_RAW);
    expect(result.confidence).toBeGreaterThanOrEqual(0.9);
  });

  test('idColumn is the gene column', () => {
    const result = detectFormat(DESEQ2_RAW);
    expect(result.idColumn.toLowerCase()).toBe('gene');
  });

  test('detects DESeq2 with unnamed first column (row-name export style)', () => {
    const unnamed = `\tbaseMean\tlog2FoldChange\tpadj
ATG5\t234.5\t-2.31\t1.1e-05`;
    const result = detectFormat(unnamed);
    expect(result.format).toBe('DESEQ2');
  });
});

// ---------------------------------------------------------------------------
// ORCS — BioGRID native .screen.tab.txt (real sample shape)
// ---------------------------------------------------------------------------
describe('detectFormat — BioGRID ORCS', () => {
  const ORCS_RAW = `#SCREEN_ID\tIDENTIFIER_ID\tIDENTIFIER_TYPE\tOFFICIAL_SYMBOL\tALIASES\tORGANISM_ID\tORGANISM_OFFICIAL\tSCORE.1\tSCORE.2\tSCORE.3\tSCORE.4\tSCORE.5\tHIT\tSOURCE
381\t5441\tENTREZ_GENE\tPOLR2L\tRBP10|RPABC5\t9606\tHomo sapiens\t-1.98680010698\t0.0\t-\t-\t-\tYES\tBioGRID ORCS
381\t5691\tENTREZ_GENE\tPSMB3\tHC10-II\t9606\tHomo sapiens\t-1.89612473832\t0.0\t-\t-\t-\tYES\tBioGRID ORCS`;

  test('returns ORCS format for #-prefixed BioGRID header', () => {
    expect(detectFormat(ORCS_RAW).format).toBe('ORCS');
  });

  test('idColumn is OFFICIAL_SYMBOL', () => {
    expect(detectFormat(ORCS_RAW).idColumn).toBe('OFFICIAL_SYMBOL');
  });

  test('hitColumn is HIT', () => {
    expect(detectFormat(ORCS_RAW).hitColumn).toBe('HIT');
  });

  test('delimiter is tab and confidence is HIGH', () => {
    const r = detectFormat(ORCS_RAW);
    expect(r.delimiter).toBe('\t');
    expect(r.confidence).toBeGreaterThanOrEqual(0.9);
  });

  test('columns strip the leading # from the first token', () => {
    expect(detectFormat(ORCS_RAW).columns[0]).toBe('SCREEN_ID');
  });
});

// ---------------------------------------------------------------------------
// RESIDUAL — z-score / residual-model screen (zs_GammaTNF_vs_DMSO.csv shape)
// ---------------------------------------------------------------------------
describe('detectFormat — RESIDUAL', () => {
  const RESIDUAL_RAW = `Gene,condition,n,mean_lfc,mean_residual,pop_mean,pop_sd,z_score,p_value,fdr,ascending_rank,descending_rank
Ifngr2,GammaTNF,4,0.9467,0.7070,1.5e-14,0.2402,5.8855,3.9e-9,5.9e-6,22629,1
Ifngr1,GammaTNF,4,0.3598,0.6157,1.5e-14,0.2402,5.1253,2.9e-7,2.6e-4,22628,2`;

  test('returns RESIDUAL format', () => {
    expect(detectFormat(RESIDUAL_RAW).format).toBe('RESIDUAL');
  });

  test('idColumn is Gene, delimiter is comma', () => {
    const r = detectFormat(RESIDUAL_RAW);
    expect(r.idColumn).toBe('Gene');
    expect(r.delimiter).toBe(',');
  });

  test('conditionColumn is condition', () => {
    expect(detectFormat(RESIDUAL_RAW).conditionColumn).toBe('condition');
  });

  test('confidence HIGH when both z_score and mean_residual present', () => {
    expect(detectFormat(RESIDUAL_RAW).confidence).toBeGreaterThanOrEqual(0.9);
  });
});

// ---------------------------------------------------------------------------
// SIMPLE — CSV
// ---------------------------------------------------------------------------
describe('detectFormat — SIMPLE CSV', () => {
  const SIMPLE_CSV = `gene_symbol,score
ATG5,-3.21
ATG7,-2.98`;

  test('returns SIMPLE format for 2-column CSV with gene_symbol header', () => {
    const result = detectFormat(SIMPLE_CSV);
    expect(result.format).toBe('SIMPLE');
  });

  test('delimiter is comma', () => {
    const result = detectFormat(SIMPLE_CSV);
    expect(result.delimiter).toBe(',');
  });

  test('idColumn is first column', () => {
    const result = detectFormat(SIMPLE_CSV);
    expect(result.idColumn).toBe('gene_symbol');
  });
});

// ---------------------------------------------------------------------------
// SIMPLE — TSV
// ---------------------------------------------------------------------------
describe('detectFormat — SIMPLE TSV', () => {
  const SIMPLE_TSV = `gene\tscore
ATG5\t-3.21
ATG7\t-2.98`;

  test('returns SIMPLE format for 2-column TSV', () => {
    const result = detectFormat(SIMPLE_TSV);
    expect(result.format).toBe('SIMPLE');
  });

  test('delimiter is tab', () => {
    const result = detectFormat(SIMPLE_TSV);
    expect(result.delimiter).toBe('\t');
  });
});

// ---------------------------------------------------------------------------
// UNKNOWN / garbage
// ---------------------------------------------------------------------------
describe('detectFormat — UNKNOWN', () => {
  test('empty string returns UNKNOWN with confidence 0', () => {
    const result = detectFormat('');
    expect(result.format).toBe('UNKNOWN');
    expect(result.confidence).toBe(0);
  });

  test('whitespace-only input returns UNKNOWN', () => {
    const result = detectFormat('   \n  \n  ');
    expect(result.format).toBe('UNKNOWN');
    expect(result.confidence).toBe(0);
  });

  test('garbage multi-column header with no recognizable tokens returns UNKNOWN', () => {
    const garbage = `foo\tbar\tbaz\tqux\tquux\tcorge
1\t2\t3\t4\t5\t6`;
    const result = detectFormat(garbage);
    expect(result.format).toBe('UNKNOWN');
  });

  test('random text blob returns UNKNOWN or SIMPLE (low confidence), never MAGECK/STARS/DESEQ2', () => {
    const blob = `this is not a gene list at all\nsome random text here`;
    const result = detectFormat(blob);
    expect(['UNKNOWN', 'SIMPLE']).toContain(result.format);
    expect(['MAGECK', 'STARS', 'DESEQ2']).not.toContain(result.format);
  });
});
