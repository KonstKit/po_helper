/**
 * Regression tests for the AnalyticsService transport-queue lifecycle.
 *
 * Cases:
 *   #18 — Long lazy-provisioning window: flush repeatedly gets HTTP 404
 *         (valid JWT, User row not yet created). The pending backlog must
 *         stay bounded by the code's LAZY_PROVISION_CAP and events must be
 *         RETAINED (not dropped) for later replay once provisioning lands.
 *   #19 — Owner change / logout while a batch is pending: the pre-logout
 *         queue must be DROPPED (not replayed) when the owner key mismatches
 *         the newly-signed-in user.
 *
 * The service (`src/services/analytics.ts`) sends batches through
 * `trackEventsBatch` from `./api/usageAnalyticsApi`, so that is the network
 * layer we mock (mirroring the hoisted-mock style of the sibling service
 * tests, e.g. services/api/__tests__/reviewQueueApi.test.ts).
 *
 * Implementation facts these tests pin (read from analytics.ts):
 *   - LAZY_PROVISION_CAP = 1000 (404 branch in flushBatch).
 *   - FLUSH_BATCH_THRESHOLD = 20 (an immediate flush is attempted once the
 *     queue reaches 20 events).
 *   - The owner marker is the FNV-1a hash of `${jwt.sub}|${jwt.tenant_id}`,
 *     persisted under `po_helper_analytics_pending_owner`, and a mismatch
 *     against the live token drops the queue in enqueueForBackend()/flushBatch().
 *
 * The `analytics` export is a singleton built at module import time, and its
 * behaviour depends on the localStorage token/owner present at construction.
 * Each test therefore seeds localStorage first, then re-imports the module
 * with `vi.resetModules()` to get a fresh, correctly-owned singleton.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { trackEventsBatchMock } = vi.hoisted(() => ({
  trackEventsBatchMock: vi.fn(),
}));

// Mock the network/post layer the service imports. analytics.ts calls
// `trackEventsBatch(events)` directly; we intercept it here so no axios /
// fetch traffic is attempted.
vi.mock('../api/usageAnalyticsApi', () => ({
  trackEventsBatch: trackEventsBatchMock,
  // trackEvent is part of the module surface but unused by the singleton.
  trackEvent: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** The cap the 404 branch enforces in analytics.ts. */
const LAZY_PROVISION_CAP = 1000;
/** The immediate-flush threshold in analytics.ts. */
const FLUSH_BATCH_THRESHOLD = 20;

const PENDING_BATCH_KEY = 'po_helper_analytics_pending';
const PENDING_OWNER_KEY = 'po_helper_analytics_pending_owner';


/** A rejection shaped like the axios errors the service inspects. */
function httpError(status: number): Error & { response: { status: number } } {
  const err = new Error(`HTTP ${status}`) as Error & {
    response: { status: number };
  };
  err.response = { status };
  return err;
}

/**
 * Re-import the analytics module so the singleton is rebuilt against the
 * localStorage state we just seeded (the constructor reads the token + owner).
 */
async function freshAnalytics() {
  vi.resetModules();
  const mod = await import('../analytics');
  return mod.analytics;
}

/**
 * Yield to the microtask queue a few times so fire-and-forget flushes
 * (`void this.flushBatch()` started inside track()) settle their rejected
 * promises and run their catch/finally blocks before we assert.
 */
async function drainMicrotasks(times = 5): Promise<void> {
  for (let i = 0; i < times; i++) {
    await Promise.resolve();
  }
}

/**
 * Pre-seed the time-to-value baselines so `seedBaselinesIfMissing()` (invoked
 * on the FIRST track() after login) does not enqueue its own synthetic
 * `time_to_value_milestone` events. Without this, the first track() would add
 * two extra events to the queue and break the exact-count assertions below.
 * Must be called after the token is set and before the first track().
 */
function seedTtvBaselines(): void {
  const now = Date.now();
  localStorage.setItem('account_created_at', String(now));
  localStorage.setItem('first_login_at', String(now));
  localStorage.setItem(
    'time_to_value_metrics',
    JSON.stringify({ accountCreatedAt: now, firstLoginAt: now }),
  );
}

/** Current persisted pending batch length (localStorage mirror). */
function persistedBatchLength(): number {
  const raw = localStorage.getItem(PENDING_BATCH_KEY);
  if (!raw) return 0;
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.length : 0;
  } catch {
    return 0;
  }
}

