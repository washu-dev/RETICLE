import { render, screen, fireEvent } from '@testing-library/react';
import DashboardView from '../DashboardView';

// The drawer fetches on open; keep those pending so we only test the dashboard.
jest.mock('../../../services/reticleApi', () => ({
  fetchGeneExplorer: jest.fn(() => new Promise(() => {})),
  fetchGeneContext: jest.fn(() => new Promise(() => {})),
  toApiOrganism: (o: string) => o,
}));

const queryResults = {
  queryId: 'q1',
  stats: { screensCompared: 287, significantMatches: 3, agreeDirectionality: 2, queryGeneCount: 25 },
  matchedScreens: [
    {
      id: 1, biogridId: 'B1', name: 'Zhang 2021', citation: 'Zhang et al.', pmid: '123',
      organism: 'Mouse', modality: 'KO', cellType: 'BMDM', rho: 0.87, fdr: 1e-9,
      directionality: 'agree', sharedGenes: 41, totalGenes: 50,
    },
  ],
  darkGenes: [
    { symbol: 'Fip1l1', darkScore: 7, correlation: 0.62, pubs: 12, screens: 5, goTerms: 3, isBright: false, cluster: 'x' },
  ],
  graphElements: { nodes: [], edges: [] },
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const props = { genes: [], options: { organism: 'Mouse' } as any, queryResults: queryResults as any, onNewAnalysis: jest.fn() };

describe('DashboardView', () => {
  test('renders the WashU shell, sections and real rows', () => {
    render(<DashboardView {...props} />);
    expect(screen.getAllByRole('img', { name: 'WashU Medicine' }).length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'Matched screens' })).toBeInTheDocument();
    expect(screen.getByText('Zhang 2021')).toBeInTheDocument();
    expect(screen.getByText('Fip1l1')).toBeInTheDocument();
  });

  test('"show numbers" reveals the uncalibrated stats on demand', () => {
    render(<DashboardView {...props} />);
    expect(screen.queryByText('raw ρ*')).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByText('show numbers')[0]);
    expect(screen.getByText('raw ρ*')).toBeInTheDocument();
  });

  test('clicking a dark gene opens the drawer', () => {
    render(<DashboardView {...props} />);
    // Closed: the dialog is aria-hidden and out of the a11y tree.
    expect(screen.queryByRole('dialog', { name: 'Gene entity' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Fip1l1'));
    expect(screen.getByRole('dialog', { name: 'Gene entity' })).toBeInTheDocument();
  });
});
