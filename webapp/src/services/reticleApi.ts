import { apiGet, apiPost } from "./api";

// ---------------------------------------------------------------------------
// Types (mirror the Pydantic models' camelCase aliases)
// ---------------------------------------------------------------------------

export interface GeneInput {
  symbol: string;
  score: number;
}

/** The researcher's description of their uploaded screen (context vector). */
export interface ScreenContext {
  modality?: string;
  organism?: string;
  selectionMethod?: string;
  coverageScope?: string;
  coverageAvailability?: string;
  assayDomain?: string;
  cellLine?: string;
  cellType?: string;
  library?: string;
  condition?: string;
  concentration?: string;
  timepoint?: string;
  timepointUnit?: string;
  nReplicates?: number;
  comparisonDirection?: string;
  hitThresholdType?: string;
  hitThresholdValue?: number;
  direction?: string;
  algorithm?: string;
  scoreColumn?: string;
  fileFormat?: string;
}

/** Which corpus screens to compare against. Defaults are no-ops (full corpus). */
export interface CorpusFilters {
  organism: string;            // Any | Human | Mouse
  assayDomains: string[];      // subset of fitness|stress|reporter|other
  coverage: string;            // Any | FULL
  cellTypes: string[];
  modalities: string[];
  minSharedGenes: number;
}

export interface QueryOptions {
  algorithm?: string;
  organism?: string;
  modalities?: string[];
  pathwayAnalysis?: boolean;
  screenContext?: ScreenContext;
  corpusFilters?: CorpusFilters;
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
  screenContext?: ScreenContext;
  corpusPoolSize?: number;
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
    screenContext: options.screenContext,
    corpusFilters: options.corpusFilters,
  });
}

/** Live count of corpus screens matching the given compare-to filters. */
export async function fetchCorpusCount(
  filters: CorpusFilters,
  signal?: AbortSignal
): Promise<number> {
  const p = new URLSearchParams();
  if (filters.organism) p.set('organism', filters.organism);
  filters.assayDomains.forEach(d => p.append('assayDomains', d));
  if (filters.coverage) p.set('coverage', filters.coverage);
  filters.cellTypes.forEach(c => p.append('cellTypes', c));
  filters.modalities.forEach(m => p.append('modalities', m));
  if (filters.minSharedGenes) p.set('minSharedGenes', String(filters.minSharedGenes));
  const res = await apiGet<{ count: number }>(`/api/corpus/count?${p.toString()}`, { signal });
  return res.count;
}

export async function fetchGeneDetail(
  symbol: string,
  signal?: AbortSignal
): Promise<GeneDetail> {
  return apiGet<GeneDetail>(`/api/genes/${symbol}`, { signal });
}

// ---------------------------------------------------------------------------
// Explorer endpoints (/api/gene, /api/context, /api/network).
// These return the ported prototype's payload shape VERBATIM — snake_case, no
// camelCase aliasing (unlike the query/gene-detail endpoints above). The types
// below mirror api/services/explorer_*.py exactly.
// ---------------------------------------------------------------------------

export type Lean = 'essential' | 'advantageous' | 'mixed';

export interface PackedScreen {
  screen_id: number;
  cell_line: string;
  screen_type: string;
  analysis: string;
  phenotype: string;
  rationale: string;
  percentile: number;
  is_hit: number;
}

export interface DomainBlock {
  n: number;
  n_hits: number;
  hit_rate: number;
  median: number;
  mean: number;
  p25: number;
  p75: number;
  min: number;
  max: number;
  lean: Lean;
  // Present only on a "full" block (fitness); omitted on the stress summary.
  hist?: { edges: number[]; counts: number[] };
  rug?: number[];
  most_essential?: PackedScreen[];
  most_advantageous?: PackedScreen[];
  screens?: { p: number; cc: string; cn: string; h: number }[];
}

export interface StressFact {
  screen_id: number;
  author: string;
  pmid: string;
  cell_line: string;
  sign: 'pos' | 'neg';
}

export interface StressLedgerEntry {
  condition: string;
  class: string;
  direction: 'resist' | 'sensitise' | 'mixed';
  net: number;
  n_papers: number;
  n_screens: number;
  n_agree: number;
  facts: StressFact[];
}

export interface ReporterFact {
  screen_id: number;
  author: string;
  pmid: string;
  cell_line: string;
  phenotype: string;
}

export interface ReporterLedgerEntry {
  process: string;
  n_papers: number;
  n_screens: number;
  facts: ReporterFact[];
  screens: number[];
}

export interface StressBlock extends DomainBlock {
  ledger: StressLedgerEntry[];
}

export interface ReporterBlock {
  n: number;
  n_hits: number;
  ledger: ReporterLedgerEntry[];
}

