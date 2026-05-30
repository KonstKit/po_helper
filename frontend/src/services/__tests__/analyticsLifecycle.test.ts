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

/**
 * Build an unsigned JWT whose payload carries `sub` (+ optional tenant_id).
 * The service decodes the payload (base64url) without verifying the
 * signature, so a dummy header/signature is fine. btoa is provided by jsdom.
 */
function makeToken(sub: string, tenantId?: string): string {
  const payload: Record<string, string> = { sub };
  if (tenantId !== undefined) payload.tenant_id = tenantId;
  const b64url = (s: string) =>
    btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  const header = b64url(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const body = b64url(JSON.stringify(payload));
  return `${header}.${body}.sig`;
}

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
    localStorage.setItem('token', makeToken('user-lazy', 'tenant-1'));
    seedTtvBaselines();
    const analytics = await freshAnalytics();

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
    localStorage.setItem('token', makeToken('user-lazy', 'tenant-1'));
    seedTtvBaselines();
    const analytics = await freshAnalytics();

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
    localStorage.setItem('token', makeToken('user-A', 'tenant-A'));
    seedTtvBaselines();
    const analytics = await freshAnalytics();

    trackEventsBatchMock.mockRejectedValue(new Error('network down'));
    for (let i = 0; i < 3; i++) {
      analytics.track('owner_a_event', { i });
    }
    await analytics.flushBatch(); // 5xx/network branch retains the queue
    await drainMicrotasks();

    const ownerA = localStorage.getItem(PENDING_OWNER_KEY);
    expect(ownerA).toBeTruthy();
    expect(persistedBatchLength()).toBe(3);

    // A DIFFERENT user signs in on the same tab (token swapped). The owner
    // marker derived from the new JWT no longer matches the persisted one.
    localStorage.setItem('token', makeToken('user-B', 'tenant-B'));

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
    localStorage.setItem('token', makeToken('user-A', 'tenant-A'));
    seedTtvBaselines();
    const analytics = await freshAnalytics();

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
    localStorage.setItem('token', makeToken('user-B', 'tenant-B'));
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

  it('#19c resetForLogout drops the pending queue entirely (explicit logout)', async () => {
    // Explicit logout is the hard-wipe path: even the same user must not have
    // unsent events replayed after an intentional sign-out.
    localStorage.setItem('token', makeToken('user-A', 'tenant-A'));
    seedTtvBaselines();
    const analytics = await freshAnalytics();

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
