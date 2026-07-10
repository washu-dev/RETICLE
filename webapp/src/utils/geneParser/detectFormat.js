/**
 * detectFormat.js
 * Pure function — no side effects, no network calls.
 * Inspects the raw text of an uploaded gene list and returns
 * a best-guess format descriptor.
 */

// Threshold: how many header tokens have to match for us to be confident?
const CONFIDENCE_HIGH = 0.9;
const CONFIDENCE_MED  = 0.6;
const CONFIDENCE_LOW  = 0.3;

/**
 * Detect the delimiter used in a raw text (tab or comma).
 * Returns '\t' when the first non-blank line has more tabs than commas,
 * otherwise ','.
 * @param {string} firstLine
 * @returns {'\t'|','}
 */
function sniffDelimiter(firstLine) {
  const tabs   = (firstLine.match(/\t/g)  || []).length;
  const commas = (firstLine.match(/,/g)   || []).length;
  return tabs >= commas ? '\t' : ',';
}

/**
 * Split a header line into column names, trimming whitespace and quotes.
 * @param {string} line
 * @param {'\t'|','} delimiter
 * @returns {string[]}
 */
function splitHeader(line, delimiter) {
  return line.split(delimiter).map(c => c.trim().replace(/^["']|["']$/g, ''));
}

/**
 * detectFormat — inspect raw text and return a format descriptor.
 *
 * @param {string} raw  Raw file/paste content
 * @returns {{
 *   format: 'MAGECK'|'STARS'|'DESEQ2'|'SIMPLE'|'UNKNOWN',
 *   delimiter: '\t'|',',
 *   columns: string[],
 *   idColumn: string,
 *   confidence: number
 * }}
 */
export function detectFormat(raw) {
  const lines = raw.trim().split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length === 0) {
    return { format: 'UNKNOWN', delimiter: '\t', columns: [], idColumn: '', confidence: 0 };
  }

  const firstLine = lines[0];
  const delimiter = sniffDelimiter(firstLine);
  const columns   = splitHeader(firstLine, delimiter);
  const colLower  = columns.map(c => c.toLowerCase());

  // ---- MAGeCK detection ----
  // MAGeCK output has an "id" column and columns containing pipe characters
  // e.g. "id", "num", "neg|score", "neg|p-value", "neg|fdr", "neg|rank", "neg|goodsgrna", "neg|lfc", "pos|score", ...
  const hasPipeCol    = columns.some(c => c.includes('|'));
  const hasIdCol      = colLower.includes('id');
  if (hasPipeCol && hasIdCol) {
    return {
      format: 'MAGECK',
      delimiter,
      columns,
      idColumn: columns[colLower.indexOf('id')],
      confidence: CONFIDENCE_HIGH,
    };
  }
  // Also accept MAGeCK if there is a pipe column but no strict "id" — pick first column
  if (hasPipeCol) {
    return {
      format: 'MAGECK',
      delimiter,
      columns,
      idColumn: columns[0],
      confidence: CONFIDENCE_MED,
    };
  }

  // ---- STARS detection ----
  // STARS output has columns: Gene, q-value, p-value, LFC, Rank (case-sensitive in the tool but we check case-insensitively)
  const starsRequired = ['gene', 'q-value', 'p-value', 'lfc', 'rank'];
  const starsMatches  = starsRequired.filter(r => colLower.includes(r)).length;
  if (starsMatches >= 3) {
    const geneIdx = colLower.indexOf('gene');
    return {
      format: 'STARS',
      delimiter,
      columns,
      idColumn: geneIdx >= 0 ? columns[geneIdx] : columns[0],
      confidence: starsMatches === starsRequired.length ? CONFIDENCE_HIGH : CONFIDENCE_MED,
    };
  }

  // ---- DESeq2 detection ----
  // DESeq2 output (results() table): baseMean, log2FoldChange, lfcSE, stat, pvalue, padj
  // Row names are gene IDs. When exported to CSV the first column is often unnamed or "gene".
  const deseqRequired = ['basemean', 'log2foldchange', 'padj'];
  const deseqOptional = ['lfcse', 'stat', 'pvalue'];
  const deseqReqMatches = deseqRequired.filter(r => colLower.includes(r)).length;
  const deseqOptMatches = deseqOptional.filter(r => colLower.includes(r)).length;
  if (deseqReqMatches >= 2) {
    // First column or a column named "gene" / "" is the ID
    const geneIdx = colLower.findIndex(c => c === 'gene' || c === '' || c === 'geneid' || c === 'gene_id');
    const idColumn = geneIdx >= 0 ? columns[geneIdx] : columns[0];
    const confidence = deseqReqMatches === 3
      ? (deseqOptMatches >= 1 ? CONFIDENCE_HIGH : CONFIDENCE_MED)
      : CONFIDENCE_LOW;
    return { format: 'DESEQ2', delimiter, columns, idColumn, confidence };
  }

  // ---- SIMPLE detection ----
  // 2-column (or 1-column) CSV/TSV with gene_symbol [, score]
  // Header line starts with gene/symbol/name and optional score column.
  const simpleIdTerms   = ['gene', 'symbol', 'gene_symbol', 'name', 'genename', 'gene_name', 'id'];
  const simpleScoreTerms = ['score', 'lfc', 'log2fc', 'log2foldchange', 'fc', 'rank', 'pvalue', 'fdr', 'value'];
  const col0Lower = colLower[0] || '';
  const col1Lower = colLower[1] || '';
  const col0IsId    = simpleIdTerms.some(t => col0Lower.includes(t));
  const col1IsScore = col1Lower ? simpleScoreTerms.some(t => col1Lower.includes(t)) : false;

  if (columns.length <= 3 && (col0IsId || columns.length === 1)) {
    return {
      format: 'SIMPLE',
      delimiter,
      columns,
      idColumn: columns[0],
      confidence: (col0IsId && col1IsScore) ? CONFIDENCE_HIGH : CONFIDENCE_MED,
    };
  }

  // ---- Heuristic fallback: if <=3 columns and data rows look like "WORD, number" ----
  if (columns.length <= 3 && lines.length >= 2) {
    const dataLine = lines[1];
    const parts    = dataLine.split(delimiter);
    const looksLikeGeneScore = parts.length >= 1 && /^[A-Za-z]/.test(parts[0].trim()) &&
      (parts.length === 1 || !isNaN(parseFloat(parts[1])));
    if (looksLikeGeneScore) {
      return {
        format: 'SIMPLE',
        delimiter,
        columns,
        idColumn: columns[0],
        confidence: CONFIDENCE_LOW,
      };
    }
  }

  return { format: 'UNKNOWN', delimiter, columns, idColumn: columns[0] || '', confidence: 0 };
}