describe('AnalyticsService transport-queue lifecycle', () => {
  // The service intentionally logs via console.error on the 404 / network /
  // owner-mismatch branches we exercise. Silence it so the output stays clean
  // (and so the optional DASHBOARD_GATE in test/setup.ts is not tripped by
  // these expected diagnostics).
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // jsdom localStorage is not provisioned for this suite in some workers;
    // provide a minimal in-memory shim so lifecycle assertions stay stable.
    if (typeof localStorage === 'undefined') {
      const store = new Map<string, string>();
      vi.stubGlobal('localStorage', {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, String(v)),
        removeItem: (k: string) => void store.delete(k),
        clear: () => void store.clear(),
      });
    }
    localStorage.clear();
    trackEventsBatchMock.mockReset();
    vi.useRealTimers();
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
    vi.useRealTimers();
    vi.resetModules();
  });

  // -------------------------------------------------------------------------
  // #18 — Long lazy-provisioning (repeated 404) keeps the backlog bounded
  //       and retains events for replay.
  // -------------------------------------------------------------------------
  it('#18 bounds the pending backlog under repeated 404 and retains events for replay', async () => {
    // Signed-in user (valid JWT) but backend keeps returning 404 — the
    // lazy-provisioning window where the User row does not exist yet.
    seedTtvBaselines();
    const analytics = await freshAnalytics();
    analytics.setConfirmedSessionOwner('user-lazy');
    analytics.setSessionOwner('user-lazy');

    // Every flush during the window 404s.
    trackEventsBatchMock.mockRejectedValue(httpError(404));

    // Emit far more events than the cap. Each track() enqueues and, once the
    // queue crosses FLUSH_BATCH_THRESHOLD, attempts an immediate flush that
    // 404s and reschedules. flushBatch is awaited explicitly after the loop
    // to deterministically exercise the 404 trim path without relying on the
    // debounce timer.
    const TOTAL = LAZY_PROVISION_CAP + 500; // 1500
    for (let i = 0; i < TOTAL; i++) {
      analytics.track('lazy_event', { i });
    }

    // Drive several flush cycles; each rejects with 404. track() already
    // fired an immediate flush at the threshold, so we first drain that
    // in-flight rejection, then run explicit rounds so the 404 branch is hit
    // and the cap is enforced once the queue exceeds it.
    for (let round = 0; round < 6; round++) {
      await analytics.flushBatch();
      await drainMicrotasks();
    }

    // The network layer WAS exercised (we did not silently swallow at the
    // client) and only ever rejected — nothing was acknowledged.
    expect(trackEventsBatchMock).toHaveBeenCalled();

    // The backlog must NOT grow unbounded: capped at LAZY_PROVISION_CAP.
    // Inspect the persisted transport queue (localStorage is source of truth).
    const persisted = persistedBatchLength();
    expect(persisted).toBeGreaterThan(0); // events RETAINED, not dropped
    expect(persisted).toBeLessThanOrEqual(LAZY_PROVISION_CAP);
    // With 1500 events and a 1000 cap, the queue should have been trimmed to
    // exactly the cap (keeping the most recent events).
    expect(persisted).toBe(LAZY_PROVISION_CAP);

    // Now provisioning completes: the next flush succeeds and drains the
    // retained backlog, proving the events were preserved for replay.
    trackEventsBatchMock.mockReset();
    trackEventsBatchMock.mockResolvedValue({ accepted: persisted, receivedAt: Date.now() });
    await analytics.flushBatch();

    // The retained events were replayed (sent) under the same identity, and
    // the queue drained.
    expect(trackEventsBatchMock).toHaveBeenCalledTimes(1);
    const sentEvents = trackEventsBatchMock.mock.calls[0][0] as unknown[];
    expect(sentEvents.length).toBe(LAZY_PROVISION_CAP);
    expect(persistedBatchLength()).toBe(0);
  });

  it('#18b keeps the queue intact when a 404 batch is still below the cap', async () => {
    // A short provisioning blip well under the cap must lose nothing.
    seedTtvBaselines();
    const analytics = await freshAnalytics();
    analytics.setConfirmedSessionOwner('user-lazy');
    analytics.setSessionOwner('user-lazy');

    trackEventsBatchMock.mockRejectedValue(httpError(404));

    const COUNT = FLUSH_BATCH_THRESHOLD + 5; // 25 — above threshold, below cap
    for (let i = 0; i < COUNT; i++) {
      analytics.track('small_lazy_event', { i });
    }
    await analytics.flushBatch();
    await drainMicrotasks();

    // Below the cap → every event retained, none trimmed.
    expect(persistedBatchLength()).toBe(COUNT);
  });

  // -------------------------------------------------------------------------
  // #19 — Logout / different owner while a batch is pending: drop the queue.
  // -------------------------------------------------------------------------
  it('#19 drops the pending queue on flush when a different owner has signed in', async () => {
    // User A enqueues events while the server is unreachable (network error
    // keeps them queued), so a backlog is persisted under owner A.
    seedTtvBaselines();
    const analytics = await freshAnalytics();
    analytics.setConfirmedSessionOwner('user-A');
    analytics.setSessionOwner('user-A');

    trackEventsBatchMock.mockRejectedValue(new Error('network down'));
    for (let i = 0; i < 3; i++) {
      analytics.track('owner_a_event', { i });
    }
    await analytics.flushBatch(); // 5xx/network branch retains the queue
    await drainMicrotasks();

    const ownerA = localStorage.getItem(PENDING_OWNER_KEY);
    expect(ownerA).toBeTruthy();
    expect(persistedBatchLength()).toBe(3);

    // A DIFFERENT user signs in on the same tab: the owner identity is
    // switched explicitly (JWT storage M2: setSessionOwner).
    analytics.setConfirmedSessionOwner('user-B');
    analytics.setSessionOwner('user-B');

    // The next flush detects the owner mismatch and DROPS the pre-login queue
    // rather than replaying user A's events under user B.
    trackEventsBatchMock.mockReset();
    trackEventsBatchMock.mockResolvedValue({ accepted: 0, receivedAt: Date.now() });
    await analytics.flushBatch();

    // User A's events were NOT sent under user B...
    expect(trackEventsBatchMock).not.toHaveBeenCalled();
    // ...and the persisted queue + owner marker were cleared.
    expect(persistedBatchLength()).toBe(0);
    expect(localStorage.getItem(PENDING_BATCH_KEY)).toBeNull();
    expect(localStorage.getItem(PENDING_OWNER_KEY)).toBeNull();
  });

  it('#19b drops the inherited queue on the next enqueue under a different owner', async () => {
    // Same setup: a backlog persisted under owner A.
    seedTtvBaselines();
    const analytics = await freshAnalytics();
    analytics.setConfirmedSessionOwner('user-A');
    analytics.setSessionOwner('user-A');

    trackEventsBatchMock.mockRejectedValue(new Error('network down'));
    for (let i = 0; i < 3; i++) {
      analytics.track('owner_a_event', { i });
    }
    await analytics.flushBatch();
    await drainMicrotasks();
    expect(persistedBatchLength()).toBe(3);
    const ownerA = localStorage.getItem(PENDING_OWNER_KEY);
    expect(ownerA).toBeTruthy();

    // User B signs in, then tracks a NEW event. enqueueForBackend() must
    // discard the stale owner-A backlog BEFORE appending B's event, so the
    // persisted queue only ever contains B's own event(s).
    // User B signs in and takes over the session owner identity.
    analytics.setConfirmedSessionOwner('user-B');
    analytics.setSessionOwner('user-B');
    trackEventsBatchMock.mockReset();
    trackEventsBatchMock.mockRejectedValue(new Error('still down')); // keep B's event queued for inspection

    analytics.track('owner_b_event', { x: 1 });

    // Owner A's 3 events were dropped; only B's single event remains queued.
    expect(persistedBatchLength()).toBe(1);
    // The persisted owner marker now belongs to B (differs from A's).
    const ownerB = localStorage.getItem(PENDING_OWNER_KEY);
    expect(ownerB).toBeTruthy();
    expect(ownerB).not.toBe(ownerA);
  });

  it('#19e rejects an ownerless persisted batch on flush after login', async () => {
    // Cold-start 401 cleanup preserves the batch but strips its owner
    // marker: it cannot be attributed, so flushing after login must drop
    // it instead of transmitting user A's events under user B.
    localStorage.setItem(
      PENDING_BATCH_KEY,
      JSON.stringify([{ eventName: 'orphan_event', eventData: { i: 1 }, timestamp: Date.now() }]),
    );
    localStorage.removeItem(PENDING_OWNER_KEY);
    const analytics = await freshAnalytics();
    analytics.setConfirmedSessionOwner('user-B');
    analytics.setSessionOwner('user-B');
    trackEventsBatchMock.mockResolvedValue({ accepted: 0, receivedAt: Date.now() });

    await analytics.flushBatch();

    expect(trackEventsBatchMock).not.toHaveBeenCalled();
    expect(persistedBatchLength()).toBe(0);
  });

  it("#19h cleanup persistence retains the batch original owner, so a re-login cannot transmit it", async () => {
    // Cold-load user A"s OWNED queue (batch + owner marker), then the
    // probe establishes user B in the same tab. The auth-error cleanup
    // re-persists the batch: it must keep A"s original owner identity,
    // never re-stamp it with B, so B"s flush drops it.
    const markerA = "owner-a-hash";
    localStorage.setItem(
      PENDING_BATCH_KEY,
      JSON.stringify([{ eventName: "a_event", eventData: {}, timestamp: Date.now() }]),
    );
    localStorage.setItem(PENDING_OWNER_KEY, markerA);
    const analytics = await freshAnalytics();
    analytics.setConfirmedSessionOwner("user-B");
    analytics.setSessionOwner("user-B");

    analytics.persistPendingBatchToStorage();
    expect(localStorage.getItem(PENDING_OWNER_KEY)).toBe(markerA);

    // B"s flush must drop the batch (owner mismatch) instead of sending.
    trackEventsBatchMock.mockResolvedValue({ accepted: 0, receivedAt: Date.now() });
    await analytics.flushBatch();
    expect(trackEventsBatchMock).not.toHaveBeenCalled();
    expect(persistedBatchLength()).toBe(0);
  });

  it("#19g cleanup persistence does not stamp an ownerless batch with the new owner", async () => {
    localStorage.setItem(
      PENDING_BATCH_KEY,
      JSON.stringify([{ eventName: 'orphan_event', eventData: { i: 1 }, timestamp: Date.now() }]),
    );
    localStorage.removeItem(PENDING_OWNER_KEY);
    const analytics = await freshAnalytics();
    analytics.setConfirmedSessionOwner('user-B');
    analytics.setSessionOwner('user-B');
    // auth-error cleanup re-persists the in-memory batch (App.tsx).
    analytics.persistPendingBatchToStorage();

    // The persisted queue must remain ownerless; user B signs in and the
    // flush rejects it instead of transmitting user A's events.
    expect(localStorage.getItem(PENDING_OWNER_KEY)).toBeNull();
    trackEventsBatchMock.mockResolvedValue({ accepted: 0, receivedAt: Date.now() });
    await analytics.flushBatch();
    expect(trackEventsBatchMock).not.toHaveBeenCalled();
    expect(persistedBatchLength()).toBe(0);
  });

  it('#19f drops an ownerless persisted batch on enqueue after login', async () => {
    localStorage.setItem(
      PENDING_BATCH_KEY,
      JSON.stringify([{ eventName: 'orphan_event', eventData: { i: 1 }, timestamp: Date.now() }]),
    );
    localStorage.removeItem(PENDING_OWNER_KEY);
    const analytics = await freshAnalytics();
    analytics.setConfirmedSessionOwner('user-B');
    analytics.setSessionOwner('user-B');

    analytics.track('b_event', { x: 1 });
    await analytics.flushBatch();

    const sent = trackEventsBatchMock.mock.calls[0]?.[0] as unknown[] | undefined;
    const names = (sent ?? []).map((e) => (e as { eventName?: string }).eventName ?? '?');
    // The ownerless orphan batch was dropped; only user-B events remain.
    expect(names).not.toContain('orphan_event');
    expect(names).toContain('b_event');
    console.log('DBG sent types:', (sent ?? []).map((e) => (e as { type: string }).type).join(','));
  });

  it('#19c resetForLogout drops the pending queue entirely (explicit logout)', async () => {
    // Explicit logout is the hard-wipe path: even the same user must not have
    // unsent events replayed after an intentional sign-out.
    seedTtvBaselines();
    const analytics = await freshAnalytics();
    analytics.setConfirmedSessionOwner('user-A');
    analytics.setSessionOwner('user-A');

    trackEventsBatchMock.mockRejectedValue(new Error('network down'));
    for (let i = 0; i < 4; i++) {
      analytics.track('pre_logout_event', { i });
    }
    await analytics.flushBatch();
    await drainMicrotasks();
    expect(persistedBatchLength()).toBe(4);

    analytics.resetForLogout();

    expect(persistedBatchLength()).toBe(0);
    expect(localStorage.getItem(PENDING_BATCH_KEY)).toBeNull();
    expect(localStorage.getItem(PENDING_OWNER_KEY)).toBeNull();
  });
});
