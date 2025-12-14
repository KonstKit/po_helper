/**
 * Smart Defaults System
 *
 * Automatically detects and applies sensible default values based on:
 * - User's browser environment (timezone, locale)
 * - Jira project analysis (sprint duration, working patterns)
 * - Industry best practices
 */

export interface SmartDefaults {
  // General Settings
  sprintDuration: number;          // Days (e.g., 14)
  workingHoursPerDay: number;      // Hours (e.g., 8)
  currency: string;                // ISO code (e.g., "USD")
  timezone: string;                // IANA timezone (e.g., "America/New_York")

  // Dashboard Preferences
  defaultTimeRange: '1month' | '3months' | '6months' | '1year';
  defaultChartView: 'velocity' | 'burndown' | 'both';

  // Analytics Preferences
  preferredMetrics: string[];
}

/**
 * Detect timezone from browser
 */
export function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC'; // Fallback
  }
}

/**
 * Detect locale and currency from browser
 */
export function detectCurrency(): string {
  try {
    const locale = navigator.language || 'en-US';

    // Map common locales to currencies
    const currencyMap: Record<string, string> = {
      'en-US': 'USD',
      'en-GB': 'GBP',
      'en-CA': 'CAD',
      'en-AU': 'AUD',
      'de-DE': 'EUR',
      'fr-FR': 'EUR',
      'es-ES': 'EUR',
      'it-IT': 'EUR',
      'ru-RU': 'RUB',
      'ja-JP': 'JPY',
      'zh-CN': 'CNY',
      'ko-KR': 'KRW',
      'pt-BR': 'BRL',
      'pl-PL': 'PLN',
      'tr-TR': 'TRY',
    };

    // Try exact match
    if (currencyMap[locale]) {
      return currencyMap[locale];
    }

    // Try language prefix (e.g., 'en' from 'en-GB')
    const lang = locale.split('-')[0];
    const prefixMatch = Object.keys(currencyMap).find(key => key.startsWith(lang));
    if (prefixMatch) {
      return currencyMap[prefixMatch];
    }

    return 'USD'; // Fallback to USD
  } catch {
    return 'USD';
  }
}

/**
 * Analyze sprint durations from project data
 * Returns average sprint length in days
 */
export function analyzeSprintDuration(sprints: any[]): number {
  if (!sprints || sprints.length === 0) {
    return 14; // Default 2-week sprints
  }

  const durations: number[] = [];

  for (const sprint of sprints) {
    if (sprint.start_date && sprint.end_date) {
      const start = new Date(sprint.start_date);
      const end = new Date(sprint.end_date);
      const durationMs = end.getTime() - start.getTime();
      const durationDays = Math.round(durationMs / (1000 * 60 * 60 * 24));

      // Filter out unrealistic values (< 5 days or > 30 days)
      if (durationDays >= 5 && durationDays <= 30) {
        durations.push(durationDays);
      }
    }
  }

  if (durations.length === 0) {
    return 14; // No valid sprints, use default
  }

  // Calculate median (more robust than mean for outliers)
  durations.sort((a, b) => a - b);
  const mid = Math.floor(durations.length / 2);
  const median = durations.length % 2 === 0
    ? Math.round((durations[mid - 1] + durations[mid]) / 2)
    : durations[mid];

  // Round to nearest common sprint length (7, 14, 21, 28)
  const commonLengths = [7, 14, 21, 28];
  const closest = commonLengths.reduce((prev, curr) =>
    Math.abs(curr - median) < Math.abs(prev - median) ? curr : prev
  );

  return closest;
}

/**
 * Detect working hours per day from task completion patterns
 * Analyzes time spent on tasks to infer typical work day
 */
export function analyzeWorkingHours(tasks: any[]): number {
  // For now, return standard 8-hour workday
  // In future, could analyze:
  // - Time spent on tasks
  // - Issue timestamps (created/updated times)
  // - Sprint commitment patterns

  return 8; // Standard workday
}

/**
 * Determine preferred metrics based on user role/use case
 */
export function determinePreferredMetrics(useCase?: string): string[] {
  const allMetrics = [
    'velocity',
    'burndown',
    'cycleTime',
    'leadTime',
    'throughput',
    'defectRate',
    'codeReview',
    'testCoverage',
  ];

  // Map use cases to relevant metrics
  switch (useCase) {
    case 'velocity':
      return ['velocity', 'burndown', 'throughput'];

    case 'traceability':
      return ['testCoverage', 'defectRate', 'codeReview'];

    case 'quality':
      return ['defectRate', 'codeReview', 'testCoverage', 'cycleTime'];

    case 'all':
    default:
      return ['velocity', 'burndown', 'cycleTime', 'defectRate'];
  }
}

/**
 * Determine default time range based on project age
 */
export function determineDefaultTimeRange(projectCreatedAt?: string): '1month' | '3months' | '6months' | '1year' {
  if (!projectCreatedAt) {
    return '6months'; // Safe default
  }

  const created = new Date(projectCreatedAt);
  const now = new Date();
  const ageMonths = (now.getTime() - created.getTime()) / (1000 * 60 * 60 * 24 * 30);

  if (ageMonths < 2) {
    return '1month'; // New project, show all data
  } else if (ageMonths < 4) {
    return '3months'; // Young project
  } else if (ageMonths < 12) {
    return '6months'; // Established project
  } else {
    return '1year'; // Mature project, show year for trends
  }
}

/**
 * Generate complete smart defaults
 */
export async function generateSmartDefaults(
  sprints?: any[],
  tasks?: any[],
  projectCreatedAt?: string,
  useCase?: string
): Promise<SmartDefaults> {
  return {
    sprintDuration: analyzeSprintDuration(sprints || []),
    workingHoursPerDay: analyzeWorkingHours(tasks || []),
    currency: detectCurrency(),
    timezone: detectTimezone(),
    defaultTimeRange: determineDefaultTimeRange(projectCreatedAt),
    defaultChartView: 'both',
    preferredMetrics: determinePreferredMetrics(useCase),
  };
}

/**
 * Save smart defaults to localStorage
 */
export function saveSmartDefaults(defaults: SmartDefaults): void {
  try {
    localStorage.setItem('smart_defaults', JSON.stringify(defaults));
  } catch (e) {
    console.error('Failed to save smart defaults:', e);
  }
}

/**
 * Load smart defaults from localStorage
 */
export function loadSmartDefaults(): SmartDefaults | null {
  try {
    const stored = localStorage.getItem('smart_defaults');
    if (stored) {
      return JSON.parse(stored);
    }
  } catch (e) {
    console.error('Failed to load smart defaults:', e);
  }
  return null;
}

/**
 * Apply smart defaults to settings form
 */
export function applyDefaultsToSettings(defaults: SmartDefaults): Record<string, any> {
  return {
    sprintDuration: defaults.sprintDuration,
    workingHoursPerDay: defaults.workingHoursPerDay,
    currency: defaults.currency,
    timezone: defaults.timezone,
  };
}

/**
 * Get default explanation for user
 */
export function explainDefault(field: keyof SmartDefaults, value: any): string {
  const explanations: Record<string, string> = {
    sprintDuration: `Detected from your project's sprint history (${value} days)`,
    workingHoursPerDay: `Standard workday (${value} hours)`,
    currency: `Detected from your browser locale (${value})`,
    timezone: `Detected from your browser (${value})`,
    defaultTimeRange: `Based on project age (${value})`,
    defaultChartView: `Recommended view for balanced insights`,
    preferredMetrics: `Relevant metrics for your use case`,
  };

  return explanations[field] || `Auto-detected: ${value}`;
}
