// Mock data for RETICLE PI demo — all data is illustrative

export const EXAMPLE_GENE_LIST = `gene_symbol,score
ATG5,-3.21
ATG7,-2.98
ULK1,-2.74
IRGM,-2.61
BECN1,-2.43
PIK3C3,-2.31
ATG14,-2.18
RUBCN,-2.05
ATG16L1,-1.94
MAP1LC3B,-1.82
SQSTM1,-1.71
CCDC6,-1.63
FAM114A1,-1.55
ZSWIM8,-1.44
C1orf43,-1.38
ANKRD36C,-1.27
TMEM106B,-1.19
VAMP8,-1.11
STK38L,-1.04
BNIP3L,-0.97
RAB7A,-0.89
TBK1,1.22
MTOR,1.44
AKT1,1.67
RPTOR,1.89`;

export const MATCHED_SCREENS = [
  {
    id: 1,
    biogridId: "ORCS-4421",
    name: "Autophagy regulation in LPS-stimulated macrophages",
    citation: "Orvedahl et al., 2019",
    pmid: "31097699",
    organism: "Human",
    modality: "KO",
    cellType: "THP-1 macrophages",
    rho: 0.82,
    fdr: 0.0003,
    directionality: "agree",
    sharedGenes: 18,
    totalGenes: 847,
  },
  {
    id: 2,
    biogridId: "ORCS-6102",
    name: "IFNγ pathway modulators in monocyte-derived macrophages",
    citation: "Zhao et al., 2021",
    pmid: "33782614",
    organism: "Human",
    modality: "KO",
    cellType: "MDMs",
    rho: 0.74,
    fdr: 0.0011,
    directionality: "agree",
    sharedGenes: 15,
    totalGenes: 912,
  },
  {
    id: 3,
    biogridId: "ORCS-7883",
    name: "mTOR complex regulation in nutrient stress",
    citation: "Lin et al., 2022",
    pmid: "35124892",
    organism: "Human",
    modality: "KO",
    cellType: "HEK293T",
    rho: 0.61,
    fdr: 0.0084,
    directionality: "agree",
    sharedGenes: 12,
    totalGenes: 1204,
  },
  {
    id: 4,
    biogridId: "ORCS-5519",
    name: "Macrophage activation enhancers — CRISPRa gain-of-function",
    citation: "Park et al., 2023",
    pmid: "36891234",
    organism: "Human",
    modality: "CRISPRa",
    cellType: "iPSC-derived macrophages",
    rho: -0.55,
    fdr: 0.0142,
    directionality: "inverted",
    sharedGenes: 11,
    totalGenes: 763,
  },
  {
    id: 5,
    biogridId: "ORCS-8234",
    name: "Inflammatory cell death regulators in RAW264.7",
    citation: "Huang et al., 2021",
    pmid: "33441802",
    organism: "Mouse",
    modality: "KO",
    cellType: "RAW264.7",
    rho: 0.48,
    fdr: 0.0389,
    directionality: "agree",
    sharedGenes: 9,
    totalGenes: 688,
  },
  {
    id: 6,
    biogridId: "ORCS-9041",
    name: "Autophagic flux determinants in J774 cells",
    citation: "Chen et al., 2022",
    pmid: "35672901",
    organism: "Mouse",
    modality: "KO",
    cellType: "J774A.1",
    rho: 0.43,
    fdr: 0.0512,
    directionality: "agree",
    sharedGenes: 8,
    totalGenes: 731,
  },
  {
    id: 7,
    biogridId: "ORCS-11203",
    name: "Pyroptosis effector screen in BMDMs",
    citation: "Kim et al., 2023",
    pmid: "37102456",
    organism: "Mouse",
    modality: "KO",
    cellType: "BMDMs",
    rho: 0.31,
    fdr: 0.1204,
    directionality: "unknown",
    sharedGenes: 6,
    totalGenes: 522,
  },
  {
    id: 8,
    biogridId: "ORCS-10087",
    name: "Immune checkpoint regulators in T cells",
    citation: "Wilson et al., 2022",
    pmid: "35984321",
    organism: "Human",
    modality: "KO",
    cellType: "Primary CD8+ T cells",
    rho: -0.28,
    fdr: 0.1891,
    directionality: "inverted",
    sharedGenes: 5,
    totalGenes: 1043,
  },
];

