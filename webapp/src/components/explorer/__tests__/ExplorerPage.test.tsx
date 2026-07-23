/**
 * Mounts the Explorer (Shadow-DOM vendored prototype) in jsdom and drives a
 * gene search end-to-end with a mocked API, asserting the shadow tree renders.
 */
import { render, act } from '@testing-library/react';
import ExplorerPage from '../ExplorerPage';

const TP53 = {
  symbol: 'TP53',
  query: 'TP53',
  organism: 'Homo sapiens',
  n_total: 1567,
  primary: 'fitness',
  fitness: {
    n: 968, n_hits: 32, hit_rate: 0.0331, median: 0.499, mean: 0.3929,
    p25: -0.0537, p75: 0.9576, min: -1, max: 1, lean: 'advantageous',
    hist: { edges: [-1, 0, 1], counts: [1, 2] },
    rug: [0.1, 0.2], screens: [], most_essential: [], most_advantageous: [],
  },
  stress: null,
  reporter: { n: 0, n_hits: 0, ledger: [] },
};

/** minimal 2D-context stub so the canvas hero code doesn't throw in jsdom */
function stubCanvas() {
  const ctx = new Proxy({}, { get: () => () => undefined });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (HTMLCanvasElement.prototype as any).getContext = () => ctx;
}

beforeAll(() => {
  stubCanvas();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
  window.requestAnimationFrame = (() => 0) as unknown as typeof window.requestAnimationFrame;
  window.cancelAnimationFrame = (() => undefined) as unknown as typeof window.cancelAnimationFrame;
});

function mockFetch() {
  const calls: string[] = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (global as any).fetch = jest.fn((url: string) => {
    calls.push(url);
    if (url.includes('/api/gene')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(TP53) });
    }
    // context / network / coessential / interpret degrade gracefully
    return Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'n/a' }) });
  });
  return calls;
}

function shadow(container: HTMLElement): ShadowRoot {
  const host = container.querySelector('div') as HTMLElement;
  return host.shadowRoot as ShadowRoot;
}

describe('ExplorerPage', () => {
  test('mounts a shadow root with the search UI', () => {
    mockFetch();
    const { container } = render(<ExplorerPage onBack={jest.fn()} />);
    const root = shadow(container);
    expect(root).toBeTruthy();
    expect(root.querySelector('#q')).toBeTruthy(); // gene search box
    expect(root.querySelector('.rx-back')).toBeTruthy(); // back-to-app affordance
  });

  test('gene search renders the ported payload against the API base', async () => {
    const calls = mockFetch();
    const { container } = render(<ExplorerPage onBack={jest.fn()} />);
    const root = shadow(container);

    await act(async () => {
      (window as unknown as { explore: (s: string) => Promise<void> }).explore('TP53');
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(root.querySelector('.gene-sym')?.textContent).toBe('TP53');
    expect(root.querySelector('.verdict')?.textContent).toMatch(/advantageous/);
    expect(root.textContent).toMatch(/fitness screens/);
    // fetch went to the configured API base, not same-origin
    expect(calls.some((u) => u.includes('/api/gene?symbol=TP53'))).toBe(true);
  });

  test('back button invokes onBack', () => {
    mockFetch();
    const onBack = jest.fn();
    const { container } = render(<ExplorerPage onBack={onBack} />);
    (shadow(container).querySelector('.rx-back') as HTMLButtonElement).click();
    expect(onBack).toHaveBeenCalled();
  });
});
