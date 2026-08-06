import { toReticleOrganism } from './organism';

describe('toReticleOrganism', () => {
  test.each(['Mouse', 'mouse', 'Mus musculus', '10090'])(
    'maps %s to the mouse route',
    (value) => expect(toReticleOrganism(value)).toBe('mouse'),
  );

  test.each(['Human', 'Homo sapiens', 'Both', undefined])(
    'keeps %s on the human default',
    (value) => expect(toReticleOrganism(value)).toBe('human'),
  );
});
