import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import GraphExplorer from './GraphExplorer'

// Mock Cytoscape so it doesn't need a real canvas/WebGL renderer
const mockNodeCollection = {
  filter: vi.fn(() => []),   // returns empty → applyFocus bails early
  addClass: vi.fn(),
  removeClass: vi.fn(),
  not: vi.fn(function () { return this }),
}
const mockEdgeCollection = {
  removeClass: vi.fn(),
  not: vi.fn(function () { return this }),
  addClass: vi.fn(),
}

vi.mock('cytoscape', () => ({
  default: vi.fn(() => ({
    on: vi.fn(),
    nodes: vi.fn(() => mockNodeCollection),
    edges: vi.fn(() => mockEdgeCollection),
    animate: vi.fn(),
    destroy: vi.fn(),
  })),
}))

describe('GraphExplorer', () => {
  it('renders without crashing', () => {
    render(<GraphExplorer />)
    expect(screen.getByText(/gene → screen → paper graph/i)).toBeInTheDocument()
  })

  it('shows a chip for each gene/dark node', () => {
    render(<GraphExplorer />)
    expect(screen.getByRole('button', { name: 'ATG5' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'CCDC6' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'FAM114A1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ULK1' })).toBeInTheDocument()
  })

  it('shows the legend panel when nothing is selected', () => {
    render(<GraphExplorer />)
    expect(screen.getByText(/node legend/i)).toBeInTheDocument()
    // Use exact match to avoid matching "Screen" inside the title/description text
    expect(screen.getByText('Screen')).toBeInTheDocument()
    expect(screen.getByText('Dark candidate')).toBeInTheDocument()
  })

  it('shows layout toggle buttons', () => {
    render(<GraphExplorer />)
    expect(screen.getByRole('button', { name: 'cose' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'breadthfirst' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'circle' })).toBeInTheDocument()
  })

  it('shows a "Select gene:" label before chips', () => {
    render(<GraphExplorer />)
    expect(screen.getByText(/select gene:/i)).toBeInTheDocument()
  })

  it('legend explains click behaviour', () => {
    render(<GraphExplorer />)
    expect(screen.getByText(/click a gene/i)).toBeInTheDocument()
  })
})
