import React from 'react';
import { render, screen } from '@testing-library/react';
import Header from '../Header';

describe('Header', () => {
  it('renders header with title', () => {
    render(<Header />);
    const title = screen.getByText('RETICLE');
    expect(title).toBeInTheDocument();
  });

  it('renders subtitle', () => {
    render(<Header />);
    const subtitle = screen.getByText('CRISPR Screen Analysis Platform');
    expect(subtitle).toBeInTheDocument();
  });

  it('renders navigation links', () => {
    render(<Header />);
    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.getByText('About')).toBeInTheDocument();
    expect(screen.getByText('Contact')).toBeInTheDocument();
  });

  it('has proper semantic structure', () => {
    render(<Header />);
    const header = screen.getByRole('banner');
    expect(header).toBeInTheDocument();
  });
});
