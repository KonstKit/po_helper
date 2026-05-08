/**
 * Usage Analytics API client.
 *
 * Sends product usage events (page views, onboarding milestones, time-to-value)
 * to the backend `/api/v1/usage-analytics` endpoints. Used by the singleton
 * AnalyticsService in `services/analytics.ts` for batched flushes.
 *
 * NOTE: Unrelated to `services/api/analytics.ts`, which exposes business
 * analytics (velocity, burndown, DORA, etc.).
 */
import api from './client';

export interface UsageAnalyticsEvent {
  eventName: string;
  eventData?: Record<string, unknown>;
  timestamp: number;
  sessionId?: string;
}

export interface TrackResponse {
  accepted: number;
  receivedAt: number;
}

export async function trackEvent(event: UsageAnalyticsEvent): Promise<TrackResponse> {
  const { data } = await api.post<TrackResponse>('/v1/usage-analytics/track', event);
  return data;
}

export async function trackEventsBatch(
  events: UsageAnalyticsEvent[],
): Promise<TrackResponse> {
  const { data } = await api.post<TrackResponse>(
    '/v1/usage-analytics/track/batch',
    { events },
  );
  return data;
}
