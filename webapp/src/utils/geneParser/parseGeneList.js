/**
 * parseGeneList.js
 * Pure function — no side effects, no network calls.
 * Parses raw file/paste content into a normalized array of gene objects.
 */

const MIN_GENES = 5;

/**
 * Split a line into fields, respecting the delimiter.
 * Trims whitespace and strips surrounding quotes from each field.
 *
 * @param {string} line
 * @param {'\t'|','} delimiter
 * @returns {string[]}
 */
function splitLine(line, delimiter) {
  return line.split(delimiter).map(f => f.trim().replace(/^["']|["']$/g, ''));
}

/**
 * Parse a numeric score from a string. Returns NaN if unparseable.
 * Handles values like "1.23e-4", "-2.5", "0.001".
 *
 * @param {string} raw
 * @returns {number}
 */
function parseScore(raw) {
  if (raw === undefined || raw === null || raw === '') return NaN;
  const n = parseFloat(raw);
  return n;
}

/**
 * parseGeneList — convert raw text into an array of normalized gene objects.
 *
 * @param {string} raw  Raw paste or file content
 * @param {{
 *   format: 'MAGECK'|'STARS'|'DESEQ2'|'SIMPLE'|'UNKNOWN',
 *   delimiter: '\t'|',',
 *   idColumn: string,
 *   scoreColumn: string
 * }} options
 * @returns {{
 *   genes: Array<{symbol: string, score: number, rawId?: string, extra?: Object}>,
 *   warnings: string[]
 * }}
 */
export function parseGeneList(raw, { delimiter, idColumn, scoreColumn }) {
  const warnings = [];
  const genes    = [];

  if (!raw || !raw.trim()) {
    warnings.push('No content to parse.');
    return { genes, warnings };
  }

  const lines = raw.trim().split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length === 0) {
    warnings.push('No content to parse.');
    return { genes, warnings };
  }

  // First line is always the header
  const headerLine = lines[0];
  const headers    = splitLine(headerLine, delimiter).map(h => h.toLowerCase());

  // Resolve column indices
  const idColLower    = (idColumn    || '').toLowerCase();
  const scoreColLower = (scoreColumn || '').toLowerCase();

  let idIdx    = headers.indexOf(idColLower);
  let scoreIdx = headers.indexOf(scoreColLower);

  // Fuzzy fallback for id column
  if (idIdx < 0) {
    idIdx = headers.findIndex(h => h === 'id' || h === 'gene' || h === 'symbol' || h === 'gene_symbol');
  }
  if (idIdx < 0) {
    idIdx = 0; // last resort
  }

  // Fuzzy fallback for score column using the original (non-lowered) headers for pipe cols
  const rawHeaders = splitLine(headerLine, delimiter);
  if (scoreIdx < 0 && scoreColumn) {
    scoreIdx = rawHeaders.findIndex(h => h === scoreColumn);
  }
  if (scoreIdx < 0) {
    scoreIdx = idIdx === 0 ? 1 : 0;
  }

  let emptyScoreCount = 0;
  let unparsedCount   = 0;

  const dataLines = lines.slice(1);
  for (const line of dataLines) {
    if (!line) continue;
    const fields = splitLine(line, delimiter);

    const rawId = fields[idIdx]?.trim() || '';
    if (!rawId) {
      unparsedCount++;
      continue;
    }

    const rawScore = fields[scoreIdx]?.trim();
    const score    = parseScore(rawScore);

    if (rawScore === undefined || rawScore === '') {
      emptyScoreCount++;
    }

    // Build extra fields (everything that isn't id or score)
    const extra = {};
    rawHeaders.forEach((col, i) => {
      if (i !== idIdx && i !== scoreIdx && col) {
        extra[col] = fields[i] ?? '';
      }
    });

    genes.push({
      symbol: rawId,
      score:  isNaN(score) ? 0 : score,
      rawId,
      ...(Object.keys(extra).length > 0 ? { extra } : {}),
    });
  }

  if (emptyScoreCount > 0) {
    warnings.push(`${emptyScoreCount} row(s) had no score value — defaulted to 0.`);
  }
  if (unparsedCount > 0) {
    warnings.push(`${unparsedCount} row(s) were skipped (missing gene identifier).`);
  }
  if (genes.length === 0) {
    warnings.push('No rows found. Check that the file has a header row and data rows.');
    return { genes, warnings };
  }
  if (genes.length < MIN_GENES) {
    warnings.push(`Only ${genes.length} gene(s) found — need at least ${MIN_GENES}. Upload a larger list.`);
    return { genes: [], warnings };
  }

  return { genes, warnings };
}
