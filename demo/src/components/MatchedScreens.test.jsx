import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import MatchedScreens from './MatchedScreens'
import { MATCHED_SCREENS } from '../mockData'

describe('MatchedScreens', () => {
  it('renders without crashing', () => {
    render(<MatchedScreens genes={[]} />)
    expect(screen.getByText(/top matched screens/i)).toBeInTheDocument()
  })

  it('shows all 8 matched screens', () => {
    render(<MatchedScreens genes={[]} />)
    MATCHED_SCREENS.forEach(s => {
      expect(screen.getByText(s.citation)).toBeInTheDocument()
    })
  })

  it('shows correct significant match count (FDR < 0.05)', () => {
    render(<MatchedScreens genes={[]} />)
    // The "FDR < 5%" note uniquely identifies the significant matches stat card
    expect(screen.getByText('FDR < 5%')).toBeInTheDocument()
  })

  it('shows directionality badges', () => {
    render(<MatchedScreens genes={[]} />)
    expect(screen.getAllByText(/agree/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/inverted/i).length).toBeGreaterThan(0)
  })

  it('shows query gene count from props', () => {
    render(<MatchedScreens genes={Array(24).fill({ symbol: 'X', score: 0 })} />)
    expect(screen.getByText('24')).toBeInTheDocument()
  })

  it('shows the BioGRID IDs', () => {
    render(<MatchedScreens genes={[]} />)
    expect(screen.getByText('ORCS-4421')).toBeInTheDocument()
  })
})
