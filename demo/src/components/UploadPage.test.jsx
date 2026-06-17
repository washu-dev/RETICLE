import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import UploadPage from './UploadPage'

describe('UploadPage', () => {
  it('renders the upload area and textarea', () => {
    render(<UploadPage onAnalyze={vi.fn()} />)
    expect(screen.getByText(/upload your gene list/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/csv or tsv/i)).toBeInTheDocument()
  })

  it('loads example data when "Load example data" is clicked', async () => {
    const user = userEvent.setup()
    render(<UploadPage onAnalyze={vi.fn()} />)
    await user.click(screen.getByText(/load example data/i))
    const textarea = screen.getByRole('textbox')
    expect(textarea.value).toContain('ATG5')
    expect(textarea.value).toContain('gene_symbol')
  })

  it('shows gene count after example data is loaded', async () => {
    const user = userEvent.setup()
    render(<UploadPage onAnalyze={vi.fn()} />)
    await user.click(screen.getByText(/load example data/i))
    expect(screen.getByText(/genes loaded/i)).toBeInTheDocument()
  })

  it('shows error when submitting with fewer than 5 genes', async () => {
    const user = userEvent.setup()
    render(<UploadPage onAnalyze={vi.fn()} />)
    const textarea = screen.getByRole('textbox')
    await user.type(textarea, 'gene_symbol,score\nATG5,-3.21\nULK1,-2.74')
    await user.click(screen.getByRole('button', { name: /run reticle/i }))
    expect(screen.getByText(/need at least 5 genes/i)).toBeInTheDocument()
  })

  it('calls onAnalyze with parsed genes and options on valid submit', async () => {
    const user = userEvent.setup()
    const onAnalyze = vi.fn()
    render(<UploadPage onAnalyze={onAnalyze} />)
    await user.click(screen.getByText(/load example data/i))
    await user.click(screen.getByRole('button', { name: /run reticle/i }))
    expect(onAnalyze).toHaveBeenCalledOnce()
    const [genes, options] = onAnalyze.mock.calls[0]
    expect(genes.length).toBeGreaterThan(5)
    expect(genes[0]).toHaveProperty('symbol')
    expect(genes[0]).toHaveProperty('score')
    expect(options).toHaveProperty('algorithm')
    expect(options).toHaveProperty('modalities')
  })

  it('run button is disabled when textarea is empty', () => {
    render(<UploadPage onAnalyze={vi.fn()} />)
    const runBtn = screen.getByRole('button', { name: /run reticle/i })
    expect(runBtn).toBeDisabled()
  })

  it('clear button resets the textarea', async () => {
    const user = userEvent.setup()
    render(<UploadPage onAnalyze={vi.fn()} />)
    await user.click(screen.getByText(/load example data/i))
    await user.click(screen.getByText(/clear/i))
    const textarea = screen.getByRole('textbox')
    expect(textarea.value).toBe('')
  })
})
