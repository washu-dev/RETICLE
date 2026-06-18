import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

// Stub heavy sub-components so App's state machine is tested in isolation
vi.mock('./components/LandingPage', () => ({
  default: ({ onStart }) => <button onClick={onStart}>Get started</button>,
}))

vi.mock('./components/UploadPage', () => ({
  default: ({ onAnalyze }) => (
    <button onClick={() => onAnalyze([{ symbol: 'ATG5', score: -3.21 }], { algorithm: 'MAGeCK LFC', modalities: ['KO'], organism: 'Human' })}>
      Run analysis
    </button>
  ),
}))

vi.mock('./components/LoadingAnalysis', () => ({
  default: ({ geneCount, onDone }) => (
    <div>
      <span>Loading {geneCount} genes</span>
      <button onClick={onDone}>Finish loading</button>
    </div>
  ),
}))

vi.mock('./components/ResultsPage', () => ({
  default: ({ genes, onReset }) => (
    <div>
      <span>Results for {genes?.length} genes</span>
      <button onClick={onReset}>New query</button>
    </div>
  ),
}))

describe('App flow', () => {
  it('starts on the landing page', () => {
    render(<App />)
    expect(screen.getByText('Get started')).toBeInTheDocument()
  })

  it('navigates to upload when "Get started" is clicked', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByText('Get started'))
    expect(screen.getByText('Run analysis')).toBeInTheDocument()
  })

  it('navigates to loading screen after analysis is submitted', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByText('Get started'))
    await user.click(screen.getByText('Run analysis'))
    expect(screen.getByText(/loading 1 genes/i)).toBeInTheDocument()
  })

  it('shows results page after loading completes', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByText('Get started'))
    await user.click(screen.getByText('Run analysis'))
    await user.click(screen.getByText('Finish loading'))
    expect(screen.getByText(/results for 1 genes/i)).toBeInTheDocument()
  })

  it('"New query" on results page returns to upload', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByText('Get started'))
    await user.click(screen.getByText('Run analysis'))
    await user.click(screen.getByText('Finish loading'))
    await user.click(screen.getByText('New query'))
    expect(screen.getByText('Run analysis')).toBeInTheDocument()
  })
})
