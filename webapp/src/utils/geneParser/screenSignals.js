/**
 * screenSignals.js
 * Pure function — no side effects, no network calls.
 *
 * Derives the "what we read from your screen" signals that pre-fill the
 * describe-your-screen form and drive the parse-confirm receipt. These are
 * *hints* (auto-detected), never authoritative — the user can override every one.
 */

const ORGANISM_MAP = {
  'homo sapiens': 'Human',
  human: 'Human',
  '9606': 'Human',
  'mus musculus': 'Mouse',
  mouse: 'Mouse',
  '10090': 'Mouse',
};

/** Read a value from a gene's `extra` bag case-insensitively. */
function extraGet(extra, ...names) {
  if (!extra) return '';
  const lower = {};
  for (const [k, v] of Object.entries(extra)) lower[k.toLowerCase()] = v;
  for (const n of names) {
    const hit = lower[n.toLowerCase()];
    if (hit !== undefined && hit !== '') return hit;
  }
  return '';
}

/**
 * deriveScreenSignals — inspect the detected format + parsed genes and return
 * auto-fill hints for the describe form.
 *
 * @param {{ format: string, columns: string[], hitColumn?: string, conditionColumn?: string }} detected
 * @param {Array<{symbol: string, score: number, isHit?: boolean, extra?: Object}>} genes
 * @returns {{
 *   geneCount: number,
 *   organism: 'Human'|'Mouse'|null,
 *   coverageAvailability: 'FULL'|'HITS_ONLY'|null,
 *   direction: 'bidirectional'|'depletion'|'enrichment'|null,
 *   condition: string,
 *   hitCount: number|null
 * }}
 */
export function deriveScreenSignals(detected, genes) {
  const cols = (detected?.columns || []).map(c => c.toLowerCase());
  const sample = genes && genes.length ? genes[0] : null;

  // Organism — from an ORGANISM column if present, else null (ask the user).
  let organism = null;
  const orgRaw = String(
    extraGet(sample?.extra, 'ORGANISM_OFFICIAL', 'organism', 'ORGANISM_ID', 'organism_id')
  ).trim().toLowerCase();
  if (orgRaw) organism = ORGANISM_MAP[orgRaw] ?? null;

  // Coverage availability — if a hit flag exists and every row is a hit, the file
  // is a hit list (absence undefined); a mix means full scoring is present.
  let coverageAvailability = null;
  let hitCount = null;
  const hasHitFlag = genes.some(g => typeof g.isHit === 'boolean');
  if (hasHitFlag) {
    hitCount = genes.filter(g => g.isHit).length;
    coverageAvailability = hitCount === genes.length ? 'HITS_ONLY' : 'FULL';
  } else if (genes.length > 0) {
    coverageAvailability = 'FULL';
  }

  // Direction — bidirectional ranks (resistance ⇄ sensitization) are the clearest
  // signal; otherwise infer from the sign of the score distribution.
  let direction = null;
  if (cols.includes('ascending_rank') && cols.includes('descending_rank')) {
    direction = 'bidirectional';
  } else if (genes.length >= 5) {
    const neg = genes.filter(g => g.score < 0).length;
    const pos = genes.filter(g => g.score > 0).length;
    if (neg > 0 && pos > 0 && Math.min(neg, pos) / genes.length > 0.15) direction = 'bidirectional';
    else if (neg > pos) direction = 'depletion';
    else if (pos > neg) direction = 'enrichment';
  }

  const condition = String(extraGet(sample?.extra, 'condition')).trim();

  return {
    geneCount: genes.length,
    organism,
    coverageAvailability,
    direction,
    condition,
    hitCount,
  };
}

/** Human-facing label for a detected direction. */
export function directionLabel(direction) {
  switch (direction) {
    case 'bidirectional': return 'resistance ⇄ sensitization';
    case 'depletion':     return 'depletion (dropout)';
    case 'enrichment':    return 'enrichment';
    default:              return 'not detected';
  }
}
