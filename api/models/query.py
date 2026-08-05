from models.base import CamelModel


class GeneInput(CamelModel):
    symbol: str
    score: float


class ScreenContext(CamelModel):
    """The researcher's description of the screen they uploaded (the context
    vector). Every field is optional — auto-detected values pre-fill the form and
    the user may override any of them. Stored/echoed so results can label the
    described screen; not all fields drive the query today."""

    modality: str | None = None            # KO | CRISPRi | CRISPRa | RNAi | Other
    organism: str | None = None            # Human | Mouse
    selection_method: str | None = None    # Negative|Positive|Bidirectional|Phenotype|Unknown
    coverage_scope: str | None = None      # Genome-wide | Focused | Unknown
    coverage_availability: str | None = None  # FULL | HITS_ONLY (auto-detected)
    assay_domain: str | None = None        # fitness | stress | reporter | other
    cell_line: str | None = None
    cell_type: str | None = None
    library: str | None = None
    condition: str | None = None
    concentration: str | None = None
    timepoint: str | None = None
    timepoint_unit: str | None = None      # hours | days
    n_replicates: int | None = None
    comparison_direction: str | None = None
    hit_threshold_type: str | None = None
    hit_threshold_value: float | None = None
    direction: str | None = None           # bidirectional | depletion | enrichment
    algorithm: str | None = None
    score_column: str | None = None
    file_format: str | None = None


class CorpusFilters(CamelModel):
    """Which screens in the corpus to compare against. 'Any'/empty/all-selected
    values are treated as no-ops so the default request reproduces the unfiltered
    corpus."""

    organism: str = "Any"                  # Any | Human | Mouse
    assay_domains: list[str] = []          # subset of fitness|stress|reporter|other
    coverage: str = "Any"                  # Any | FULL
    cell_types: list[str] = []
    modalities: list[str] = []
    min_shared_genes: int = 0


class QueryRequest(CamelModel):
    genes: list[GeneInput]
    algorithm: str = "MAGeCK LFC"
    organism: str = "Both"
    modalities: list[str] = ["KO", "CRISPRa"]
    pathway_analysis: bool = False
    screen_context: ScreenContext | None = None
    corpus_filters: CorpusFilters | None = None


class MatchedScreen(CamelModel):
    id: int
    biogrid_id: str
    name: str
    citation: str
    pmid: str
    organism: str
    modality: str
    cell_type: str
    rho: float
    fdr: float
    directionality: str
    shared_genes: int
    total_genes: int
    # The query genes that are hits in this screen — the clickable bridge to the
    # single-gene lookup. Empty when unknown (e.g. the offline mock path).
    shared_gene_symbols: list[str] = []
    # Verified article title, resolved from `pmid` via NCBI so the displayed
    # citation always matches the PubMed link. None when unresolved (offline).
    article_title: str | None = None


class ScreenGene(CamelModel):
    symbol: str
    percentile: float | None = None
    is_hit: bool = False
    harmonized_score: float | None = None
    robust_z: float | None = None
    # The raw deposited score as it appears in BioGRID ORCS (score_1 / raw_score),
    # before RETICLE's harmonization. None when the screen didn't deposit one.
    raw_score: float | None = None


class ScreenDetail(CamelModel):
    """One screen's metadata + a capped, control-filtered list of its genes."""

    screen_id: str
    biogrid_url: str
    pmid: str | None = None
    pubmed_url: str | None = None
    author: str | None = None
    name: str | None = None
    # Verified from `pmid` via NCBI esummary — the article title and a formatted
    # citation ("Behan FM et al., 2019 · Nature"). None when unresolved (offline).
    article_title: str | None = None
    citation: str | None = None
    # Plain-language label for the raw deposited score column (from score_basis),
    # e.g. "Log2FC" — tells the reader what ScreenGene.raw_score actually means.
    raw_score_label: str | None = None
    organism: str | None = None
    cell_line: str | None = None
    cell_type: str | None = None
    screen_type: str | None = None
    modality: str | None = None
    analysis: str | None = None
    methodology: str | None = None
    phenotype: str | None = None
    rationale: str | None = None
    coverage_type: str | None = None
    assay_domain: str | None = None
    condition_name: str | None = None
    growth_direction: str | None = None
    score_basis: str | None = None
    is_directional: bool | None = None
    scores_size: int | None = None
    n_genes: int | None = None
    n_hits: int | None = None
    genes_shown: int | None = None
    genes: list[ScreenGene] = []


class DarkGene(CamelModel):
    symbol: str
    dark_score: float
    correlation: float
    pubs: int
    screens: int
    go_terms: int
    is_bright: bool
    cluster: str


class GraphNodeData(CamelModel):
    id: str
    label: str
    type: str
    detail: str | None = None
    citation: str | None = None
    pmid: str | None = None
    gene_count: int | None = None
    screen_count: int | None = None


class GraphNodePosition(CamelModel):
    x: float
    y: float


class GraphNode(CamelModel):
    data: GraphNodeData
    position: GraphNodePosition | None = None


class GraphEdgeData(CamelModel):
    source: str
    target: str
    rho: float
    edge_label: str | None = None


class GraphEdge(CamelModel):
    data: GraphEdgeData


class GraphElements(CamelModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class QueryStats(CamelModel):
    screens_compared: int
    significant_matches: int
    agree_directionality: int
    query_gene_count: int


class QueryResponse(CamelModel):
    query_id: str
    stats: QueryStats
    matched_screens: list[MatchedScreen]
    dark_genes: list[DarkGene]
    graph_elements: GraphElements
    screen_context: ScreenContext | None = None
    corpus_pool_size: int | None = None
