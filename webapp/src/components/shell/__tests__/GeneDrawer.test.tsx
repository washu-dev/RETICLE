import { render, screen, fireEvent } from '@testing-library/react';
import GeneDrawer from '../GeneDrawer';

const gene = {
  symbol: 'Jak2', query: 'Jak2', organism: 'Mus musculus', n_total: 30, primary: 'fitness',
  fitness: { n: 20, n_hits: 8, hit_rate: 0.4, median: -0.2, mean: -0.2, p25: -0.5, p75: 0.1, min: -1, max: 1, lean: 'essential' },
  stress: {
    n: 6, n_hits: 3, hit_rate: 0.5, median: 0, mean: 0, p25: 0, p75: 0, min: -1, max: 1, lean: 'mixed',
    ledger: [{ condition: 'IFN-γ', class: 'cytokine', direction: 'resist', net: 2, n_papers: 2, n_screens: 3, n_agree: 3, facts: [] }],
  },
  reporter: { n: 0, n_hits: 0, ledger: [] },
};
const context = {
  symbol: 'Jak2',
  annotation: { entrez: 16452, name: 'Janus kinase 2', summary: 'A signalling kinase.', go_bp: 5, go_mf: 3, go_cc: 2, go_total: 10 },
  darkness: { score: 1.2, pubmed_count: 2400, go_total: 10, dark_pub: 0.1, dark_go: 0.2, band: 'bright' },
  string_partners: [{ partner: 'STAT1', score: 0.99 }, { partner: 'JAK1', score: 0.98 }],
};

jest.mock('../../../services/reticleApi', () => ({
  fetchGeneExplorer: jest.fn(() => Promise.resolve(gene)),
  fetchGeneContext: jest.fn(() => Promise.resolve(context)),
  fetchCoessential: jest.fn(() =>
    Promise.resolve({
      symbol: 'Jak2',
      nodes: [
        { name: 'STAT1', lean: 'essential', focus: false },
        { name: 'JAK1', lean: 'essential', focus: false },
        { name: 'Jak2', lean: 'essential', focus: true },
      ],
      edges: [],
      n_screens: 40,
    })
  ),
  fetchInterpret: jest.fn(() => Promise.reject(new Error('503 unavailable'))),
  toApiOrganism: (o: string) => o,
}));

describe('GeneDrawer', () => {
  test('a closed drawer is hidden from assistive tech', () => {
    render(<GeneDrawer symbol={null} onClose={jest.fn()} />);
    expect(screen.getByLabelText('Gene entity')).toHaveAttribute('aria-hidden', 'true');
  });

  test('Overview renders real gene behavior and NCBI context', async () => {
    render(<GeneDrawer symbol="Jak2" onClose={jest.fn()} />);
    expect(await screen.findByText('A signalling kinase.')).toBeInTheDocument();
    // hits = fitness(8) + stress(3) + reporter(0) = 11 of n_total 30
    expect(screen.getByText(/hit in 11 of 30 assayed/)).toBeInTheDocument();
    expect(screen.getByText(/Janus kinase 2/)).toBeInTheDocument();
  });

  test('Why tab lists the real hit ledgers', async () => {
    render(<GeneDrawer symbol="Jak2" onClose={jest.fn()} />);
    await screen.findByText('A signalling kinase.');
    fireEvent.click(screen.getByRole('tab', { name: 'Why a hit / not' }));
    expect(screen.getByText('IFN-γ')).toBeInTheDocument();
    expect(screen.getByText(/Proliferation \/ fitness/)).toBeInTheDocument();
  });

  test('Relatives tab shows real co-essential partners', async () => {
    render(<GeneDrawer symbol="Jak2" onClose={jest.fn()} />);
    await screen.findByText('A signalling kinase.');
    fireEvent.click(screen.getByRole('tab', { name: 'Relatives' }));
    expect(await screen.findByText('STAT1')).toBeInTheDocument();
    expect(screen.getByText('JAK1')).toBeInTheDocument();
  });

  test('Escape invokes onClose', async () => {
    const onClose = jest.fn();
    render(<GeneDrawer symbol="Jak2" onClose={onClose} />);
    await screen.findByText('A signalling kinase.'); // let the async loads settle inside act
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