export const DARK_GENES = [
  { symbol: "CCDC6",     darkScore: 8.2, correlation: 0.71, pubs: 23,  screens: 4, go_terms: 3,  isBright: false, cluster: "dark-matter"         },
  { symbol: "FAM114A1",  darkScore: 9.1, correlation: 0.68, pubs: 8,   screens: 3, go_terms: 2,  isBright: false, cluster: "dark-matter"         },
  { symbol: "ZSWIM8",    darkScore: 7.8, correlation: 0.65, pubs: 31,  screens: 4, go_terms: 4,  isBright: false, cluster: "dark-matter"         },
  { symbol: "C1orf43",   darkScore: 8.9, correlation: 0.62, pubs: 12,  screens: 3, go_terms: 2,  isBright: false, cluster: "dark-matter"         },
  { symbol: "ANKRD36C",  darkScore: 9.4, correlation: 0.58, pubs: 5,   screens: 2, go_terms: 1,  isBright: false, cluster: "dark-matter"         },
  { symbol: "TMEM106B",  darkScore: 6.5, correlation: 0.77, pubs: 67,  screens: 5, go_terms: 6,  isBright: false, cluster: "selective-autophagy" },
  { symbol: "STK38L",    darkScore: 7.2, correlation: 0.54, pubs: 44,  screens: 3, go_terms: 5,  isBright: false, cluster: "selective-autophagy" },
  { symbol: "BNIP3L",    darkScore: 5.8, correlation: 0.59, pubs: 89,  screens: 4, go_terms: 7,  isBright: false, cluster: "selective-autophagy" },
  { symbol: "RAB7A",     darkScore: 4.4, correlation: 0.66, pubs: 214, screens: 6, go_terms: 12, isBright: false, cluster: "core-autophagy"      },
  { symbol: "VAMP8",     darkScore: 5.2, correlation: 0.81, pubs: 112, screens: 5, go_terms: 8,  isBright: false, cluster: "selective-autophagy" },
  { symbol: "ATG5",      darkScore: 2.1, correlation: 0.85, pubs: 892, screens: 7, go_terms: 22, isBright: true,  cluster: "core-autophagy"      },
  { symbol: "ATG7",      darkScore: 1.8, correlation: 0.82, pubs: 743, screens: 7, go_terms: 19, isBright: true,  cluster: "core-autophagy"      },
  { symbol: "ULK1",      darkScore: 3.2, correlation: 0.78, pubs: 501, screens: 6, go_terms: 16, isBright: true,  cluster: "core-autophagy"      },
  { symbol: "IRGM",      darkScore: 4.1, correlation: 0.73, pubs: 278, screens: 6, go_terms: 11, isBright: true,  cluster: "selective-autophagy" },
  { symbol: "BECN1",     darkScore: 2.4, correlation: 0.76, pubs: 1204,screens: 8, go_terms: 24, isBright: true,  cluster: "core-autophagy"      },
  { symbol: "MAP1LC3B",  darkScore: 3.0, correlation: 0.70, pubs: 631, screens: 7, go_terms: 17, isBright: true,  cluster: "core-autophagy"      },
];

