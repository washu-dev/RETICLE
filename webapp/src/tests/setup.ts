import '@testing-library/jest-dom';

// jsdom has no IntersectionObserver; the dashboard shell uses it for scroll-spy.
class IntersectionObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
}
if (!('IntersectionObserver' in globalThis)) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).IntersectionObserver = IntersectionObserverStub;
}

// jsdom has no fetch either. A component that calls it on mount would otherwise
// throw a ReferenceError out of its effect and take the whole tree down with it,
// which reads as "the component is broken" rather than "there is no server here".
//
// The stub answers as a server that refused, so components take their documented
// failure path and render whatever they fall back to — the state most worth
// asserting in a unit test. It resolves rather than rejects so that a component
// without a .catch() cannot spray unhandled rejections through an unrelated suite.
// A test that wants a real payload overrides globalThis.fetch itself.
if (!('fetch' in globalThis)) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).fetch = () =>
    Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({}) });
}
