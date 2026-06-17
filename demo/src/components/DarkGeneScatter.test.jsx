import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import DarkGeneScatter from './DarkGeneScatter'

vi.mock('recharts', async () => {
  const actual = await vi.importActual('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }) =>
      React.cloneElement(children, { width: 600, height: 400 }),
  }
})

describe('DarkGeneScatter', () => {
  it('renders without crashing', () => {
    render(<DarkGeneScatter />)
    expect(screen.getByText(/dark gene landscape/i)).toBeInTheDocument()
  })

  it('shows dark candidate count callout', () => {
    render(<DarkGeneScatter />)
    expect(screen.getByText(/dark candidates/i)).toBeInTheDocument()
  })

  it('renders clickable gene chips for dark candidates', () => {
    render(<DarkGeneScatter />)
    expect(screen.getByRole('button', { name: 'CCDC6' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'FAM114A1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ANKRD36C' })).toBeInTheDocument()
  })

  it('clicking a gene chip opens the detail panel', async () => {
    const user = userEvent.setup()
    render(<DarkGeneScatter />)
    await user.click(screen.getByRole('button', { name: 'CCDC6' }))
    expect(screen.getByText(/AI Hypothesis/i)).toBeInTheDocument()
  })

  it('calls onSelectGene with the gene symbol when a chip is clicked', async () => {
    const user = userEvent.setup()
    const onSelectGene = vi.fn()
    render(<DarkGeneScatter onSelectGene={onSelectGene} />)
    await user.click(screen.getByRole('button', { name: 'CCDC6' }))
    expect(onSelectGene).toHaveBeenCalledWith('CCDC6')
  })

  it('clicking the same gene chip twice deselects it', async () => {
    const user = userEvent.setup()
    const onSelectGene = vi.fn()
    render(<DarkGeneScatter onSelectGene={onSelectGene} />)
    await user.click(screen.getByRole('button', { name: 'CCDC6' }))
    await user.click(screen.getByRole('button', { name: 'CCDC6' }))
    // second click passes null — onSelectGene not called with a value the second time
    expect(onSelectGene).toHaveBeenCalledTimes(1)
  })

  it('shows cluster regions when pathwayAnalysis is true', () => {
    render(<DarkGeneScatter pathwayAnalysis />)
    // Appears in both legend and chart label — assert at least one instance
    expect(screen.getAllByText(/core autophagy/i).length).toBeGreaterThanOrEqual(1)
  })
})