export const STRING_INTERACTORS = {
  CCDC6: [
    { symbol: 'ATM',    combinedScore: 0.921, direction: 'upregulated'   },
    { symbol: 'RET',    combinedScore: 0.903, direction: 'upregulated'   },
    { symbol: 'ATG5',   combinedScore: 0.741, direction: 'downregulated' },
    { symbol: 'IRGM',   combinedScore: 0.688, direction: 'downregulated' },
    { symbol: 'TBK1',   combinedScore: 0.654, direction: 'upregulated'   },
    { symbol: 'BECN1',  combinedScore: 0.612, direction: 'unknown'       },
  ],
  FAM114A1: [
    { symbol: 'ATG5',   combinedScore: 0.712, direction: 'downregulated' },
    { symbol: 'ULK1',   combinedScore: 0.681, direction: 'downregulated' },
    { symbol: 'SQSTM1', combinedScore: 0.643, direction: 'unknown'       },
    { symbol: 'BNIP3L', combinedScore: 0.598, direction: 'downregulated' },
    { symbol: 'VAMP8',  combinedScore: 0.571, direction: 'unknown'       },
  ],
  ATG5: [
    { symbol: 'ATG7',     combinedScore: 0.999, direction: 'upregulated'   },
    { symbol: 'BECN1',    combinedScore: 0.997, direction: 'upregulated'   },
    { symbol: 'MAP1LC3B', combinedScore: 0.995, direction: 'upregulated'   },
    { symbol: 'ULK1',     combinedScore: 0.988, direction: 'upregulated'   },
    { symbol: 'ATG14',    combinedScore: 0.976, direction: 'upregulated'   },
    { symbol: 'RUBCN',    combinedScore: 0.931, direction: 'downregulated' },
    { symbol: 'IRGM',     combinedScore: 0.912, direction: 'upregulated'   },
  ],
  ATG7: [
    { symbol: 'ATG5',     combinedScore: 0.999, direction: 'upregulated' },
    { symbol: 'BECN1',    combinedScore: 0.996, direction: 'upregulated' },
    { symbol: 'MAP1LC3B', combinedScore: 0.992, direction: 'upregulated' },
    { symbol: 'ULK1',     combinedScore: 0.981, direction: 'upregulated' },
    { symbol: 'ATG16L1',  combinedScore: 0.974, direction: 'upregulated' },
  ],
  ULK1: [
    { symbol: 'ATG5',   combinedScore: 0.988, direction: 'upregulated'   },
    { symbol: 'BECN1',  combinedScore: 0.982, direction: 'upregulated'   },
    { symbol: 'ATG7',   combinedScore: 0.981, direction: 'upregulated'   },
    { symbol: 'PIK3C3', combinedScore: 0.962, direction: 'upregulated'   },
    { symbol: 'RPTOR',  combinedScore: 0.941, direction: 'downregulated' },
    { symbol: 'MTOR',   combinedScore: 0.934, direction: 'downregulated' },
  ],
};

export const GENE_RATIONALES = {
  CCDC6: {
    hypothesis: "CCDC6 (coiled-coil domain containing 6) co-clusters with core autophagy machinery (ATG5, ATG7, IRGM) across 4 of 8 matched screens, with a mean Spearman ρ of 0.71 to the query screen. Despite only 23 indexed publications, its pathway-correlation profile is indistinguishable from established autophagy genes, suggesting a functional role in autophagic flux or selective cargo recognition.",
    mechanisticContext: "CCDC6 is known primarily as a fusion partner in thyroid carcinoma (RET/PTC rearrangements), where it acts as a substrate for ATM-mediated DNA damage checkpointing. However, its role in non-malignant macrophage biology is completely uncharacterized. The co-occurrence pattern with IFNγ-responsive genes (TBK1, IRGM) in matched screens suggests a potential regulatory node connecting innate immune signaling to autophagic clearance — a mechanism consistent with the itaconate/Irg1 axis being studied.",
    citations: [
      { text: "Orvedahl et al. (2019) Nature Immunology", pmid: "31097699" },
      { text: "Zhao et al. (2021) Cell Reports", pmid: "33782614" },
      { text: "Lin et al. (2022) eLife", pmid: "35124892" },
    ],
    suggestedValidation: "Orthogonal validation via CRISPRi depletion in bone-marrow-derived macrophages with IFNγ/LPS co-stimulation. Assess LC3-II flux by western blot and p62/SQSTM1 accumulation as proxies for autophagic activity.",
    darkScore: 8.2,
    pubs: 23,
    screens: 4,
  },
  FAM114A1: {
    hypothesis: "FAM114A1 (family with sequence similarity 114 member A1) has only 8 indexed publications and appears in 3 matched screens correlated with macrophage death regulators. Its functional annotation is limited to 2 GO terms — it is among the highest-darkness candidates in this query.",
    mechanisticContext: "FAM114A1 encodes a poorly characterized transmembrane protein with predicted coiled-coil domains. It localizes to the ER in proteomics studies but has no assigned molecular function. The co-occurrence with known autophagy receptors in matched screens is unexplained by existing literature — this is a true dark matter candidate.",
    citations: [
      { text: "Zhao et al. (2021) Cell Reports", pmid: "33782614" },
      { text: "Huang et al. (2021) Science Immunology", pmid: "33441802" },
    ],
    suggestedValidation: "Subcellular localization in activated macrophages using fluorescence microscopy. Proximity ligation assay with ATG5/ATG7 to test physical interaction.",
    darkScore: 9.1,
    pubs: 8,
    screens: 3,
  },
};

