export type ReticleOrganism = 'human' | 'mouse';

/**
 * Normalize the organism labels used across uploads, BioGRID metadata and the
 * vendored Gene / Network pages into the compact value those pages accept.
 * Unknown or mixed pools keep the product's existing human default.
 */
export function toReticleOrganism(organism?: string | null): ReticleOrganism {
  const value = (organism ?? '').trim().toLowerCase();
  return value === 'mouse' || value === 'mus musculus' || value === '10090'
    ? 'mouse'
    : 'human';
}
