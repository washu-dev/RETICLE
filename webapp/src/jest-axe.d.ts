declare module 'jest-axe' {
  import type { RawResult } from 'axe-core';

  export function axe(element: Element): Promise<RawResult>;

  export const toHaveNoViolations: {
    toHaveNoViolations(results: RawResult): { pass: boolean; message(): string };
  };
}
