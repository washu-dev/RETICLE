import { fireEvent, render, screen } from '@testing-library/react';

import HomeLandingAaron from '../HomeLanding_aaron';

/** The page is two doors now, so what is worth asserting changed with it. The old test proved the
 *  mode chip hid the Mouse toggle once you switched to screens; there is no chip to switch, and the
 *  toggle only ever exists on the gene side. What matters instead is that the two sides are
 *  genuinely separate — that neither box can send you to the other half's destination. */

function renderLanding(props: Partial<Parameters<typeof HomeLandingAaron>[0]> = {}) {
  const spies = {
    onOpenGene: jest.fn(),
    onOpenScreen: jest.fn(),
    onStart: jest.fn(),
    onExplore: jest.fn(),
    ...props,
  };
  render(<HomeLandingAaron {...spies} />);
  return spies;
}

const geneBox = () => screen.getByRole('textbox', { name: /search a gene/i });
const screenBox = () => screen.getByRole('textbox', { name: /published screen/i });

test('offers a gene search and a screen search at the same time', () => {
  renderLanding();
  expect(geneBox()).toBeInTheDocument();
  expect(screenBox()).toBeInTheDocument();
});

test('the organism toggle belongs to the gene side only', () => {
  renderLanding();
  // The comparison pool is human-only, so a mouse switch over the screens half would offer
  // something that cannot be delivered. One toggle, on the side it applies to.
  expect(screen.getAllByRole('button', { name: 'Mouse' })).toHaveLength(1);
  expect(screen.getAllByRole('button', { name: 'Human' })).toHaveLength(1);
});

test('a typed gene opens the gene, and never the screen half', () => {
  const { onOpenGene, onOpenScreen } = renderLanding();
  fireEvent.change(geneBox(), { target: { value: 'FANCD2' } });
  fireEvent.submit(geneBox().closest('form')!);

  expect(onOpenGene).toHaveBeenCalledWith('FANCD2', 'human');
  expect(onOpenScreen).not.toHaveBeenCalled();
});

test('the gene search carries the chosen organism', () => {
  const { onOpenGene } = renderLanding();
  fireEvent.click(screen.getByRole('button', { name: 'Mouse' }));
  fireEvent.change(geneBox(), { target: { value: 'Trp53' } });
  fireEvent.submit(geneBox().closest('form')!);

  expect(onOpenGene).toHaveBeenCalledWith('Trp53', 'mouse');
});

test('a typed screen opens the screen, and never the gene half', () => {
  const { onOpenGene, onOpenScreen } = renderLanding();
  fireEvent.change(screenBox(), { target: { value: '1544' } });
  fireEvent.submit(screenBox().closest('form')!);

  expect(onOpenScreen).toHaveBeenCalledWith('1544');
  expect(onOpenGene).not.toHaveBeenCalled();
});

test('the example genes open without anything being typed', () => {
  const { onOpenGene } = renderLanding();
  fireEvent.click(screen.getByRole('button', { name: 'TP53' }));
  expect(onOpenGene).toHaveBeenCalledWith('TP53', 'human');
});

test('bringing your own screen is a separate door from searching for one', () => {
  const { onStart, onOpenScreen } = renderLanding();
  fireEvent.click(screen.getByRole('button', { name: /bring your own screen/i }));
  expect(onStart).toHaveBeenCalled();
  expect(onOpenScreen).not.toHaveBeenCalled();
});
