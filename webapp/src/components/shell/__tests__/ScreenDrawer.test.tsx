import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ScreenDrawer from '../ScreenDrawer';
import { fetchScreenDetail, type ScreenDetail } from '../../../services/reticleApi';

jest.mock('../../../services/reticleApi', () => ({
  fetchScreenDetail: jest.fn(),
}));

const detail: ScreenDetail = {
  screenId: '1839',
  biogridUrl: 'https://orcs.thebiogrid.org/Screen/1839',
  pmid: '31509742',
  pubmedUrl: 'https://pubmed.ncbi.nlm.nih.gov/31509742',
  author: 'Freeman AJ (2019)',
  name: 'MHC-I regulators',
  organism: 'Mus musculus',
  cellLine: 'B16-F10',
  modality: 'KO',
  assayDomain: 'reporter',
  phenotype: 'protein/peptide accumulation',
  rationale: 'Regulation of MHC I expression',
  analysis: 'MaGeCK',
  coverageType: 'FULL',
  conditionName: 'Interferon gamma',
  scoresSize: 20570,
  nGenes: 20570,
  nHits: 1066,
  genesShown: 3,
  genes: [
    { symbol: 'Ifngr1', percentile: 1.0, isHit: true, harmonizedScore: 11.3, robustZ: 4.96 },
    { symbol: 'Stat1', percentile: 0.99, isHit: true, harmonizedScore: 9.5, robustZ: 4.2 },
    { symbol: 'Jak2', percentile: 0.98, isHit: true, harmonizedScore: 8.7, robustZ: 3.9 },
  ],
};

const mockFetch = fetchScreenDetail as jest.MockedFunction<typeof fetchScreenDetail>;

describe('ScreenDrawer', () => {
  beforeEach(() => mockFetch.mockReset());

  test('closed when screenId is null', () => {
    render(<ScreenDrawer screenId={null} onClose={jest.fn()} onOpenGene={jest.fn()} />);
    expect(screen.queryByRole('dialog', { name: 'Screen detail' })).not.toBeInTheDocument();
  });

  test('loads and renders metadata, links and gene tokens', async () => {
    mockFetch.mockResolvedValue(detail);
    render(<ScreenDrawer screenId="1839" onClose={jest.fn()} onOpenGene={jest.fn()} />);
    await waitFor(() => expect(screen.getByText('MHC-I regulators')).toBeInTheDocument());
    expect(screen.getByText('Interferon gamma')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /PubMed/ })).toHaveAttribute('href', detail.pubmedUrl);
    expect(screen.getByRole('link', { name: /BioGRID ORCS/ })).toHaveAttribute('href', detail.biogridUrl);
    expect(screen.getByRole('button', { name: 'Ifngr1' })).toBeInTheDocument();
  });

  test('clicking a gene token calls onOpenGene', async () => {
    mockFetch.mockResolvedValue(detail);
    const onOpenGene = jest.fn();
    render(<ScreenDrawer screenId="1839" onClose={jest.fn()} onOpenGene={onOpenGene} />);
    await waitFor(() => screen.getByRole('button', { name: 'Stat1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Stat1' }));
    expect(onOpenGene).toHaveBeenCalledWith('Stat1');
  });

  test('filter narrows the gene list', async () => {
    mockFetch.mockResolvedValue(detail);
    render(<ScreenDrawer screenId="1839" onClose={jest.fn()} onOpenGene={jest.fn()} />);
    await waitFor(() => screen.getByRole('button', { name: 'Ifngr1' }));
    fireEvent.change(screen.getByLabelText('Filter genes'), { target: { value: 'stat' } });
    expect(screen.getByRole('button', { name: 'Stat1' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ifngr1' })).not.toBeInTheDocument();
  });
});
