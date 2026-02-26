/**
 * Analytics Service
 * Tracks user behavior, onboarding progress, and feature adoption
 */

export interface AnalyticsEvent {
  eventName: string;
  eventData?: Record<string, unknown>;
  timestamp: number;
  userId?: string;
  sessionId?: string;
}

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

  constructor() {
    this.sessionId = this.generateSessionId();
    this.loadEvents();
  }

  private generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  private loadEvents(): void {
    try {
      const stored = localStorage.getItem(this.storageKey);
      if (stored) {
        this.events = JSON.parse(stored);
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

  /**
   * Track a user event
   */
  track(eventName: string, eventData?: Record<string, unknown>): void {
    const event: AnalyticsEvent = {
      eventName,
      eventData,
      timestamp: Date.now(),
      sessionId: this.sessionId,
    };

    this.events.push(event);
    this.saveEvents();

    // In production, send to analytics backend
    if (process.env.NODE_ENV === 'production') {
      this.sendToBackend(event);
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
  trackTimeToValue(milestone: keyof TimeToValueMetrics): void {
    const metricsKey = 'time_to_value_metrics';
    let metrics: TimeToValueMetrics = this.getTimeToValueMetrics();

    metrics[milestone] = Date.now();
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
   * Clear all analytics data
   */
  clear(): void {
    localStorage.removeItem(this.storageKey);
    localStorage.removeItem('onboarding_metrics');
    localStorage.removeItem('time_to_value_metrics');

    // Clear feature visits
    const keys = Object.keys(localStorage);
    keys.forEach(key => {
      if (key.startsWith('feature_') && key.endsWith('_visited')) {
        localStorage.removeItem(key);
      }
    });

    this.events = [];
  }

  /**
   * Send event to backend (in production)
   */
  private async sendToBackend(event: AnalyticsEvent): Promise<void> {
    void event;
    try {
      // In production, send to analytics backend
      // await fetch('/api/analytics/track', {
      //   method: 'POST',
      //   headers: { 'Content-Type': 'application/json' },
      //   body: JSON.stringify(event),
      // });
    } catch (e) {
      console.error('Failed to send analytics event:', e);
    }
  }
}

// Export singleton instance
export const analytics = new AnalyticsService();
