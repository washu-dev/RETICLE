import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ResultsPage from './ResultsPage'
import { EXAMPLE_GENE_LIST } from '../mockData'
import { parseGenes } from '../utils/parseGenes'

// Suppress Cytoscape/Recharts noise in test output
vi.mock('./GraphExplorer', () => ({
  default: ({ focusGene }) => (
    <div data-testid="graph-explorer">
      {focusGene && <span data-testid="focused-gene">{focusGene}</span>}
    </div>
  ),
}))

vi.mock('./DarkGeneScatter', () => ({
  default: ({ onSelectGene }) => (
    <div>
      <button onClick={() => onSelectGene('CCDC6')}>Select CCDC6</button>
    </div>
  ),
}))

const mockGenes = parseGenes(EXAMPLE_GENE_LIST)
const mockOptions = { algorithm: 'MAGeCK LFC', organism: 'Human', modalities: ['KO'], pathwayAnalysis: false }

// Helper: clicks a tab by its button role (avoids matching non-button text with same words)
function clickTab(user, name) {
  return user.click(screen.getByRole('button', { name }))
}

describe('ResultsPage', () => {
  it('renders all four tabs', () => {
    render(<ResultsPage genes={mockGenes} options={mockOptions} onReset={vi.fn()} />)
    expect(screen.getByRole('button', { name: /query genes/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /matched screens/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /dark gene candidates/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /graph explorer/i })).toBeInTheDocument()
  })

  it('Query Genes tab shows the uploaded genes', async () => {
    const user = userEvent.setup()
    render(<ResultsPage genes={mockGenes} options={mockOptions} onReset={vi.fn()} />)
    await clickTab(user, /query genes/i)
    expect(screen.getByText('ATG5')).toBeInTheDocument()
    expect(screen.getByText('CCDC6')).toBeInTheDocument()
  })

  it('Query Genes tab shows gene count summary', async () => {
    const user = userEvent.setup()
    render(<ResultsPage genes={mockGenes} options={mockOptions} onReset={vi.fn()} />)
    await clickTab(user, /query genes/i)
    expect(screen.getByText(/genes from your screen/i)).toBeInTheDocument()
  })

  it('"Graph" button on a gene row switches to Graph Explorer tab', async () => {
    const user = userEvent.setup()
    render(<ResultsPage genes={mockGenes} options={mockOptions} onReset={vi.fn()} />)
    await clickTab(user, /query genes/i)
    // Gene-row "Graph" buttons don't contain "Explorer"; the tab button does
    const geneGraphBtn = screen.getAllByRole('button', { name: /graph/i })
      .find(b => !b.textContent.includes('Explorer'))
    await user.click(geneGraphBtn)
    expect(screen.getByTestId('graph-explorer')).toBeInTheDocument()
  })

  it('passes focusGene to GraphExplorer when a gene is selected via Graph button', async () => {
    const user = userEvent.setup()
    render(<ResultsPage genes={mockGenes} options={mockOptions} onReset={vi.fn()} />)
    await clickTab(user, /query genes/i)
    const geneGraphBtn = screen.getAllByRole('button', { name: /graph/i })
      .find(b => !b.textContent.includes('Explorer'))
    await user.click(geneGraphBtn)
    expect(screen.getByTestId('focused-gene')).toBeInTheDocument()
  })

  it('selecting a gene in DarkGeneScatter bridges to Graph Explorer', async () => {
    const user = userEvent.setup()
    render(<ResultsPage genes={mockGenes} options={mockOptions} onReset={vi.fn()} />)
    await clickTab(user, /dark gene candidates/i)
    await user.click(screen.getByText('Select CCDC6'))
    expect(screen.getByTestId('graph-explorer')).toBeInTheDocument()
    expect(screen.getByTestId('focused-gene')).toHaveTextContent('CCDC6')
  })

  it('calls onReset when "New query" is clicked', async () => {
    const user = userEvent.setup()
    const onReset = vi.fn()
    render(<ResultsPage genes={mockGenes} options={mockOptions} onReset={onReset} />)
    await user.click(screen.getByText(/new query/i))
    expect(onReset).toHaveBeenCalledOnce()
  })
})
