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

// jsdom in some vitest workers does not provision localStorage; provide a
// minimal Storage-compatible implementation whose stored keys are own
// enumerable properties (matching browser behavior, so code that does
// Object.keys(localStorage) to enumerate feature_* markers keeps working).
if (typeof localStorage === "undefined") {
  const store = new Map<string, string>();
  const shim: Record<string, unknown> = {};
  Object.defineProperties(shim, {
    getItem: {
      value: (k: string) => (store.has(k) ? store.get(k)! : null),
      enumerable: false,
    },
    setItem: {
      value: (k: string, v: string) => {
        store.set(k, String(v));
        Object.defineProperty(shim, k, {
          value: String(v),
          enumerable: true,
          configurable: true,
          writable: true,
        });
      },
      enumerable: false,
    },
    removeItem: {
      value: (k: string) => {
        store.delete(k);
        delete (shim as Record<string, unknown>)[k];
      },
      enumerable: false,
    },
    clear: {
      value: () => {
        store.clear();
        for (const k of Object.keys(shim)) {
          if (k !== "getItem" && k !== "setItem" && k !== "removeItem" && k !== "clear" && k !== "key" && k !== "length") {
            delete (shim as Record<string, unknown>)[k];
          }
        }
      },
      enumerable: false,
    },
    key: {
      value: (i: number) => Array.from(store.keys())[i] ?? null,
      enumerable: false,
    },
    length: {
      get: () => store.size,
      enumerable: false,
    },
  });
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    get() {
      return shim as unknown as Storage;
    },
  });
}

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
