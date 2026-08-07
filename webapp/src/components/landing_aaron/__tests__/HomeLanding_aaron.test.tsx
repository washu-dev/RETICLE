import { fireEvent, render, screen } from '@testing-library/react';

import HomeLandingAaron from '../HomeLanding_aaron';

/** The page is two doors now, so what is worth asserting changed with it. The old test proved the
 *  mode chip hid the Mouse toggle once you switched to screens; there is no chip to switch. The
 *  right half is no longer a search at all — it is one door into the comparison flow — so what is
 *  worth proving is that each side reaches its own destination and neither reaches the other's. */

function renderLanding(props: Partial<Parameters<typeof HomeLandingAaron>[0]> = {}) {
  const spies = {
    onOpenGene: jest.fn(),
    onStart: jest.fn(),
    onExplore: jest.fn(),
    ...props,
  };
  render(<HomeLandingAaron {...spies} />);
  return spies;
}

const geneBox = () => screen.getByRole('textbox', { name: /search a gene/i });

test('the gene search is the only search on the page', () => {
  renderLanding();
  expect(geneBox()).toBeInTheDocument();
  expect(screen.getAllByRole('textbox')).toHaveLength(1);
});

test('the organism toggle belongs to the gene side only', () => {
  renderLanding();
  // The comparison pool is human-only, so a mouse switch over the screens half would offer
  // something that cannot be delivered. One toggle, on the side it applies to.
  expect(screen.getAllByRole('button', { name: 'Mouse' })).toHaveLength(1);
  expect(screen.getAllByRole('button', { name: 'Human' })).toHaveLength(1);
});

test('a typed gene opens the gene', () => {
  const { onOpenGene } = renderLanding();
  fireEvent.change(geneBox(), { target: { value: 'FANCD2' } });
  fireEvent.submit(geneBox().closest('form')!);
  expect(onOpenGene).toHaveBeenCalledWith('FANCD2', 'human');
});

test('the gene search carries the chosen organism', () => {
  const { onOpenGene } = renderLanding();
  fireEvent.click(screen.getByRole('button', { name: 'Mouse' }));
  fireEvent.change(geneBox(), { target: { value: 'Trp53' } });
  fireEvent.submit(geneBox().closest('form')!);

  expect(onOpenGene).toHaveBeenCalledWith('Trp53', 'mouse');
});

test('the right half is one door into the comparison flow', () => {
  const { onStart, onOpenGene } = renderLanding();
  // The label carries a live count when the API answers and falls back when it does not, so it is
  // matched on the part that never changes.
  fireEvent.click(screen.getByRole('button', { name: /compare/i }));
  expect(onStart).toHaveBeenCalled();
  expect(onOpenGene).not.toHaveBeenCalled();
});
