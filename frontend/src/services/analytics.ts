/**
 * Analytics Service
 * Tracks user behavior, onboarding progress, and feature adoption.
 *
 * Events are buffered in localStorage (offline fallback) and flushed in
 * batches to /api/v1/usage-analytics/track/batch.
 */
import { trackEventsBatch } from './api/usageAnalyticsApi';

export interface AnalyticsEvent {
  eventName: string;
  eventData?: Record<string, unknown>;
  timestamp: number;
  userId?: string;
  sessionId?: string;
}

const FLUSH_INTERVAL_MS = 10_000;
const FLUSH_BATCH_THRESHOLD = 20;

export interface OnboardingMetrics {
  started: boolean;
  startedAt?: number;
  completed: boolean;
  completedAt?: number;
  currentStep?: number;
  totalSteps: number;
  skipped: boolean;
  stepsCompleted: number[];
}

export interface TimeToValueMetrics {
  accountCreatedAt?: number;
  firstLoginAt?: number;
  jiraConnectedAt?: number;
  firstSyncAt?: number;
  firstProjectViewedAt?: number;
  firstTaskViewedAt?: number;
}

export interface FeatureAdoptionMetrics {
  features: {
    dashboard: { visited: boolean; lastVisit?: number };
    projects: { visited: boolean; lastVisit?: number };
    tasks: { visited: boolean; lastVisit?: number };
    analytics: { visited: boolean; lastVisit?: number };
    knowledge: { visited: boolean; lastVisit?: number };
    quality: { visited: boolean; lastVisit?: number };
    testing: { visited: boolean; lastVisit?: number };
    traceability: { visited: boolean; lastVisit?: number };
    jiraFields: { visited: boolean; lastVisit?: number };
    sprintCapacity: { visited: boolean; lastVisit?: number };
  };
  adoptionRate: number; // 0-1
}

interface OnboardingActionData {
  totalSteps?: number;
  step?: number;
  [key: string]: unknown;
}

class AnalyticsService {
  private events: AnalyticsEvent[] = [];
  private sessionId: string;
  private storageKey = 'po_helper_analytics';
  private pendingBatchKey = 'po_helper_analytics_pending';
  private pendingOwnerKey = 'po_helper_analytics_pending_owner';
  // Owner marker recorded by softResetForAuthError() and consulted at the
  // next login by dropInheritedStateIfOwnerChanged(). Persisted (rather
  // than only in memory) so a cross-user signin survives a page reload
  // between the 401 cleanup and the next login.
  private previousOwnerKey = 'po_helper_analytics_previous_owner';
  private pendingBatch: AnalyticsEvent[] = [];
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private flushInFlight = false;
  // Set when resetForLogout() runs while a flush is in progress. The catch
  // block must not requeue events captured before the logout — otherwise
  // they would be re-sent under the next account that signs in.
  private logoutDuringFlight = false;
  // Dynamic per-flush cap. Lowered (halved) whenever the server returns
  // 413 so we converge under ANALYTICS_BATCH_MAX_SIZE; reset to null on
  // the first successful flush so we go back to flushing the whole queue.
  private maxFlushSize: number | null = null;
  // Owner marker captured at softResetForAuthError() — kept so that, after
  // performAuthErrorCleanup() wipes the token via clearLocalStorage(),
  // savePendingBatch() can still stamp the persisted queue with the owner
  // it belonged to. Without this fallback the next user on the same tab
  // would see no owner marker and inherit the previous user's queue.
  private cachedOwnerMarker: string | null = null;

  constructor() {
    this.sessionId = this.generateSessionId();
    this.loadEvents();
    this.loadPendingBatch();
    // Only resume the timer on startup when we already have a token. Without
    // it, an immediate flush would 401 and drop the persisted batch — losing
    // events that should survive across browser restart / re-auth. The next
    // tracked event after login will re-arm the timer via enqueueForBackend.
    if (this.pendingBatch.length > 0 && this.hasAuthToken()) {
      this.scheduleFlush();
    }
    // Cleanup on auth invalidation is orchestrated by utils/logout
    // (performAuthErrorCleanup invokes softResetForAuthError;
    // performLogout invokes resetForLogout). The singleton no longer
    // self-subscribes to 'auth-error' — that would double-fire with
    // utils/logout and could race with localStorage clears.
    //
    // Register a synchronous owner-marker snapshot hook on window so the
    // axios interceptor (services/api/client.ts) can capture the queue
    // owner BEFORE it removes the token, without creating a static
    // import cycle (client → analytics → usageAnalyticsApi → client).
    if (typeof window !== 'undefined') {
      window.__poAnalyticsSnapshotOwner = () => this.snapshotOwnerForAuthError();
    }
  }

  private hasAuthToken(): boolean {
    if (typeof window === 'undefined') return false;
    try {
      return Boolean(localStorage.getItem('token'));
    } catch {
      return false;
    }
  }

