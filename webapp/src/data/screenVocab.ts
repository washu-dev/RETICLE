/**
 * screenVocab.ts — controlled vocabularies for describing a screen and filtering
 * the comparison corpus.
 *
 * These MUST stay aligned with the values the backend curation writes into
 * `screen_metadata_curated` (see prototype/script/llm_metadata_extractor.py) and
 * the intended data model in requirements/requirement_analysis.md §6.4–6.5.
 * A single source here keeps the describe form and the compare-to filters — and
 * the query the backend runs — speaking the same language.
 */

export interface VocabOption {
  value: string;
  /** Plain-language label a bench biologist recognizes. */
  label: string;
  /** Optional one-line clarifier for tooltips / helper text. */
  hint?: string;
}

/** CRISPR modality / screen_type. Base editing is folded into KO (loss-of-function). */
export const MODALITY: VocabOption[] = [
  { value: 'KO', label: 'Knockout (KO)', hint: 'CRISPRn / Cas9 nuclease — loss of function' },
  { value: 'CRISPRi', label: 'CRISPRi', hint: 'dCas9-KRAB transcriptional repression' },
  { value: 'CRISPRa', label: 'CRISPRa', hint: 'dCas9 transcriptional activation' },
  { value: 'RNAi', label: 'RNAi', hint: 'shRNA / siRNA knockdown' },
  { value: 'Other', label: 'Other', hint: 'Base editing or an unlisted modality' },
];

/** selection_method — how cells were selected/scored. */
export const SELECTION_METHOD: VocabOption[] = [
  { value: 'Negative', label: 'Negative (dropout)', hint: 'Depleted guides = essential genes' },
  { value: 'Positive', label: 'Positive (enrichment)', hint: 'Enriched guides = resistance genes' },
  { value: 'Bidirectional', label: 'Both directions', hint: 'Positive and negative selection' },
  { value: 'Phenotype', label: 'Phenotype / sort', hint: 'FACS or marker-based sorting' },
  { value: 'Unknown', label: 'Unknown', hint: '' },
];

/**
 * assay_domain — the coarse class that governs cross-screen comparability. This
 * is the single most important compare-to filter.
 */
export const ASSAY_DOMAIN: VocabOption[] = [
  { value: 'fitness', label: 'Fitness', hint: 'Baseline survival / growth (the essentiality axis)' },
  { value: 'stress', label: 'Stress', hint: 'Survival under an applied pressure (drug, virus, toxin)' },
  { value: 'reporter', label: 'Reporter', hint: 'Sorted by a measured marker (FACS / level / localization)' },
  { value: 'other', label: 'Other', hint: 'Phenotype that fits none of the above cleanly' },
];

/** coverage_type — SCOPE of the library (distinct from data availability). */
export const COVERAGE_SCOPE: VocabOption[] = [
  { value: 'Genome-wide', label: 'Genome-wide', hint: 'A whole-genome library' },
  { value: 'Focused', label: 'Focused', hint: 'A targeted / sub-library' },
  { value: 'Unknown', label: 'Unknown', hint: '' },
];

/**
 * Data availability — whether every gene is scored (FULL) or only hits are
 * reported (HITS_ONLY). Auto-detected from the file; distinct from scope above.
 */
export const COVERAGE_AVAILABILITY: VocabOption[] = [
  { value: 'FULL', label: 'Every gene scored', hint: 'Full ranked table — absence means "not in library"' },
  { value: 'HITS_ONLY', label: 'Hits only', hint: 'Only hits reported — a gene\'s absence is undefined' },
];

export const ORGANISM: VocabOption[] = [
  { value: 'Human', label: 'Human', hint: 'Homo sapiens' },
  { value: 'Mouse', label: 'Mouse', hint: 'Mus musculus' },
];

/** Common CRISPR libraries (extend as needed; free-text entry also allowed). */
export const LIBRARY: VocabOption[] = [
  { value: 'Brunello', label: 'Brunello' },
  { value: 'Brie', label: 'Brie', hint: 'Mouse' },
  { value: 'GeCKOv2', label: 'GeCKO v2' },
  { value: 'Calabrese', label: 'Calabrese', hint: 'CRISPRa' },
  { value: 'Caprano', label: 'Caprano', hint: 'CRISPRa (mouse)' },
  { value: 'Dolcetto', label: 'Dolcetto', hint: 'CRISPRi' },
  { value: 'TKOv3', label: 'TKOv3' },
  { value: 'custom', label: 'Custom / other' },
];

/** Comparison direction (which condition is the numerator). */
export const COMPARISON_DIRECTION: VocabOption[] = [
  { value: 'A_MINUS_B', label: 'Treated − control' },
  { value: 'B_MINUS_A', label: 'Control − treated' },
];

/** Hit-threshold statistic type. */
export const HIT_THRESHOLD_TYPE: VocabOption[] = [
  { value: 'FDR', label: 'FDR', hint: 'e.g. FDR < 0.10' },
  { value: 'SCORE', label: 'Score cutoff' },
  { value: 'CUSTOM', label: 'Custom' },
];

/** Common cell types (suggestions; free-text also allowed). */
export const CELL_TYPE: VocabOption[] = [
  { value: 'macrophage', label: 'Macrophage' },
  { value: 'microglia', label: 'Microglia' },
  { value: 'T cell', label: 'T cell' },
  { value: 'cancer', label: 'Cancer line' },
  { value: 'stem cell', label: 'Stem / iPSC' },
  { value: 'fibroblast', label: 'Fibroblast' },
  { value: 'epithelial', label: 'Epithelial' },
];

/** Scoring algorithm that produced the ranked list. */
export const ALGORITHM: VocabOption[] = [
  { value: 'MAGeCK LFC', label: 'MAGeCK LFC' },
  { value: 'MAGeCK MLE', label: 'MAGeCK MLE' },
  { value: 'STARS', label: 'STARS' },
  { value: 'DRUGz', label: 'DRUGz' },
  { value: 'DESeq2', label: 'DESeq2' },
  { value: 'residual', label: 'Residual / z-score' },
  { value: 'Custom', label: 'Custom' },
];

/** Map a parser format string to its most likely scoring algorithm. */
export const FORMAT_TO_ALGORITHM: Record<string, string> = {
  MAGECK: 'MAGeCK LFC',
  STARS: 'STARS',
  DESEQ2: 'DESeq2',
  RESIDUAL: 'residual',
  ORCS: 'Custom',
  SIMPLE: 'Custom',
  UNKNOWN: 'Custom',
};

/** Look up a label for a value within a vocab list (falls back to the raw value). */
export function labelFor(vocab: VocabOption[], value: string | undefined): string {
  if (!value) return '';
  return vocab.find(o => o.value === value)?.label ?? value;
}
