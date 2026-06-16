import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import GreetingDisplay from '../GreetingDisplay';
import * as apiModule from '../../services/api';

jest.mock('../../services/api');

describe('GreetingDisplay', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders loading state initially', () => {
    (apiModule.apiGet as jest.Mock).mockImplementation(
      () => new Promise(() => {})
    );
    render(<GreetingDisplay />);
    expect(screen.getByText('Loading greeting message...')).toBeInTheDocument();
  });

  it('renders greeting message on success', async () => {
    const mockMessage = { message: 'Welcome to RETICLE' };
    (apiModule.apiGet as jest.Mock).mockResolvedValue(mockMessage);

    render(<GreetingDisplay />);
    await waitFor(() => {
      expect(screen.getByText('Welcome to RETICLE')).toBeInTheDocument();
    });
  });

  it('renders error message on failure', async () => {
    (apiModule.apiGet as jest.Mock).mockRejectedValue(new Error('Network error'));

    render(<GreetingDisplay />);
    await waitFor(() => {
      expect(screen.getByText('Failed to load greeting message')).toBeInTheDocument();
    });
  });

  it('has proper ARIA attributes', () => {
    (apiModule.apiGet as jest.Mock).mockImplementation(
      () => new Promise(() => {})
    );
    render(<GreetingDisplay />);
    const section = screen.getByRole('region');
    expect(section).toHaveAttribute('aria-live', 'polite');
  });
});