  /**
   * Stable identifier for the *current* token holder, used to mark the
   * persisted pending batch with its owner. Returns null when there is no
   * token (e.g. on the login screen).
   *
   * Derived from the JWT `sub` claim (the user identity) AND the
   * `tenant_id` claim (when present). Hashing both prevents two distinct
   * tenants that share a `sub` (the same person signing into different
   * tenants) from being treated as the same owner — otherwise a queue or
   * UI state from tenant A would leak into tenant B after a re-auth.
   *
   * Using a derived claim rather than the raw bearer string keeps the
   * marker stable across same-user re-login (a fresh JWT has a different
   * signature/iat but the same sub+tenant_id pair).
   *
   * Decoding here is *unverified* (no signature check). That is fine for
   * a local-only owner marker: a tampered token cannot be used against
   * the backend, the marker never leaves the browser, and the worst case
   * is dropping a backlog earlier than necessary.
   */
  private currentOwnerMarker(): string | null {
    if (typeof window === 'undefined') return null;
    try {
      const token = localStorage.getItem('token');
      if (!token) return null;
      const payload = this.extractJwtPayload(token);
      const sub = typeof payload?.sub === 'string' ? payload.sub : null;
      if (!sub) return null;
      const tenantId =
        typeof payload?.tenant_id === 'string' ? payload.tenant_id : '';
      return this.fnv1aHash(`${sub}|${tenantId}`);
    } catch {
      return null;
    }
  }

  /**
   * Synchronously capture the owner marker derived from the live token,
   * called by the axios interceptor immediately before it removes the
   * token on a 401. The cached marker is consumed later by
   * `softResetForAuthError()` (queue-stamping during cleanup) and by the
   * fallback in `currentOwnerMarker()`'s callers, so that even when the
   * `auth-error` listener fires after the token is gone, the persisted
   * pending queue still carries the previous owner's stamp.
   */
  snapshotOwnerForAuthError(): void {
    const marker = this.currentOwnerMarker();
    if (marker) this.cachedOwnerMarker = marker;
  }

  private extractJwtPayload(token: string): Record<string, unknown> | null {
    const parts = token.split('.');
    if (parts.length < 2) return null;
    try {
      const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
      const pad = '='.repeat((4 - (b64.length % 4)) % 4);
      const json = atob(b64 + pad);
      const parsed = JSON.parse(json);
      return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }

  private fnv1aHash(input: string): string {
    // Tiny non-cryptographic hash (FNV-1a). We only need stable equality,
    // not collision resistance — the marker never leaves the browser.
    let h = 0x811c9dc5;
    for (let i = 0; i < input.length; i++) {
      h ^= input.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h.toString(16);
  }

  private cancelFlushCycle(): void {
    if (this.flushTimer !== null) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    if (this.flushInFlight) {
      this.logoutDuringFlight = true;
    }
  }

  /**
   * Wipe per-user UI analytics state without touching the backend transport
   * queue. Used on 401 / session expiry, where the same user may sign back
   * in and we want the queued events to survive. Public so it can be
   * orchestrated by the auth-error cleanup path in utils/logout.
   */
  softResetForAuthError(): void {
    // The axios interceptor (services/api/client.ts) calls
    // snapshotOwnerForAuthError() *before* removing the token, which
    // populates `cachedOwnerMarker`. By the time this runs, the token is
    // already gone, so currentOwnerMarker() typically returns null. Use
    // the snapshot as a fallback so we always have an owner to persist.
    const liveOwner = this.currentOwnerMarker() ?? this.cachedOwnerMarker;
    if (liveOwner) {
      this.cachedOwnerMarker = liveOwner;
      // Persist for cross-reload comparison at the next login. The
      // auth-error path keeps `previousOwnerKey` through clearLocalStorage
      // (see utils/logout.ts), and dropInheritedStateIfOwnerChanged()
      // consumes it after the new token is set.
      try {
        localStorage.setItem(this.previousOwnerKey, liveOwner);
      } catch {
        // localStorage write can fail in private/quota-limited contexts;
        // a missing previous owner just means we cannot detect cross-user
        // signin, which falls back to "trust the new login" behavior.
      }
    }
    this.cancelFlushCycle();
    this.resetUiState();
  }

  /**
   * After login, schedule a flush if there is a preserved pending batch.
   * Without this, the same-user re-auth path (or a cold start with a
   * persisted queue) would leave events sitting in localStorage forever
   * because the flush timer is only re-armed by `enqueueForBackend()`.
   */
  resumePendingFlushIfAny(): void {
    if (this.pendingBatch.length > 0 && this.hasAuthToken()) {
      this.scheduleFlush();
    }
  }

  /**
   * Drop UI analytics state inherited from a previous user when a new
   * login establishes a different owner on the same tab. Call after a
   * fresh token has been written to localStorage (Login flow,
   * loginSuccess reducer). The owner-marker logic on the backend
   * transport queue already covers `pendingBatch`; this method covers
   * the localStorage-only UI state (onboarding completion, TTV
   * baselines, first-view markers) that those guards do not protect.
   */
  dropInheritedStateIfOwnerChanged(): void {
    if (typeof window === 'undefined') return;
    let previous: string | null = null;
    try {
      previous = localStorage.getItem(this.previousOwnerKey);
    } catch {
      previous = null;
    }
    const current = this.currentOwnerMarker();
    if (!previous || !current) {
      // No previous record (no recent auth-error) or no current token
      // (call ordering issue) — clear the marker either way; nothing to
      // do until softResetForAuthError records a fresh one.
      try {
        localStorage.removeItem(this.previousOwnerKey);
      } catch {
        // ignore
      }
      return;
    }
    if (previous === current) {
      // Same user re-authenticated; preserved keys belong to them.
      try {
        localStorage.removeItem(this.previousOwnerKey);
      } catch {
        // ignore
      }
      return;
    }
    // Different user. Wipe inherited per-user UI state and the backend
    // transport queue (the previous owner's pending batch must not flush
    // under the new account, but that is also enforced by the owner
    // marker check inside flushBatch — wiping here is belt-and-braces).
    try {
      // Persisted raw event log. Without this, the next page reload by
      // the new user would `loadEvents()` the previous user's history
      // back into memory, and the dashboard's "Export Local Cache" /
      // session-duration widgets would keep showing stale data until
      // new events overwrite it.
      localStorage.removeItem(this.storageKey);
      localStorage.removeItem('onboarding_metrics');
      localStorage.removeItem('onboarding_progress');
      localStorage.removeItem('onboarding_completed');
      localStorage.removeItem('account_created_at');
      localStorage.removeItem('first_login_at');
      localStorage.removeItem('time_to_value_metrics');
      localStorage.removeItem(this.pendingBatchKey);
      localStorage.removeItem(this.pendingOwnerKey);
      const keys: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && (k.startsWith('first_view_') || (k.startsWith('feature_') && k.endsWith('_visited')))) {
          keys.push(k);
        }
      }
      keys.forEach((k) => localStorage.removeItem(k));
      localStorage.removeItem(this.previousOwnerKey);
    } catch (e) {
      console.error('Failed to drop inherited analytics state:', e);
    }
    this.pendingBatch = [];
    this.cachedOwnerMarker = null;
    this.events = [];
  }

