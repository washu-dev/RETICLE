import { reticleInitialSearch } from '../vendor/reticleBundle_aaron';

describe('reticleInitialSearch', () => {
  test('opens a mouse gene wiki with the mouse taxonomy', () => {
    expect(reticleInitialSearch('gene', 'Trp53', 'mouse')).toBe('?gene=Trp53&taxid=10090');
  });

  test('opens a mouse gene directly in the mouse network', () => {
    expect(reticleInitialSearch('network', 'Trp53', 'mouse')).toBe(
      '?gene=Trp53&organism=mouse',
    );
  });

  test('hands a screen id to the screen-comparison deep link', () => {
    expect(reticleInitialSearch('screen', '2123')).toBe('?screen=2123');
  });
});