export const GRAPH_ELEMENTS = {
  nodes: [
    { data: { id: "s1", label: "Orvedahl 2019", type: "screen", detail: "Autophagy · Human · KO",       citation: "Orvedahl et al., 2019 · Nature Immunology", pmid: "31097699", geneCount: 847  }, position: { x: 300, y: 200 } },
    { data: { id: "s2", label: "Zhao 2021",     type: "screen", detail: "IFNγ · Human · KO",            citation: "Zhao et al., 2021 · Cell Reports",           pmid: "33782614", geneCount: 912  }, position: { x: 500, y: 100 } },
    { data: { id: "s3", label: "Lin 2022",      type: "screen", detail: "mTOR · Human · KO",            citation: "Lin et al., 2022 · eLife",                   pmid: "35124892", geneCount: 1204 }, position: { x: 650, y: 280 } },
    { data: { id: "s4", label: "Park 2023",     type: "screen", detail: "Activation · iPSC · CRISPRa",  citation: "Park et al., 2023 · Cell Stem Cell",         pmid: "36891234", geneCount: 763  }, position: { x: 150, y: 350 } },
    { data: { id: "s5", label: "Huang 2021",    type: "screen", detail: "Cell death · Mouse · KO",      citation: "Huang et al., 2021 · Science Immunology",    pmid: "33441802", geneCount: 688  }, position: { x: 480, y: 400 } },

    { data: { id: "g1", label: "ATG5",     type: "gene", detail: "Core autophagy · 892 pubs",        screenCount: 3 }, position: { x: 350, y: 320 } },
    { data: { id: "g2", label: "ATG7",     type: "gene", detail: "Core autophagy · 743 pubs",        screenCount: 2 }, position: { x: 420, y: 250 } },
    { data: { id: "g3", label: "IRGM",     type: "gene", detail: "Selective autophagy · 278 pubs",   screenCount: 3 }, position: { x: 280, y: 150 } },
    { data: { id: "g4", label: "CCDC6",    type: "dark", detail: "Dark candidate · 23 pubs",         screenCount: 3 }, position: { x: 560, y: 200 } },
    { data: { id: "g5", label: "FAM114A1", type: "dark", detail: "Dark candidate · 8 pubs",          screenCount: 3 }, position: { x: 200, y: 260 } },
    { data: { id: "g6", label: "ULK1",     type: "gene", detail: "Autophagy initiation · 501 pubs",  screenCount: 2 }, position: { x: 390, y: 380 } },
  ],
  edges: [
    { data: { source: "s1", target: "g1", rho: 0.82, edgeLabel: "Orvedahl 2019 → ATG5"     } },
    { data: { source: "s1", target: "g2", rho: 0.78, edgeLabel: "Orvedahl 2019 → ATG7"     } },
    { data: { source: "s1", target: "g3", rho: 0.74, edgeLabel: "Orvedahl 2019 → IRGM"     } },
    { data: { source: "s1", target: "g4", rho: 0.71, edgeLabel: "Orvedahl 2019 → CCDC6"    } },

    { data: { source: "s2", target: "g1", rho: 0.68, edgeLabel: "Zhao 2021 → ATG5"         } },
    { data: { source: "s2", target: "g3", rho: 0.65, edgeLabel: "Zhao 2021 → IRGM"         } },
    { data: { source: "s2", target: "g4", rho: 0.62, edgeLabel: "Zhao 2021 → CCDC6"        } },
    { data: { source: "s2", target: "g5", rho: 0.58, edgeLabel: "Zhao 2021 → FAM114A1"     } },

    { data: { source: "s3", target: "g2", rho: 0.61, edgeLabel: "Lin 2022 → ATG7"          } },
    { data: { source: "s3", target: "g6", rho: 0.57, edgeLabel: "Lin 2022 → ULK1"          } },
    { data: { source: "s3", target: "g4", rho: 0.54, edgeLabel: "Lin 2022 → CCDC6"         } },

    { data: { source: "s4", target: "g5", rho: -0.55, edgeLabel: "Park 2023 → FAM114A1"   } },
    { data: { source: "s4", target: "g1", rho: -0.48, edgeLabel: "Park 2023 → ATG5"        } },

    { data: { source: "s5", target: "g6", rho: 0.43, edgeLabel: "Huang 2021 → ULK1"        } },
    { data: { source: "s5", target: "g3", rho: 0.39, edgeLabel: "Huang 2021 → IRGM"        } },
    { data: { source: "s5", target: "g5", rho: 0.36, edgeLabel: "Huang 2021 → FAM114A1"    } },
  ],
};