  /**
   * Re-write the current in-memory pendingBatch (and owner marker) to
   * localStorage. Used by `performAuthErrorCleanup` after the broad
   * `clearLocalStorage()` step, which deletes everything matching
   * `/analytics_/`. This restores the transport queue from the singleton's
   * authoritative in-memory state, which is also race-safe: if a flush
   * completed during cleanup, splice already shrank the queue and we
   * persist the smaller version (no duplicate delivery on next session).
   */
  persistPendingBatchToStorage(): void {
    this.savePendingBatch();
  }

  private resetUiState(): void {
    // Critically uses clearLocalUiCache() (not clear()) so the backend
    // transport queue survives forced 401 / session expiry. clear() does
    // a full wipe and is reserved for explicit logout.
    // preserveSessionInvariant=true keeps onboarding completion and raw
    // TTV baselines so an already-onboarded user that re-authenticates in
    // the same tab is not pushed back through the wizard.
    this.clearLocalUiCache({ preserveSessionInvariant: true });
    // Do NOT rotate sessionId here. Backend aggregates onboarding attempts
    // by session_id; if a token expires mid-onboarding and we issue a
    // fresh sessionId, the resumed wizard would emit `onboarding_started`
    // under a new id and the same real attempt becomes two backend
    // sessions, depressing completion-rate and drop-off metrics. Explicit
    // logout uses a different path (`resetForLogout`) that DOES rotate.
  }

  /**
   * Clear all per-user analytics state on logout.
   *
   * Called from `performLogout` and on 'auth-error'. Wipes every channel
   * that could leak the previous user's activity into the next session
   * within the same tab (no hard refresh):
   *   - in-memory `events` log + persisted `storageKey`
   *   - in-memory `pendingBatch` + persisted `pendingBatchKey`
   *   - onboarding/TTV/feature-adoption localStorage entries (via `clear()`)
   *   - `first_view_*` markers (or PageViewTracker would never re-emit
   *     `firstProjectViewedAt`/`firstTaskViewedAt` for the next user)
   *   - active flush timer
   *   - `sessionId` (regenerated, so subsequent events start a fresh session)
   *
   * Any unsent events are dropped intentionally — they belonged to the
   * previous session and would cross-attribute to the next user on flush.
   */
  resetForLogout(): void {
    this.cancelFlushCycle();
    // Full wipe — UI cache *and* backend transport queue. Explicit logout
    // means "this session is over"; the next user must not inherit any
    // unsent events or first-view markers.
    this.clear();
    this.sessionId = this.generateSessionId();
  }

