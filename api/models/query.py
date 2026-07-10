from models.base import CamelModel


class GeneInput(CamelModel):
    symbol: str
    score: float


class QueryRequest(CamelModel):
    genes: list[GeneInput]
    algorithm: str = "MAGeCK LFC"
    organism: str = "Both"
    modalities: list[str] = ["KO", "CRISPRa"]
    pathway_analysis: bool = False


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
