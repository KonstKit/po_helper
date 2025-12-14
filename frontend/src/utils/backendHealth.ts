import api from '../services/api';

export interface BackendHealthStatus {
  isHealthy: boolean;
  lastChecked: Date;
  error?: string;
  consecutiveFailures: number;
}

class BackendHealthMonitor {
  private status: BackendHealthStatus = {
    isHealthy: true,
    lastChecked: new Date(),
    consecutiveFailures: 0
  };

  private checkInterval: NodeJS.Timer | null = null;
  private readonly CHECK_INTERVAL_MS = 10000; // Check every 10 seconds
  private readonly MAX_CONSECUTIVE_FAILURES = 3;

  /**
   * Start monitoring backend health
   */
  startMonitoring() {
    if (this.checkInterval) {
      return;
    }

    // Initial check
    this.checkHealth();

    // Set up periodic checks
    this.checkInterval = setInterval(() => {
      this.checkHealth();
    }, this.CHECK_INTERVAL_MS);
  }

  /**
   * Stop monitoring backend health
   */
  stopMonitoring() {
    if (this.checkInterval) {
      clearInterval(this.checkInterval);
      this.checkInterval = null;
    }
  }

  /**
   * Manually check backend health
   */
  async checkHealth(): Promise<BackendHealthStatus> {
    try {
      // Increased timeout to handle backend during heavy operations (like Jira sync)
      const response = await api.get('/v1/health/', {
        timeout: 10000 // 10 second timeout for health check
      });

      if (response.data?.status === 'healthy') {
        this.status = {
          isHealthy: true,
          lastChecked: new Date(),
          consecutiveFailures: 0
        };

        // Notify recovery if was previously unhealthy
        if (!this.status.isHealthy) {
          this.notifyHealthChange(true);
        }
      } else {
        throw new Error('Unexpected health response');
      }
    } catch (error: any) {
      this.status.consecutiveFailures++;

      const wasHealthy = this.status.isHealthy;
      this.status.isHealthy = false;
      this.status.lastChecked = new Date();
      this.status.error = error.message || 'Backend health check failed';

      // Notify unhealthy state if threshold reached
      if (wasHealthy && this.status.consecutiveFailures >= this.MAX_CONSECUTIVE_FAILURES) {
        this.notifyHealthChange(false);
      }
    }

    return this.status;
  }

  /**
   * Get current health status without checking
   */
  getStatus(): BackendHealthStatus {
    return { ...this.status };
  }

  /**
   * Notify UI about health state changes
   */
  private notifyHealthChange(isHealthy: boolean) {
    window.dispatchEvent(new CustomEvent('backend-health-change', {
      detail: { isHealthy, status: this.status }
    }));
  }

  /**
   * Force mark backend as unhealthy (useful when requests fail)
   */
  markUnhealthy(error?: string) {
    this.status.isHealthy = false;
    this.status.error = error || 'Backend request failed';
    this.status.consecutiveFailures++;
    this.notifyHealthChange(false);
  }
}

// Singleton instance
export const backendHealthMonitor = new BackendHealthMonitor();

// Auto-start monitoring when module loads
if (typeof window !== 'undefined') {
  backendHealthMonitor.startMonitoring();
}