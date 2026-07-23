import { render, screen } from '@testing-library/react';
import Provenance, { ProvenanceLegend, ProvMark } from '../Provenance';

describe('Provenance', () => {
  test('renders each kind with its default label', () => {
    const { rerender } = render(<Provenance kind="ai" />);
    expect(screen.getByText('AI-generated · di2')).toBeInTheDocument();
    rerender(<Provenance kind="computed" />);
    expect(screen.getByText('Computed')).toBeInTheDocument();
    rerender(<Provenance kind="source" />);
    expect(screen.getByText('Source')).toBeInTheDocument();
  });

  test('renders an override label and sub clarifier', () => {
    render(<Provenance kind="computed" label="Estimated" sub="uncalibrated" />);
    expect(screen.getByText('Estimated')).toBeInTheDocument();
    expect(screen.getByText('— uncalibrated')).toBeInTheDocument();
  });

  test('the legend explains all three marks', () => {
    render(<ProvenanceLegend />);
    expect(screen.getByText('AI-generated')).toBeInTheDocument();
    expect(screen.getByText('Computed')).toBeInTheDocument();
    expect(screen.getByText('Source')).toBeInTheDocument();
  });

  test('ProvMark renders an inline svg (no emoji)', () => {
    const { container } = render(<ProvMark kind="ai" />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });
});
