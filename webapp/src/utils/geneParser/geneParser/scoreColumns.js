/**
 * scoreColumns.js
 * Pure function — no side effects, no network calls.
 * Given a list of column names and a detected format, returns the
 * recommended score column and all candidate options for the UI dropdown.
 */

/**
 * Build a candidate list from a column array, using a priority order.
 * Columns are deduplicated and returned as {value, label} objects.
 *
 * @param {string[]} columns       All column names from the header
 * @param {string[]} priorityOrder Preferred column names (exact match, case-sensitive first, then case-insensitive)
 * @returns {{ value: string, label: string }[]}
 */
function buildCandidates(columns, priorityOrder) {
  // Build sorted list: priority columns first (in priority order), then the rest alphabetically
  const seen    = new Set();
  const ordered = [];

  for (const preferred of priorityOrder) {
    const match = columns.find(c => c === preferred)
      || columns.find(c => c.toLowerCase() === preferred.toLowerCase());
    if (match && !seen.has(match)) {
      seen.add(match);
      ordered.push(match);
    }
  }

  for (const col of columns) {
    if (!seen.has(col)) {
      seen.add(col);
      ordered.push(col);
    }
  }

  return ordered.map(c => ({ value: c, label: c }));
}

/**
 * suggestScoreColumn — recommend a default score column and return all candidates.
 *
 * Priority rules per format:
 *   MAGeCK : neg|lfc  →  neg|score  →  pos|lfc  →  pos|score  →  (any pipe col)
 *   STARS  : LFC  →  q-value
 *   DESeq2 : log2FoldChange  →  stat
 *   SIMPLE : second column (index 1), whatever name it has
 *   UNKNOWN: first numeric-looking column, or column index 1
 *
 * @param {string[]} columns  Column names from the parsed header
 * @param {'MAGECK'|'STARS'|'DESEQ2'|'SIMPLE'|'UNKNOWN'} format
 * @returns {{ defaultColumn: string, candidates: { value: string, label: string }[] }}
 */
export function suggestScoreColumn(columns, format) {
  if (!columns || columns.length === 0) {
    return { defaultColumn: '', candidates: [] };
  }

  let priorityOrder;

  switch (format) {
    case 'MAGECK': {
      priorityOrder = ['neg|lfc', 'neg|score', 'pos|lfc', 'pos|score'];
      // Also include any pipe-containing columns not already listed
      const pipeCols = columns.filter(c => c.includes('|') && !priorityOrder.includes(c));
      priorityOrder = [...priorityOrder, ...pipeCols];
      break;
    }
    case 'STARS':
      priorityOrder = ['LFC', 'lfc', 'q-value', 'p-value', 'Rank', 'rank'];
      break;
    case 'DESEQ2':
      priorityOrder = ['log2FoldChange', 'log2foldchange', 'stat', 'pvalue', 'padj', 'baseMean'];
      break;
    case 'SIMPLE': {
      // Default to the second column (index 1)
      const second = columns[1] || columns[0];
      priorityOrder = [second];
      break;
    }
    default:
      priorityOrder = columns.length > 1 ? [columns[1]] : [columns[0]];
  }

  const candidates    = buildCandidates(columns, priorityOrder);
  const defaultColumn = candidates[0]?.value ?? '';

  return { defaultColumn, candidates };
}
