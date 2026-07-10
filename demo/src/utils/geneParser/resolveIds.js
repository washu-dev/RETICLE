/**
 * resolveIds.js
 * Pure function — no side effects, no network calls.
 * Resolves gene identifiers (Entrez IDs, Ensembl IDs, mouse orthologs)
 * to HGNC symbols using a bundled crosswalk JSON.
 *
 * If the symbol is already an HGNC symbol (most common for SIMPLE format),
 * it passes through unchanged.
 */

/**
 * Determine whether a string looks like an Entrez ID (all digits).
 * @param {string} id
 * @returns {boolean}
 */
function looksLikeEntrez(id) {
  return /^\d+$/.test(id);
}

/**
 * Determine whether a string looks like an Ensembl gene ID.
 * @param {string} id
 * @returns {boolean}
 */
function looksLikeEnsembl(id) {
  return /^ENSG\d+(\.\d+)?$/i.test(id);
}

/**
 * resolveIdentifiers — map raw IDs in gene objects to HGNC symbols.
 *
 * Resolution order per gene:
 *   1. If id looks like Entrez → crosswalk.entrez[id]
 *   2. If id looks like Ensembl → crosswalk.ensembl[id]  (strips version suffix)
 *   3. If organism is Mouse → crosswalk.ortholog[id]
 *   4. Passthrough (assume already HGNC)
 *
 * @param {Array<{symbol: string, score: number, rawId?: string, extra?: Object}>} genes
 * @param {'Human'|'Mouse'} organism
 * @param {{ entrez: Object, ensembl: Object, ortholog: Object }} crosswalk
 * @returns {{
 *   genes: Array<{symbol: string, score: number, rawId?: string, extra?: Object}>,
 *   resolved: number,
 *   unmapped: Array<{rawId: string, reason: string}>,
 *   warnings: string[]
 * }}
 */
export function resolveIdentifiers(genes, organism, crosswalk) {
  const warnings = [];
  const unmapped = [];
  let resolved   = 0;

  if (!crosswalk) {
    warnings.push('Crosswalk not loaded — IDs passed through without resolution.');
    return { genes, resolved: 0, unmapped, warnings };
  }

  const { entrez = {}, ensembl = {}, ortholog = {} } = crosswalk;

  const resolvedGenes = genes.map(gene => {
    const rawId = gene.rawId ?? gene.symbol;

    // Entrez
    if (looksLikeEntrez(rawId)) {
      const hgnc = entrez[rawId];
      if (hgnc) {
        resolved++;
        return { ...gene, symbol: hgnc };
      }
      unmapped.push({ rawId, reason: 'Entrez ID not found in crosswalk' });
      return gene;
    }

    // Ensembl (strip version suffix like .12)
    if (looksLikeEnsembl(rawId)) {
      const baseId = rawId.split('.')[0].toUpperCase();
      const hgnc   = ensembl[baseId] || ensembl[rawId];
      if (hgnc) {
        resolved++;
        return { ...gene, symbol: hgnc };
      }
      unmapped.push({ rawId, reason: 'Ensembl ID not found in crosswalk' });
      return gene;
    }

    // Mouse ortholog
    if (organism === 'Mouse') {
      const hgnc = ortholog[rawId];
      if (hgnc) {
        resolved++;
        return { ...gene, symbol: hgnc };
      }
      // Not in ortholog map — keep the original symbol but note it
      // Many mouse genes have the same name in human (e.g. Atg5 → ATG5 via capitalisation)
      // Try a case-insensitive upper-case match as a heuristic passthrough
      const upperSym = rawId.toUpperCase();
      // No crosswalk hit: record as unmapped but still include (passthrough)
      unmapped.push({ rawId, reason: 'Mouse ortholog not found in crosswalk — symbol passed through' });
      return { ...gene, symbol: upperSym };
    }

    // Passthrough — assume already HGNC
    return gene;
  });

  if (unmapped.length > 0) {
    warnings.push(`${unmapped.length} ID(s) could not be fully resolved via crosswalk.`);
  }

  return { genes: resolvedGenes, resolved, unmapped, warnings };
}
