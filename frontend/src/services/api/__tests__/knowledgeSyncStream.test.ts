import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  startConfluenceSyncStream,
  type ConfluenceSyncStreamEvent,
} from '../knowledge';

const originalFetch = globalThis.fetch;
const originalEventSource = globalThis.EventSource;
const demoEnv = import.meta.env as Record<string, string | undefined>;
const originalDemoFlag = demoEnv.VITE_ALLOW_UNAUTHENTICATED_DEMO_API;

class MockEventSource {
  static instances: MockEventSource[] = [];

  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(public readonly url: string) {
    MockEventSource.instances.push(this);
  }
}

describe('startConfluenceSyncStream', () => {
  beforeEach(() => {
    localStorage.clear();
    MockEventSource.instances = [];
    demoEnv.VITE_ALLOW_UNAUTHENTICATED_DEMO_API = 'false';
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    globalThis.EventSource = originalEventSource;
    demoEnv.VITE_ALLOW_UNAUTHENTICATED_DEMO_API = originalDemoFlag;
    vi.restoreAllMocks();
  });

  it('uses authenticated fetch streaming when a bearer token is present', async () => {
    const encoder = new TextEncoder();
    const events: ConfluenceSyncStreamEvent[] = [];
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                `data: ${JSON.stringify({ type: 'progress', percent: 42, message: 'Syncing' })}\n\n`
              )
            );
            controller.close();
          },
        }),
        { status: 200 }
      )
    );
    globalThis.fetch = fetchMock;
    localStorage.setItem('token', 'jwt-token');

    const handle = startConfluenceSyncStream(
      { space: 'ENG', limit: 25 },
      {
        onEvent: (event) => events.push(event),
        onError: vi.fn(),
      }
    );

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(handle.mode).toBe('fetch');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'GET',
      headers: expect.objectContaining({
        Accept: 'text/event-stream',
        Authorization: 'Bearer jwt-token',
      }),
    });
    expect(events).toEqual([
      expect.objectContaining({ type: 'progress', percent: 42, message: 'Syncing' }),
    ]);

    handle.close();
  });

  it('falls back to EventSource only in explicit demo mode without a bearer token', () => {
    const events: ConfluenceSyncStreamEvent[] = [];
    globalThis.fetch = vi.fn();
    globalThis.EventSource = MockEventSource as unknown as typeof EventSource;
    demoEnv.VITE_ALLOW_UNAUTHENTICATED_DEMO_API = 'true';

    const handle = startConfluenceSyncStream(
      { q: 'PRD' },
      {
        onEvent: (event) => events.push(event),
        onError: vi.fn(),
      }
    );

    expect(handle.mode).toBe('eventsource');
    expect(MockEventSource.instances).toHaveLength(1);
    expect(globalThis.fetch).not.toHaveBeenCalled();

    MockEventSource.instances[0].onmessage?.({
      data: JSON.stringify({ type: 'complete', synced: 3, created: 1, updated: 2 }),
    } as MessageEvent<string>);

    expect(events).toEqual([
      expect.objectContaining({ type: 'complete', synced: 3, created: 1, updated: 2 }),
    ]);

    handle.close();
    expect(MockEventSource.instances[0].close).toHaveBeenCalledTimes(1);
  });
});
