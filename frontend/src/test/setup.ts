import { afterEach, beforeEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

const isDashboardGate = process.env.DASHBOARD_GATE === '1';

let consoleErrorSpy: ReturnType<typeof vi.spyOn> | null = null;

if (isDashboardGate) {
  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });
}

// Cleanup after each test
afterEach(() => {
  const errorSpy = consoleErrorSpy;
  let cleanupError: unknown = null;

  try {
    cleanup();
  } catch (error) {
    cleanupError = error;
  }

  const gateCalls =
    isDashboardGate && errorSpy
      ? errorSpy.mock.calls
      : [];
  const hasGateError = gateCalls.length > 0;
  const rendered = hasGateError
    ? gateCalls.map((call) => call.map((entry) => String(entry)).join(' ')).join('\n')
    : '';

  errorSpy?.mockRestore();
  consoleErrorSpy = null;

  if (hasGateError) {
    const cleanupDetails =
      cleanupError !== null
        ? `\ncleanup-error: ${String(cleanupError)}`
        : '';
    throw new Error(
      `dashboard-gate: console.error was called\n${rendered}${cleanupDetails}`
    );
  }

  if (cleanupError !== null) {
    throw cleanupError;
  }
});

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock IntersectionObserver
class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin = '';
  readonly thresholds: ReadonlyArray<number> = [];

  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
  unobserve() {}
}

global.IntersectionObserver = MockIntersectionObserver;

// Mock ResizeObserver
class MockResizeObserver implements ResizeObserver {
  constructor() {}
  disconnect() {}
  observe(_target: Element, _options?: unknown) {
    void _target;
    void _options;
  }
  unobserve(_target: Element) {
    void _target;
  }
}

global.ResizeObserver = MockResizeObserver;
