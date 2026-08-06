import { fireEvent, render, screen } from '@testing-library/react';

import HomeLandingAaron from '../HomeLanding_aaron';


function renderLanding() {
  render(
    <HomeLandingAaron
      onOpenGene={jest.fn()}
      onOpenScreen={jest.fn()}
      onStart={jest.fn()}
      onExplore={jest.fn()}
    />
  );
}


test('screen mode exposes the supported human comparison scope', () => {
  renderLanding();
  expect(screen.getByRole('button', { name: 'Mouse' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /Gene/ }));
  fireEvent.click(screen.getByRole('menuitem', { name: /Screen/ }));

  expect(screen.getByText('Human comparison pool · 962 supported screens')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Mouse' })).not.toBeInTheDocument();
});