export interface GeneExplorer {
  symbol: string;
  query: string;
  organism: string;
  n_total: number;
  primary: 'fitness' | 'stress' | 'reporter';
  fitness: DomainBlock | null;
  stress: StressBlock | null;
  reporter: ReporterBlock;
}

export interface GeneAnnotation {
  entrez: number | string | null;
  name: string;
  summary: string;
  go_bp: number;
  go_mf: number;
  go_cc: number;
  go_total: number;
}

export interface Darkness {
  score: number;
  pubmed_count: number;
  go_total: number;
  dark_pub: number;
  dark_go: number;
  band: 'dark' | 'grey' | 'bright';
}

export interface StringPartner {
  partner: string;
  score: number;
}

export interface GeneContext {
  symbol: string;
  annotation: GeneAnnotation | null;
  darkness: Darkness | null;
  string_partners: StringPartner[];
}

export interface NetworkNode {
  name: string;
  median: number | null;
  lean: Lean | null;
  focus: boolean;
}

export interface NetworkEdge {
  a: string;
  b: string;
  score: number;
  channels: Record<string, number>;
}

export interface GeneNetwork {
  focus: string;
  nodes: NetworkNode[];
  edges: NetworkEdge[];
}

/** Map the UI's organism option to the NCBI organism string the API expects. */
export function toApiOrganism(organism?: string): string {
  return organism === 'Mouse' || organism === 'Mus musculus' ? 'Mus musculus' : 'Homo sapiens';
}

/** Per-gene behavior across screens, split by assay domain. 404s for unknown genes. */
export async function fetchGeneExplorer(symbol: string, signal?: AbortSignal): Promise<GeneExplorer> {
  return apiGet<GeneExplorer>(`/api/gene?symbol=${encodeURIComponent(symbol)}`, { signal });
}

/** External context: NCBI annotation, darkness rating, STRING partners. */
export async function fetchGeneContext(
  symbol: string,
  organism = 'Homo sapiens',
  signal?: AbortSignal
): Promise<GeneContext> {
  const org = toApiOrganism(organism);
  return apiGet<GeneContext>(
    `/api/context?symbol=${encodeURIComponent(symbol)}&org=${encodeURIComponent(org)}`,
    { signal }
  );
}

/** STRING subnetwork colored by CRISPR fitness. */
export async function fetchGeneNetwork(
  symbol: string,
  organism = 'Homo sapiens',
  signal?: AbortSignal
): Promise<GeneNetwork> {
  const org = toApiOrganism(organism);
  return apiGet<GeneNetwork>(
    `/api/network?symbol=${encodeURIComponent(symbol)}&org=${encodeURIComponent(org)}`,
    { signal }
  );
}

// ---------------------------------------------------------------------------
// Phase 5 endpoints — co-essentiality, AI narrative, pathway enrichment.
// Snake_case, matching api/routers/*.py contracts.
// ---------------------------------------------------------------------------

export interface CoessNode {
  name: string;
  lean: Lean | null;
  focus: boolean;
}
export interface CoessEdge {
  a: string;
  b: string;
  r: number;
  score: number;
}
export interface CoessNetwork {
  symbol: string;
  nodes: CoessNode[];
  edges: CoessEdge[];
  n_screens: number;
}

/** Co-essentiality neighbours (pure-CRISPR relatedness) for a gene. */
export async function fetchCoessential(
  symbol: string,
  organism = 'Homo sapiens',
  signal?: AbortSignal
): Promise<CoessNetwork> {
  const org = toApiOrganism(organism);
  return apiGet<CoessNetwork>(
    `/api/coessential?symbol=${encodeURIComponent(symbol)}&org=${encodeURIComponent(org)}`,
    { signal }
  );
}

export interface InterpretSource {
  pmid: string;
  title: string;
}
export interface Interpretation {
  model: string;
  text: string;
  sources: InterpretSource[];
}

/** AI narrative for a gene footprint (the /api/gene payload). Throws ApiError
 *  503 when the LLM gateway is unconfigured — callers should degrade gracefully. */
export async function fetchInterpret(
  footprint: unknown,
  signal?: AbortSignal
): Promise<Interpretation> {
  return apiPost<Interpretation>('/api/interpret', footprint, { signal });
}

export interface PathwayTerm {
  term: string;
  p_value: number;
  adj_p_value: number;
  combined_score: number;
  overlap_genes: string[];
}
export interface PathwayResult {
  library: string;
  terms: PathwayTerm[];
}

/** Pathway enrichment (Enrichr) for a gene list. Returns empty terms on failure. */
export async function fetchPathways(
  genes: string[],
  library?: string,
  signal?: AbortSignal
): Promise<PathwayResult> {
  return apiPost<PathwayResult>('/api/pathways', { genes, library }, { signal });
}
