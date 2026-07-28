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

// Tokens that stand in for "no value" in real screen exports (BioGRID uses '-').
const MISSING_TOKENS = new Set(['', '-', 'na', 'nan', 'null', 'none', '.']);

/**
 * Parse a numeric score from a string. Returns NaN if unparseable or a known
 * missing-value token ('-', 'NA', …). Handles "1.23e-4", "-2.5", "0.001".
 *
 * @param {string} raw
 * @returns {number}
 */
function parseScore(raw) {
  if (raw === undefined || raw === null) return NaN;
  if (MISSING_TOKENS.has(String(raw).trim().toLowerCase())) return NaN;
  return parseFloat(raw);
}

/**
 * Interpret a hit-flag cell (YES/NO, 1/0, true/false) as a boolean.
 * @param {string} raw
 * @returns {boolean}
 */
function parseHit(raw) {
  const v = String(raw ?? '').trim().toLowerCase();
  return v === 'yes' || v === '1' || v === 'true' || v === 'hit' || v === 'y';
}

/**
 * parseGeneList — convert raw text into an array of normalized gene objects.
 *
 * @param {string} raw  Raw paste or file content
 * @param {{
 *   format?: 'MAGECK'|'STARS'|'DESEQ2'|'ORCS'|'RESIDUAL'|'SIMPLE'|'UNKNOWN',
 *   delimiter: '\t'|',',
 *   idColumn: string,
 *   scoreColumn: string,
 *   hitColumn?: string
 * }} options
 * @returns {{
 *   genes: Array<{symbol: string, score: number, rawId?: string, isHit?: boolean, extra?: Object}>,
 *   warnings: string[]
 * }}
 */
export function parseGeneList(raw, { delimiter, idColumn, scoreColumn, hitColumn }) {
  const warnings = [];
  const genes    = [];

  if (!raw || !raw.trim()) {
    warnings.push('No content to parse.');
    return { genes, warnings };
  }

  // Drop blank lines. The FIRST line may be a `#`-prefixed header (BioGRID ORCS);
  // any OTHER `#`-prefixed lines are comments and are skipped.
  const allLines = raw.trim().split('\n').map(l => l.trim()).filter(Boolean);
  if (allLines.length === 0) {
    warnings.push('No content to parse.');
    return { genes, warnings };
  }
  const headerLine = allLines[0].replace(/^#+\s*/, '');
  const lines = [headerLine, ...allLines.slice(1).filter(l => !l.startsWith('#'))];

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

  // Optional hit-flag column (BioGRID ORCS "HIT" = YES/NO). When present, each
  // gene carries an isHit boolean so callers can route hit-only lists to the
  // Jaccard-overlap path.
  const hitIdx = hitColumn
    ? headers.indexOf(hitColumn.toLowerCase())
    : headers.findIndex(h => h === 'hit' || h === 'hit_flag' || h === 'is_hit');

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
      ...(hitIdx >= 0 ? { isHit: parseHit(fields[hitIdx]) } : {}),
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
