# Testing the RETICLE Demo

The demo uses **[Vitest](https://vitest.dev/)** as the test runner and **[React Testing Library](https://testing-library.com/docs/react-testing-library/intro/)** for rendering and interacting with components. Tests run in a simulated browser environment (jsdom) — no real browser required.

---

## Quick start

```bash
cd demo
npm test
```

That runs all 74 tests once and prints a pass/fail summary.

---

## All test commands

| Command | What it does |
|---------|-------------|
| `npm test` | Run all tests once (good for CI or before committing) |
| `npm run test:watch` | Re-run tests automatically whenever a file changes (good while writing code) |
| `npm run test:ui` | Open a browser-based test dashboard with a visual tree of results |
| `npm run test:coverage` | Run all tests and generate a coverage report in `coverage/` |

---

## What is being tested

### Unit tests — pure logic, no components

| File | Tests |
|------|-------|
| `src/utils/parseGenes.test.js` | CSV/TSV parsing: valid input, TSV, fewer-than-3-genes returns null, whitespace trimming, bad score defaults to 0 |
| `src/utils/geneGraph.test.js` | Graph traversal: `getConnectedScreens` and `getConnectedGenes` return the right nodes sorted by ρ, with citation and pmid populated |
| `src/mockData.test.js` | Data integrity: no pub-type nodes exist, every screen has a citation + pmid, all edge source/target IDs reference real nodes |

### Component tests — render a component and simulate user interaction

| File | Tests |
|------|-------|
| `src/components/UploadPage.test.jsx` | Upload area renders, example data loads, gene count shown, error on < 5 genes, `onAnalyze` called with correct shape, disabled submit button |
| `src/components/GeneDetailPanel.test.jsx` | Null when no symbol, gene header, AI hypothesis section, generic summary fallback, X button calls `onClose`, STRING section expands |
| `src/components/MatchedScreens.test.jsx` | All 8 screens render, FDR note shown, directionality badges present, query gene count from props |
| `src/components/DarkGeneScatter.test.jsx` | Gene chips render, clicking a chip opens detail panel, `onSelectGene` callback fires, deselect on second click, cluster regions with `pathwayAnalysis` prop |
| `src/components/GraphExplorer.test.jsx` | Gene chips render, legend shown by default, layout toggle buttons present |
| `src/components/ResultsPage.test.jsx` | All 4 tabs present, Query Genes tab shows uploaded list, "Graph →" button switches to Graph Explorer, scatter plot gene click bridges to graph with `focusGene` |

### Integration test — full app state machine

| File | Tests |
|------|-------|
| `src/App.test.jsx` | Starts on landing, clicks through to upload, submit triggers loading, loading complete shows results, "New query" returns to upload |

---

## File structure

```
demo/
├── src/
│   ├── test/
│   │   └── setup.js              ← global mocks (ResizeObserver, matchMedia, canvas)
│   ├── utils/
│   │   ├── parseGenes.js         ← extracted parser (testable in isolation)
│   │   ├── parseGenes.test.js
│   │   ├── geneGraph.js          ← extracted graph helpers
│   │   └── geneGraph.test.js
│   ├── mockData.test.js
│   ├── App.test.jsx
│   └── components/
│       ├── *.test.jsx            ← one test file per component
│       └── ...
└── vite.config.js                ← test config lives here (environment, setupFiles, coverage)
```

---

## Adding a new test

1. Create a file next to the code you want to test, named `<filename>.test.js` or `<filename>.test.jsx`.
2. Import `describe`, `it`, `expect` from `vitest` and `render`, `screen` from `@testing-library/react`.
3. Run `npm run test:watch` while writing — it re-runs on every save.

Minimal example:

```js
import { describe, it, expect } from 'vitest'
import { parseGenes } from './parseGenes'

describe('parseGenes', () => {
  it('returns null for fewer than 3 genes', () => {
    expect(parseGenes('gene_symbol,score\nATG5,-1')).toBeNull()
  })
})
```

---

## Mocking strategy for heavy dependencies

**Cytoscape.js** (the graph renderer) requires a real canvas that jsdom cannot provide. Any test file that renders `GraphExplorer` must mock it at the top:

```js
vi.mock('cytoscape', () => ({
  default: vi.fn(() => ({
    on: vi.fn(),
    nodes: vi.fn(() => ({ filter: vi.fn(() => []), addClass: vi.fn(), removeClass: vi.fn(), not: vi.fn(function() { return this }) })),
    edges: vi.fn(() => ({ removeClass: vi.fn(), not: vi.fn(function() { return this }), addClass: vi.fn() })),
    animate: vi.fn(),
    destroy: vi.fn(),
  })),
}))
```

**Recharts** uses `ResizeObserver` for chart sizing. The global mock in `src/test/setup.js` handles this automatically — no per-file action needed. For `ResponsiveContainer`, mock it to pass a fixed size:

```js
vi.mock('recharts', async () => {
  const actual = await vi.importActual('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }) =>
      React.cloneElement(children, { width: 600, height: 400 }),
  }
})
```

If you're testing a component that uses `GraphExplorer` or `DarkGeneScatter` indirectly (like `ResultsPage`), mock those entire components instead of mocking their dependencies:

```js
vi.mock('./GraphExplorer', () => ({
  default: ({ focusGene }) => <div data-testid="graph-explorer">{focusGene}</div>,
}))
```

---

## Coverage

```bash
npm run test:coverage
```

Generates a report in `demo/coverage/`. Open `coverage/index.html` in a browser for a line-by-line breakdown. Coverage is configured to track `src/**/*.{js,jsx}` excluding the test setup file and `main.jsx`.
