import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import GeneDetailPanel from './GeneDetailPanel'

describe('GeneDetailPanel', () => {
  it('renders nothing when no symbol is provided', () => {
    const { container } = render(<GeneDetailPanel symbol={null} onClose={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders gene header with symbol for a known dark candidate', () => {
    render(<GeneDetailPanel symbol="CCDC6" onClose={vi.fn()} />)
    expect(screen.getByText('CCDC6')).toBeInTheDocument()
    expect(screen.getByText(/dark candidate/i)).toBeInTheDocument()
    expect(screen.getByText(/23 publications/i)).toBeInTheDocument()
  })

  it('shows AI hypothesis for genes with rationale', () => {
    render(<GeneDetailPanel symbol="CCDC6" onClose={vi.fn()} />)
    expect(screen.getByText(/AI Hypothesis/i)).toBeInTheDocument()
    expect(screen.getByText(/co-clusters/i)).toBeInTheDocument()
  })

  it('shows mechanistic context section', () => {
    render(<GeneDetailPanel symbol="CCDC6" onClose={vi.fn()} />)
    expect(screen.getByText(/mechanistic context/i)).toBeInTheDocument()
  })

  it('shows generic summary for genes without a rationale entry', () => {
    render(<GeneDetailPanel symbol="ZSWIM8" onClose={vi.fn()} />)
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('ZSWIM8')
    expect(screen.getByText(/Summary/i)).toBeInTheDocument()
  })

  it('calls onClose when the X button is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<GeneDetailPanel symbol="CCDC6" onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: '' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('shows suggested next step section', () => {
    render(<GeneDetailPanel symbol="CCDC6" onClose={vi.fn()} />)
    expect(screen.getByText(/suggested next step/i)).toBeInTheDocument()
    expect(screen.getByText(/CRISPRi/i)).toBeInTheDocument()
  })

  it('STRING section expands when clicked', async () => {
    const user = userEvent.setup()
    render(<GeneDetailPanel symbol="CCDC6" onClose={vi.fn()} />)
    const stringButton = screen.getByText(/STRING protein interactions/i)
    await user.click(stringButton)
    expect(screen.getByText('ATM')).toBeInTheDocument()
    expect(screen.getByText('RET')).toBeInTheDocument()
  })
})