  private clearFirstViewMarkers(options: { preserveSessionInvariant?: boolean } = {}): void {
    if (options.preserveSessionInvariant) {
      // Keep first_view_* markers across same-user re-auth: PageViewTracker
      // uses them to gate firstProjectViewedAt / firstTaskViewedAt, and
      // wiping them here would let the next /projects or /tasks visit
      // overwrite the preserved TTV milestones with re-login timestamps.
      return;
    }
    try {
      const keys: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith('first_view_')) {
          keys.push(key);
        }
      }
      keys.forEach((k) => localStorage.removeItem(k));
    } catch (e) {
      console.error('Failed to clear first-view markers:', e);
    }
  }

  private generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  private loadEvents(): void {
    try {
      const stored = localStorage.getItem(this.storageKey);
      if (stored) {
        // Guard against non-array JSON (e.g. {}, 0, a partial/legacy write):
        // without this, this.events becomes a non-array and the next track()
        // throws on this.events.push(...), breaking analytics for the session.
        const parsed = JSON.parse(stored);
        this.events = Array.isArray(parsed) ? parsed : [];
      }
    } catch (e) {
      console.error('Failed to load analytics events:', e);
      this.events = [];
    }
  }

  private saveEvents(): void {
    try {
      // Keep only last 1000 events to prevent localStorage bloat
      const recentEvents = this.events.slice(-1000);
      localStorage.setItem(this.storageKey, JSON.stringify(recentEvents));
    } catch (e) {
      console.error('Failed to save analytics events:', e);
    }
  }

  private loadPendingBatch(): void {
    try {
      const stored = localStorage.getItem(this.pendingBatchKey);
      if (!stored) {
        this.pendingBatch = [];
        return;
      }
      // If the persisted batch was written by a different account, drop it
      // — replaying it under the new bearer token would cross-attribute
      // product analytics. We only enforce this when both markers exist;
      // a legitimate first-time load on the same browser may have a saved
      // batch with no owner (legacy data) — keep that for retry.
      const owner = localStorage.getItem(this.pendingOwnerKey);
      const currentOwner = this.currentOwnerMarker();
      if (owner && currentOwner && owner !== currentOwner) {
        console.warn(
          'Discarding persisted analytics batch: owner mismatch (different account)',
        );
        localStorage.removeItem(this.pendingBatchKey);
        localStorage.removeItem(this.pendingOwnerKey);
        this.pendingBatch = [];
        return;
      }
      const parsed = JSON.parse(stored);
      this.pendingBatch = Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      console.error('Failed to load pending analytics batch:', e);
      this.pendingBatch = [];
    }
  }

  private savePendingBatch(): void {
    try {
      if (this.pendingBatch.length === 0) {
        localStorage.removeItem(this.pendingBatchKey);
        localStorage.removeItem(this.pendingOwnerKey);
        // Empty queue means there is no owner to remember anymore.
        this.cachedOwnerMarker = null;
        return;
      }
      localStorage.setItem(this.pendingBatchKey, JSON.stringify(this.pendingBatch));
      // Prefer the live JWT-derived marker; fall back to the cached one
      // captured by softResetForAuthError() before the token was wiped.
      // Without the fallback, a non-empty queue persisted after auth-
      // error cleanup would have no owner stamp and the next user on
      // the tab would inherit it via the (owner && currentOwner) guard
      // short-circuiting to "allow".
      const owner = this.currentOwnerMarker() ?? this.cachedOwnerMarker;
      if (owner) {
        localStorage.setItem(this.pendingOwnerKey, owner);
      }
    } catch (e) {
      console.error('Failed to persist pending analytics batch:', e);
    }
  }

  /**
   * Track a user event
   */
  track(eventName: string, eventData?: Record<string, unknown>): void {
    // Re-create local TTV baselines if they were wiped by resetForLogout.
    // App.tsx seeds `account_created_at` / `first_login_at` only on a
    // mount-effect, so a same-tab logout→login cycle (no remount) would
    // leave them blank and the local time-to-first-value UI would not
    // recover until a hard refresh.
    this.seedBaselinesIfMissing();

    const event: AnalyticsEvent = {
      eventName,
      eventData,
      timestamp: Date.now(),
      sessionId: this.sessionId,
    };

    this.events.push(event);
    this.saveEvents();
    this.enqueueForBackend(event);
  }

  private seedBaselinesIfMissing(): void {
    if (!this.hasAuthToken()) return;
    try {
      const now = Date.now();
      const readPreserved = (key: string): number | undefined => {
        const raw = localStorage.getItem(key);
        if (!raw) return undefined;
        const parsed = Number(raw);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
      };

      const preservedCreated = readPreserved('account_created_at');
      const preservedFirstLogin = readPreserved('first_login_at');

      // Persist raw baseline keys so the next reseed (after Clear Local Cache)
      // can recover the original timestamps instead of resetting them to "now".
      if (preservedCreated === undefined) {
        localStorage.setItem('account_created_at', String(now));
      }
      if (preservedFirstLogin === undefined) {
        localStorage.setItem('first_login_at', String(now));
      }

      // Each trackTimeToValue() call re-enters track() and updates
      // localStorage, so we must reload the metrics object between checks
      // — otherwise we would emit a duplicate firstLoginAt right after
      // emitting accountCreatedAt (the in-memory copy `ttv` would still
      // see firstLoginAt as missing).
      let ttv = this.getTimeToValueMetrics();
      if (!ttv.accountCreatedAt) {
        this.trackTimeToValue('accountCreatedAt', preservedCreated);
        ttv = this.getTimeToValueMetrics();
      }
      // AnalyticsDashboard reads firstLoginAt from time_to_value_metrics,
      // not from the raw `first_login_at` key, so we must explicitly emit
      // it through trackTimeToValue() rather than only setting the raw
      // localStorage entry above.
      if (!ttv.firstLoginAt) {
        this.trackTimeToValue('firstLoginAt', preservedFirstLogin);
      }
    } catch (e) {
      console.error('Failed to seed TTV baselines:', e);
    }
  }

  /**
   * Track page view
   */
  pageView(pageName: string): void {
    this.track('page_view', { page: pageName });

    // Update feature adoption metrics
    const adoptionKey = `feature_${pageName}_visited`;
    localStorage.setItem(adoptionKey, Date.now().toString());
  }

  /**
   * Track onboarding progress
   */
  trackOnboarding(
    action: 'started' | 'step_completed' | 'completed' | 'skipped',
    data?: OnboardingActionData
  ): void {
    const metricsKey = 'onboarding_metrics';
    let metrics: OnboardingMetrics = this.getOnboardingMetrics();

    switch (action) {
      case 'started':
        // Rotate the analytics sessionId for every fresh onboarding
        // attempt. Backend onboarding aggregation keys attempts on
        // `user_id|session_id`; without a rotation here, retries within
        // the same browser tab (skip → reopen wizard) would collapse
        // into the original attempt and skew startedCount /
        // completionRate / dropOffStep. Mid-attempt 401 re-auth keeps
        // the existing sessionId via resetUiState (no `started` event
        // is emitted on resume), so the same real attempt stays as one
        // backend session.
        this.sessionId = this.generateSessionId();
        metrics = {
          started: true,
          startedAt: Date.now(),
          completed: false,
          totalSteps: data?.totalSteps || 6,
          skipped: false,
          stepsCompleted: [],
        };
        break;

      case 'step_completed':
        if (typeof data?.step === 'number') {
          if (!metrics.stepsCompleted.includes(data.step)) {
            metrics.stepsCompleted.push(data.step);
          }
          metrics.currentStep = data.step;
        }
        break;

      case 'completed':
        metrics.completed = true;
        metrics.completedAt = Date.now();
        localStorage.setItem('onboarding_completed', 'true');
        break;

      case 'skipped':
        metrics.skipped = true;
        localStorage.setItem('onboarding_completed', 'true');
        break;
    }

    localStorage.setItem(metricsKey, JSON.stringify(metrics));
    this.track(`onboarding_${action}`, data);
  }

  /**
   * Get onboarding metrics
   */
  getOnboardingMetrics(): OnboardingMetrics {
    try {
      const stored = localStorage.getItem('onboarding_metrics');
      if (stored) {
        return JSON.parse(stored);
      }
    } catch (e) {
      console.error('Failed to load onboarding metrics:', e);
    }

    return {
      started: false,
      completed: false,
      totalSteps: 6,
      skipped: false,
      stepsCompleted: [],
    };
  }

  /**
   * Track time-to-value milestones
   */
  trackTimeToValue(
    milestone: keyof TimeToValueMetrics,
    overrideTimestampMs?: number,
  ): void {
    const metricsKey = 'time_to_value_metrics';
    const metrics: TimeToValueMetrics = this.getTimeToValueMetrics();

    metrics[milestone] =
      typeof overrideTimestampMs === 'number' && Number.isFinite(overrideTimestampMs)
        ? overrideTimestampMs
        : Date.now();
    localStorage.setItem(metricsKey, JSON.stringify(metrics));
    this.track('time_to_value_milestone', { milestone });
  }

  /**
   * Get time-to-value metrics
   */
  getTimeToValueMetrics(): TimeToValueMetrics {
    try {
      const stored = localStorage.getItem('time_to_value_metrics');
      if (stored) {
        return JSON.parse(stored);
      }
    } catch (e) {
      console.error('Failed to load time-to-value metrics:', e);
    }

    return {};
  }

  /**
   * Calculate time-to-first-value (in minutes)
   */
  getTimeToFirstValue(): number | null {
    const metrics = this.getTimeToValueMetrics();
    if (!metrics.accountCreatedAt || !metrics.firstSyncAt) {
      return null;
    }

    return Math.round((metrics.firstSyncAt - metrics.accountCreatedAt) / 60000);
  }

  /**
   * Get feature adoption metrics
   */
  getFeatureAdoptionMetrics(): FeatureAdoptionMetrics {
    const features = {
      dashboard: this.getFeatureVisit('dashboard'),
      projects: this.getFeatureVisit('projects'),
      tasks: this.getFeatureVisit('tasks'),
      analytics: this.getFeatureVisit('analytics'),
      knowledge: this.getFeatureVisit('knowledge'),
      quality: this.getFeatureVisit('quality'),
      testing: this.getFeatureVisit('testing'),
      traceability: this.getFeatureVisit('traceability'),
      jiraFields: this.getFeatureVisit('jira-fields'),
      sprintCapacity: this.getFeatureVisit('sprint-capacity'),
    };

    const visitedCount = Object.values(features).filter(f => f.visited).length;
    const adoptionRate = visitedCount / Object.keys(features).length;

    return { features, adoptionRate };
  }

  private getFeatureVisit(feature: string): { visited: boolean; lastVisit?: number } {
    const key = `feature_${feature}_visited`;
    const lastVisit = localStorage.getItem(key);

    if (lastVisit) {
      return { visited: true, lastVisit: parseInt(lastVisit, 10) };
    }

    return { visited: false };
  }

  /**
   * Get onboarding completion rate
   */
  getOnboardingCompletionRate(): number {
    const metrics = this.getOnboardingMetrics();
    if (!metrics.started) {
      return 0;
    }

    return metrics.stepsCompleted.length / metrics.totalSteps;
  }

  /**
   * Get session duration (in minutes)
   */
  getSessionDuration(): number {
    const sessionStart = this.events.find(e => e.sessionId === this.sessionId);
    if (!sessionStart) {
      return 0;
    }

    return Math.round((Date.now() - sessionStart.timestamp) / 60000);
  }

  /**
   * Export analytics data
   */
  exportData(): {
    onboarding: OnboardingMetrics;
    timeToValue: TimeToValueMetrics;
    featureAdoption: FeatureAdoptionMetrics;
    events: AnalyticsEvent[];
    sessionDuration: number;
  } {
    return {
      onboarding: this.getOnboardingMetrics(),
      timeToValue: this.getTimeToValueMetrics(),
      featureAdoption: this.getFeatureAdoptionMetrics(),
      events: this.events,
      sessionDuration: this.getSessionDuration(),
    };
  }

  /**
   * Clear local UI analytics cache only (events log, onboarding/TTV/
   * feature-visit/first_view markers, sessionId is left to the caller).
   *
   * Does NOT touch the backend transport queue (`pendingBatch` /
   * `pendingBatchKey` / `pendingOwnerKey`). Use this from the dashboard
   * "Clear Local Cache" button and from forced 401 cleanup so that
   * unsent telemetry is not silently dropped.
   *
   * `preserveSessionInvariant=true` keeps user-level UI markers
   * (onboarding completion, raw TTV baselines) so that a same-user re-auth
   * after a 401 does not push an already-onboarded user back through the
   * wizard or reset their TTV baseline. Use it from the auth-error path,
   * NOT from the explicit "Clear Local Cache" button.
   */
  clearLocalUiCache(options: { preserveSessionInvariant?: boolean } = {}): void {
    const { preserveSessionInvariant = false } = options;
    try {
      localStorage.removeItem(this.storageKey);
      // onboarding_metrics is a derived aggregate that gets recomputed
      // from raw onboarding_* events, so it is safe to drop in both modes.
      localStorage.removeItem('onboarding_metrics');
      if (!preserveSessionInvariant) {
        // Per-user UI state. Wiping these resets the onboarding wizard and
        // the TTV baseline, which is the contract of the dashboard
        // "Clear Local Cache" button. The auth-error path passes
        // preserveSessionInvariant so a returning user sees their
        // onboarded state survive a session expiry.
        localStorage.removeItem('time_to_value_metrics');
        localStorage.removeItem('onboarding_progress');
        localStorage.removeItem('onboarding_completed');
        localStorage.removeItem('account_created_at');
        localStorage.removeItem('first_login_at');
      }
      // Note: when preserveSessionInvariant is true we keep
      // `time_to_value_metrics` because it stores already-achieved local
      // milestones (firstSyncAt, firstProjectViewedAt, ...). Discarding it
      // would silently roll those back until the actions happen again.
      const keys = Object.keys(localStorage);
      keys.forEach(key => {
        if (key.startsWith('feature_') && key.endsWith('_visited')) {
          localStorage.removeItem(key);
        }
      });
    } catch (e) {
      console.error('Failed to clear local UI analytics cache:', e);
    }
    this.events = [];
    this.clearFirstViewMarkers({ preserveSessionInvariant });
  }

  /**
   * Full reset: UI cache plus backend transport queue.
   *
   * Use this only when the session is genuinely over (explicit logout from
   * UI, or `resetForLogout()`). On forced 401 / session-expiry, prefer
   * `clearLocalUiCache()` so a same-user re-auth still drains queued
   * events.
   */
  clear(): void {
    this.clearLocalUiCache();
    try {
      localStorage.removeItem(this.pendingBatchKey);
      localStorage.removeItem(this.pendingOwnerKey);
    } catch (e) {
      console.error('Failed to clear analytics transport queue:', e);
    }
    this.pendingBatch = [];
    // Explicit logout invalidates any cached owner — the next user must
    // not reuse a stale marker.
    this.cachedOwnerMarker = null;
  }

  /**
   * Queue an event for the next backend flush.
   *
   * The flush is debounced: events accumulate in `pendingBatch` and are sent
   * either when the batch reaches FLUSH_BATCH_THRESHOLD or after
   * FLUSH_INTERVAL_MS of inactivity. localStorage is the source of truth and
   * is preserved as offline fallback even after a successful flush.
   */
  private enqueueForBackend(event: AnalyticsEvent): void {
    // Backend track endpoints are auth-only. If the user is not signed in,
    // do not buffer events for the backend at all — the local `events` log
    // (in `track`) still keeps them for client-side dashboards. This both
    // avoids 401 retry loops and prevents cross-attribution to the next
    // user who logs in on the same browser.
    if (!this.hasAuthToken()) {
      return;
    }

    // If the persisted batch was written by a previous account on this
    // browser (the token changed since loadPendingBatch), drop it BEFORE
    // appending — otherwise savePendingBatch below would rewrite the
    // owner marker and the next flush would attribute pre-login events
    // to the new user.
    const owner = localStorage.getItem(this.pendingOwnerKey);
    const currentOwner = this.currentOwnerMarker();
    if (owner && currentOwner && owner !== currentOwner) {
      console.warn(
        'Discarding pending analytics batch on enqueue: owner mismatch (different account)',
      );
      this.pendingBatch = [];
      try {
        localStorage.removeItem(this.pendingBatchKey);
        localStorage.removeItem(this.pendingOwnerKey);
      } catch (e) {
        console.error('Failed to clear stale pending batch:', e);
      }
    }

    this.pendingBatch.push(event);
    this.savePendingBatch();

    if (this.pendingBatch.length >= FLUSH_BATCH_THRESHOLD) {
      // Try to flush immediately; this is a no-op if a flush is already in
      // flight, so we still need the timer below as a safety net.
      void this.flushBatch();
    }

    // Always ensure a timer is armed so events do not strand if the immediate
    // flush is suppressed (in-flight) or fails.
    this.scheduleFlush();
  }

  private scheduleFlush(): void {
    if (this.flushTimer !== null) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      void this.flushBatch();
    }, FLUSH_INTERVAL_MS);
  }

  /**
   * Flush queued events to the backend. Failures are swallowed so analytics
   * never blocks user-facing flows; events remain in localStorage.
   */
  async flushBatch(): Promise<void> {
    if (this.flushInFlight || this.pendingBatch.length === 0) {
      return;
    }
    // No token → don't even hit the network. Keep the batch persisted so it
    // survives until the user re-authenticates. We deliberately do NOT
    // re-arm a timer here: the next enqueueForBackend after login will
    // restart the cycle. (If we re-armed, we'd burn CPU polling on the
    // login screen.)
    if (!this.hasAuthToken()) {
      if (this.flushTimer !== null) {
        clearTimeout(this.flushTimer);
        this.flushTimer = null;
      }
      return;
    }
    // Re-check owner against the persisted marker. If the token rotated to
    // a different account between load and now (rare but possible across
    // multi-tab login flows), drop the batch instead of replaying it.
    const owner = localStorage.getItem(this.pendingOwnerKey);
    const currentOwner = this.currentOwnerMarker();
    if (owner && currentOwner && owner !== currentOwner) {
      console.warn(
        'Dropping pending analytics batch on flush: owner mismatch (different account)',
      );
      this.pendingBatch = [];
      this.savePendingBatch();
      if (this.flushTimer !== null) {
        clearTimeout(this.flushTimer);
        this.flushTimer = null;
      }
      return;
    }
    if (this.flushTimer !== null) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }

    // Snapshot, but DO NOT remove from pendingBatch yet. If the tab closes
    // or the browser crashes mid-request, localStorage still holds the
    // events so they get retried on the next session. We trade a possible
    // duplicate (request reached the server but we never saw the response)
    // for guaranteed durability.
    //
    // `maxFlushSize` (set on prior 413) caps how many events we send this
    // round. The remainder stays in pendingBatch and is retried next time.
    const limit = this.maxFlushSize ?? this.pendingBatch.length;
    const batch = this.pendingBatch.slice(0, limit);
    const sentCount = batch.length;
    this.flushInFlight = true;
    this.logoutDuringFlight = false;
    try {
      await trackEventsBatch(
        batch.map(({ eventName, eventData, timestamp, sessionId }) => ({
          eventName,
          eventData,
          timestamp,
          sessionId,
        })),
      );
      // Success: drop the items we sent. We must splice even if a logout
      // raced this in-flight request — the server has already accepted
      // those events, so leaving them in pendingBatch would cause
      // duplicate delivery on next re-auth. The split between
      // "transport queue" (resetForLogout drops) and
      // "soft reset" (auth-error keeps) decides what happens to the
      // remainder of the queue, but the *sent* slice is gone either way.
      this.pendingBatch.splice(0, sentCount);
      this.savePendingBatch();
      // Successful round: relax the dynamic cap back to "flush whatever
      // is queued", in case the server limit was raised again.
      this.maxFlushSize = null;
      if (this.logoutDuringFlight) {
        // Auth cleanup already happened; do not re-arm a timer.
        // resetForLogout (full logout) cleared pendingBatch above; for
        // softResetForAuthError the remainder stays for same-user re-auth.
        return;
      }
      if (this.pendingBatch.length > 0) {
        this.scheduleFlush();
      }
    } catch (e) {
      if (this.logoutDuringFlight) {
        // User logged out while this flush was in flight. resetForLogout
        // already cleared the queue; do NOT restore the snapshot — those
        // events belong to the previous session.
        console.error(
          'Analytics flush failed during logout; dropping pre-logout batch:',
          e,
        );
        return;
      }
      // 401 / session invalidation: axios interceptor already cleared the
      // token and emitted 'auth-error'. Keep the events queued — owner-marker
      // (`pendingOwnerKey`) is keyed on the JWT `sub` claim, which is stable
      // across same-user re-auth. If the same user signs back in we replay;
      // if a different user signs in, the owner mismatch in
      // enqueueForBackend()/flushBatch() will drop the queue at that point.
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 401) {
        console.error('Analytics flush failed with 401; preserving queue for re-auth:', e);
        return;
      }
      if (status === 413) {
        // Backend rejected the batch as too large (typically because
        // ANALYTICS_BATCH_MAX_SIZE was lowered below the current backlog).
        // Don't drop events: just halve the dynamic per-flush cap so the
        // next attempt sends a smaller chunk. The remaining events stay
        // in pendingBatch and get retried on the next scheduleFlush.
        // Convergent: a few iterations bring the per-flush size under
        // the server limit, then the queue drains in chunks.
        const newLimit = Math.max(1, Math.floor(sentCount / 2));
        this.maxFlushSize = newLimit;
        console.error(
          `Analytics batch too large (${sentCount}); shrinking per-flush cap to ${newLimit}:`,
          e,
        );
        this.scheduleFlush();
        return;
      }
      // 404 = lazy-provisioning window: JWT valid but the User row does not
      // exist yet. Preserve the backlog (no aggressive 200-event truncation)
      // so events emitted before provisioning are flushed later under the same
      // identity. But still BOUND it: a token that is never provisioned would
      // otherwise grow pendingBatch (and its localStorage mirror) without limit
      // and retry forever. Keep the most recent events at a generous cap, since
      // this window is expected to resolve once the User row appears.
      if (status === 404) {
        const LAZY_PROVISION_CAP = 1000;
        if (this.pendingBatch.length > LAZY_PROVISION_CAP) {
          this.pendingBatch = this.pendingBatch.slice(-LAZY_PROVISION_CAP);
        }
        this.savePendingBatch();
        console.error(
          'Analytics flush 404 (lazy provisioning); preserving recent backlog:',
          e,
        );
        this.scheduleFlush();
        return;
      }
      // Other 4xx (e.g. 422 from server-side validation, 400 from a malformed
      // payload): the batch is unrecoverable as-is. If we keep retrying, a
      // single poison event at the head of the queue blocks every later
      // flush forever. Drop the sent slice and let the rest of the queue
      // proceed. Better to lose one batch than freeze telemetry indefinitely.
      // 429 (rate limit) is transient — leave it on the retry path below.
      if (
        typeof status === 'number'
        && status >= 400
        && status < 500
        && status !== 429
      ) {
        this.pendingBatch.splice(0, sentCount);
        this.savePendingBatch();
        console.error(
          `Analytics flush dropped ${sentCount} event(s) due to client error ${status}:`,
          e,
        );
        // Continue draining the queue if there is more behind the poison batch.
        if (this.pendingBatch.length > 0) this.scheduleFlush();
        return;
      }
      // Network / 5xx / timeout: leave events in pendingBatch for retry.
      // Cap to avoid unbounded growth on long outages.
      if (this.pendingBatch.length > 200) {
        this.pendingBatch = this.pendingBatch.slice(-200);
      }
      this.savePendingBatch();
      console.error('Failed to flush analytics batch:', e);
      // Reschedule a retry without requiring a new tracked event.
      this.scheduleFlush();
    } finally {
      this.flushInFlight = false;
      this.logoutDuringFlight = false;
    }
  }
}

// Export singleton instance
export const analytics = new AnalyticsService();
