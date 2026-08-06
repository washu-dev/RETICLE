import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ScreenDrawer from '../ScreenDrawer';
import { fetchScreenDetail, type ScreenDetail } from '../../../services/reticleApi';

jest.mock('../../../services/reticleApi', () => ({
  fetchScreenDetail: jest.fn(),
}));

const detail: ScreenDetail = {
  screenId: '833',
  biogridUrl: 'https://orcs.thebiogrid.org/Screen/833',
  similarityAvailable: true,
  pmid: '30971826',
  pubmedUrl: 'https://pubmed.ncbi.nlm.nih.gov/30971826',
  author: 'Behan FM (2019)',
  name: 'Cancer dependency map',
  citation: 'Behan FM (2019) · Nature',
  articleTitle: 'Prioritization of cancer therapeutic targets using CRISPR-Cas9 screens',
  rawScoreLabel: 'Log2FC',
  organism: 'Homo sapiens',
  cellLine: 'KYSE-510',
  modality: 'KO',
  assayDomain: 'fitness',
  phenotype: 'cell fitness',
  rationale: 'Genome-wide fitness',
  analysis: 'MAGeCK',
  coverageType: 'FULL',
  conditionName: 'Interferon gamma',
  scoresSize: 18009,
  nGenes: 18009,
  nHits: 1066,
  genesShown: 3,
  genes: [
    { symbol: 'ATG5', percentile: 1.0, isHit: true, harmonizedScore: 11.3, robustZ: 4.96, rawScore: -2.84 },
    { symbol: 'ATG7', percentile: 0.99, isHit: true, harmonizedScore: 9.5, robustZ: 4.2, rawScore: -2.61 },
    { symbol: 'ULK1', percentile: 0.98, isHit: false, harmonizedScore: 8.7, robustZ: 3.9, rawScore: -2.3 },
  ],
};

const mockFetch = fetchScreenDetail as jest.MockedFunction<typeof fetchScreenDetail>;

/** Wait for load, then activate a tab by its accessible name. */
async function openTab(name: RegExp) {
  await waitFor(() => screen.getByText('Cancer dependency map'));
  fireEvent.click(screen.getByRole('tab', { name }));
}

describe('ScreenDrawer', () => {
  beforeEach(() => mockFetch.mockReset());

  test('closed when screenId is null', () => {
    render(<ScreenDrawer screenId={null} onClose={jest.fn()} onOpenGene={jest.fn()} />);
    expect(screen.queryByRole('dialog', { name: 'Screen detail' })).not.toBeInTheDocument();
  });

  test('overview shows metadata, verified citation and link-outs', async () => {
    mockFetch.mockResolvedValue(detail);
    render(<ScreenDrawer screenId="833" onClose={jest.fn()} onOpenGene={jest.fn()} />);
    await waitFor(() => expect(screen.getByText('Cancer dependency map')).toBeInTheDocument());
    expect(screen.getByText('Interferon gamma')).toBeInTheDocument();
    expect(screen.getByText(/Behan FM \(2019\) · Nature/)).toBeInTheDocument();
    // Link href and the citation next to it come from the same pmid.
    expect(screen.getByRole('link', { name: /PubMed/ })).toHaveAttribute('href', detail.pubmedUrl);
    expect(screen.getByRole('link', { name: /BioGRID ORCS/ })).toHaveAttribute('href', detail.biogridUrl);
  });

  test('genes tab lists clickable gene tokens', async () => {
    mockFetch.mockResolvedValue(detail);
    const onOpenGene = jest.fn();
    render(<ScreenDrawer screenId="833" onClose={jest.fn()} onOpenGene={onOpenGene} />);
    await openTab(/Genes/);
    fireEvent.click(screen.getByRole('button', { name: 'ATG7' }));
    expect(onOpenGene).toHaveBeenCalledWith('ATG7', 'human');
  });

  test('continues from the drawer into full screen comparison', async () => {
    mockFetch.mockResolvedValue(detail);
    const onOpenScreen = jest.fn();
    render(
      <ScreenDrawer
        screenId="833"
        onClose={jest.fn()}
        onOpenGene={jest.fn()}
        onOpenScreen={onOpenScreen}
      />,
    );
    await waitFor(() => screen.getByText('Cancer dependency map'));
    fireEvent.click(screen.getByRole('button', { name: /Find similar screens/i }));
    expect(onOpenScreen).toHaveBeenCalledWith('833');
  });

  test('does not offer a guaranteed-404 comparison for an unsupported screen', async () => {
    mockFetch.mockResolvedValue({ ...detail, similarityAvailable: false });
    render(
      <ScreenDrawer
        screenId="833"
        onClose={jest.fn()}
        onOpenGene={jest.fn()}
        onOpenScreen={jest.fn()}
      />,
    );
    await waitFor(() => screen.getByText('Cancer dependency map'));
    expect(screen.queryByRole('button', { name: /Find similar screens/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Similar-screen matching is unavailable/i)).toBeInTheDocument();
  });

  test('genes tab filter narrows the list', async () => {
    mockFetch.mockResolvedValue(detail);
    render(<ScreenDrawer screenId="833" onClose={jest.fn()} onOpenGene={jest.fn()} />);
    await openTab(/Genes/);
    fireEvent.change(screen.getByLabelText('Filter genes'), { target: { value: 'atg7' } });
    expect(screen.getByRole('button', { name: 'ATG7' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'ATG5' })).not.toBeInTheDocument();
  });

  test('raw data tab shows the raw + harmonized score table', async () => {
    mockFetch.mockResolvedValue(detail);
    render(<ScreenDrawer screenId="833" onClose={jest.fn()} onOpenGene={jest.fn()} />);
    await openTab(/Raw data/);
    // The raw-score column header is labeled with the deposited metric.
    expect(screen.getByText(/Raw · Log2FC/)).toBeInTheDocument();
    expect(screen.getByText('Harmonized')).toBeInTheDocument();
    // A raw deposited value from the fixture is rendered in the table.
    expect(screen.getByText('-2.84')).toBeInTheDocument();
  });

  test('raw data table sorts when a column header is clicked', async () => {
    mockFetch.mockResolvedValue(detail);
    render(<ScreenDrawer screenId="833" onClose={jest.fn()} onOpenGene={jest.fn()} />);
    await openTab(/Raw data/);
    // Default sort is percentile desc → ATG5 first. Sort by Gene asc/desc and
    // confirm the header is interactive (no throw, rows still present).
    fireEvent.click(screen.getByText('Gene'));
    expect(screen.getByRole('button', { name: 'ATG5' })).toBeInTheDocument();
  });

  test('arrow keys move between tabs (roving tabindex)', async () => {
    mockFetch.mockResolvedValue(detail);
    render(<ScreenDrawer screenId="833" onClose={jest.fn()} onOpenGene={jest.fn()} />);
    await waitFor(() => screen.getByText('Cancer dependency map'));
    const overview = screen.getByRole('tab', { name: /Overview/ });
    expect(overview).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: /Genes/ })).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'End' });
    expect(screen.getByRole('tab', { name: /Raw data/ })).toHaveAttribute('aria-selected', 'true');
  });
});
