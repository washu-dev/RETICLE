"""Gm3558-anchored gene-relatedness pipeline (BioGRID ORCS, mouse).

Implements the client's 6-step design over the offline ORCS mouse archive:
  1. classify_screen_scores   (FULL vs HIT_ONLY coverage)
  2. harmonize_scores         (hit-anchored within-screen percentile + core-essential gate)
  3. build_gene_screen_matrix (dense gene x screen harmonized-percentile matrix)
  4. compute_channels         (co-essentiality / co-hit / co-citation / contextual)
  5. score_gene_relatedness   (effect x support x significance -> BH-FDR -> tier)
  6. validate_relatedness     (QA vs STRING + core-essential sanity)

Stdlib-only; anchored on one gene; never crosses organism.
"""
