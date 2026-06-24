import { apiGet, apiPost } from "./api";

// ---------------------------------------------------------------------------
// Types (mirror the Pydantic models' camelCase aliases)
// ---------------------------------------------------------------------------

export interface GeneInput {
  symbol: string;
  score: number;
}

export interface QueryOptions {
  algorithm?: string;
  organism?: string;
  modalities?: string[];
  pathwayAnalysis?: boolean;
}

export interface MatchedScreen {
  id: number;
  biogridId: string;
  name: string;
  citation: string;
  pmid: string;
  organism: string;
  modality: string;
  cellType: string;
  rho: number;
  fdr: number;
  directionality: string;
  sharedGenes: number;
  totalGenes: number;
}

export interface DarkGene {
  symbol: string;
  darkScore: number;
  correlation: number;
  pubs: number;
  screens: number;
  goTerms: number;
  isBright: boolean;
  cluster: string;
}

export interface GraphNodeData {
  id: string;
  label: string;
  type: "screen" | "gene" | "dark";
  detail?: string;
  citation?: string;
  pmid?: string;
  geneCount?: number;
  screenCount?: number;
}

export interface GraphNode {
  data: GraphNodeData;
  position?: { x: number; y: number };
}

export interface GraphEdgeData {
  source: string;
  target: string;
  rho: number;
  edgeLabel?: string;
}

export interface GraphEdge {
  data: GraphEdgeData;
}

export interface GraphElements {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface QueryStats {
  screensCompared: number;
  significantMatches: number;
  agreeDirectionality: number;
  queryGeneCount: number;
}

export interface QueryResponse {
  queryId: string;
  stats: QueryStats;
  matchedScreens: MatchedScreen[];
  darkGenes: DarkGene[];
  graphElements: GraphElements;
}

export interface Citation {
  text: string;
  pmid: string;
}

export interface StringInteractor {
  symbol: string;
  combinedScore: number;
  direction: string;
}

export interface GeneDetail {
  symbol: string;
  darkScore?: number;
  pubs?: number;
  screens?: number;
  correlation?: number;
  isBright?: boolean;
  hypothesis?: string;
  mechanisticContext?: string;
  citations: Citation[];
  suggestedValidation?: string;
  stringInteractors?: StringInteractor[];
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export async function runQuery(
  genes: GeneInput[],
  options: QueryOptions
): Promise<QueryResponse> {
  return apiPost<QueryResponse>("/api/query", {
    genes,
    algorithm: options.algorithm ?? "MAGeCK LFC",
    organism: options.organism ?? "Both",
    modalities: options.modalities ?? ["KO", "CRISPRa"],
    pathwayAnalysis: options.pathwayAnalysis ?? false,
  });
}

export async function fetchGeneDetail(
  symbol: string,
  signal?: AbortSignal
): Promise<GeneDetail> {
  return apiGet<GeneDetail>(`/api/genes/${symbol}`, { signal });
}
