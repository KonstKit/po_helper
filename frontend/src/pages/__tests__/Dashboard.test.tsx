import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach, vi } from 'vitest';
import '../../test/setup-env';
import { render, screen, waitFor, fireEvent, act, within, waitForElementToBeRemoved } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { MemoryRouter } from 'react-router-dom';

import Dashboard from '../Dashboard';
import {
  DASHBOARD_DEFAULTS,
  DASHBOARD_STORAGE_CONTRACT,
  DASHBOARD_STORAGE_KEYS,
  DASHBOARD_TEST_IDS,
} from '../dashboard/dashboardContract';
import { DASHBOARD_GUARDRAIL_TARGETS, isDashboardChartWarning } from '../dashboard/dashboardGuardrails';
import authReducer from '../../store/authSlice';
import projectReducer, { setCurrentProject } from '../../store/projectSlice';
import taskReducer from '../../store/taskSlice';
import sprintReducer from '../../store/sprintSlice';
import {
  listProjects,
  listTasksPaginated,
  listSprints,
  getProjectBudgetHours,
  getProjectValueMetrics,
  getProjectById,
  getSprintBurndown,
  getSprintWipStatus,
  getIntegrationsStatus,
  getVelocity,
  type VelocityResponse,
} from '../../services/api';
import {
  DASHBOARD_SCENARIO_MATRIX,
  SCENARIO_NOW,
  activeSprintScenario,
  dateRangeScenarioTasks,
  emptyWindowScenarioTasks,
  velocitySparseScenario,
} from './fixtures/dashboard-scenarios';

vi.mock('../../services/api', () => ({
  listProjects: vi.fn(),
  listTasksPaginated: vi.fn(),
  listSprints: vi.fn(),
  getProjectBudgetHours: vi.fn(),
  getProjectValueMetrics: vi.fn(),
  getProjectById: vi.fn(),
  getSprintBurndown: vi.fn(),
  getSprintWipStatus: vi.fn(),
  getIntegrationsStatus: vi.fn(),
  getVelocity: vi.fn(),
}));

vi.mock('react-chartjs-2', () => ({
  Line: () => null,
  Bar: () => null,
  Doughnut: () => null,
}));

const mockedListProjects = vi.mocked(listProjects);
const mockedListTasksPaginated = vi.mocked(listTasksPaginated);
const mockedListSprints = vi.mocked(listSprints);
const mockedGetProjectBudgetHours = vi.mocked(getProjectBudgetHours);
const mockedGetProjectValueMetrics = vi.mocked(getProjectValueMetrics);
const mockedGetProjectById = vi.mocked(getProjectById);
const mockedGetSprintBurndown = vi.mocked(getSprintBurndown);
const mockedGetSprintWipStatus = vi.mocked(getSprintWipStatus);
const mockedGetIntegrationsStatus = vi.mocked(getIntegrationsStatus);
const mockedGetVelocity = vi.mocked(getVelocity);

const DAY = 24 * 60 * 60 * 1000;

const sampleProject = {
  id: 1,
  jira_key: 'WAB',
  name: 'WaBank',
  status: 'active',
  total_tasks: 5,
};

const sampleProjectSecondary = {
  id: 2,
  jira_key: 'WAB2',
  name: 'WaBank Core',
  status: 'active',
  total_tasks: 0,
};

const baseNow = SCENARIO_NOW;

const sampleTasks = [
  {
    id: 1,
    jira_id: 'WAB-1',
    key: 'WAB-1',
    summary: 'Overdue risk',
    status: 'In Progress',
    due_date: new Date(baseNow - 2 * DAY).toISOString(),
    updated_date: new Date(baseNow - 6 * DAY).toISOString(),
    project_id: 1,
    estimate_hours: 3,
  },
  {
    id: 2,
    jira_id: 'WAB-2',
    key: 'WAB-2',
    summary: 'Blocking issue',
    status: 'Blocked',
    updated_date: new Date(baseNow - DAY).toISOString(),
    due_date: new Date(baseNow + 3 * DAY).toISOString(),
    project_id: 1,
    is_blocker: true,
  },
  {
    id: 3,
    jira_id: 'WAB-3',
    key: 'WAB-3',
    summary: 'Stale progress',
    status: 'In Progress',
    updated_date: new Date(baseNow - 7 * DAY).toISOString(),
    project_id: 1,
  },
  {
    id: 4,
    jira_id: 'WAB-4',
    key: 'WAB-4',
    summary: 'Completed feature',
    status: 'Done',
    updated_date: new Date(baseNow - 2 * DAY).toISOString(),
    resolved_date: new Date(baseNow - 2 * DAY).toISOString(),
    estimate_hours: 5,
    project_id: 1,
  },
  {
    id: 5,
    jira_id: 'WAB-5',
    key: 'WAB-5',
    summary: 'Upcoming refinement',
    status: 'Todo',
    due_date: new Date(baseNow + 5 * DAY).toISOString(),
    project_id: 1,
  },
];

const preloadedState = {
  auth: { user: null, token: null, isAuthenticated: false, loading: false },
  project: {
    projects: [sampleProject],
    // Widened so tests can preload a selected project (UX review C4 global selector).
    currentProject: null as typeof sampleProject | null,
    loading: false,
    error: null,
    lastLoadedAt: null,
  },
  task: {
    tasks: [],
    loading: false,
    error: null,
    lastLoadedAt: null,
    lastLoadedAllAt: null,
    lastLoadedAtByProject: {},
    taskScopeByProject: {},
    tasksByProject: {},
  },
  sprint: {
    sprints: [],
    activeSprint: null,
    loading: false,
    error: null,
    lastLoadedAt: null,
    lastLoadedAtByProject: {},
    sprintsByProject: {},
  },
};

class MockSocket extends EventTarget implements WebSocket {
  static CONNECTING = 0 as const;
  static OPEN = 1 as const;
  static CLOSING = 2 as const;
  static CLOSED = 3 as const;
  static instances: MockSocket[] = [];
  readonly CONNECTING: 0 = MockSocket.CONNECTING;
  readonly OPEN: 1 = MockSocket.OPEN;
  readonly CLOSING: 2 = MockSocket.CLOSING;
  readonly CLOSED: 3 = MockSocket.CLOSED;

  binaryType: 'blob' | 'arraybuffer' = 'blob';
  bufferedAmount = 0;
  extensions = '';
  protocol = '';
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: Event) => void) | null = null;
  readyState: number = MockSocket.OPEN;
  url: string;

  constructor(url: string | URL) {
    super();
    this.url = String(url);
    MockSocket.instances.push(this);
    setTimeout(() => {
      const event = new Event('open');
      this.onopen?.(event);
      this.dispatchEvent(event);
    }, 0);
  }

  close(code?: number, reason?: string) {
    this.readyState = MockSocket.CLOSED;
    const event = new CloseEvent('close', {
      code: code ?? 1000,
      reason: reason ?? '',
      wasClean: true,
    });
    this.onclose?.(event);
    this.dispatchEvent(event);
  }

  send() {}

  triggerMessage(payload: unknown) {
    const event = new MessageEvent('message', { data: JSON.stringify(payload) });
    this.onmessage?.(event);
    this.dispatchEvent(event);
  }

  static last() {
    return MockSocket.instances[MockSocket.instances.length - 1] || null;
  }

  static reset() {
    MockSocket.instances = [];
  }
}

let originalWebSocket: typeof WebSocket;
let dateNowSpy: { mockRestore: () => void } | null = null;

describe('Dashboard smoke scenarios', () => {
  beforeAll(() => {
    originalWebSocket = globalThis.WebSocket;
    globalThis.WebSocket = MockSocket;
  });

  afterAll(() => {
    globalThis.WebSocket = originalWebSocket;
  });

  beforeEach(() => {
    MockSocket.reset();
    vi.clearAllMocks();
    dateNowSpy = vi.spyOn(Date, 'now').mockReturnValue(SCENARIO_NOW);
    localStorage.clear();
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.quickFilter, 'recent');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.dateRange, '30d');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.chartView, 'both');

    mockedListProjects.mockResolvedValue({
      data: [sampleProject],
      meta: {
        total: 1,
        page: 1,
        per_page: 50,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });
    mockedListTasksPaginated.mockResolvedValue({
      data: sampleTasks,
      meta: {
        total: sampleTasks.length,
        page: 1,
        per_page: 500,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });
    mockedListSprints.mockResolvedValue([]);
    mockedGetProjectBudgetHours.mockResolvedValue({
      remaining_hours: 12,
      total_spent_hours: 18,
      total_estimate_hours: 30,
      overrun: false,
      overrun_hours: 0,
      top_overruns: [],
    });
    mockedGetProjectValueMetrics.mockResolvedValue({ value_delivered: 42, total_spent_hours: 18, roi: 1.6 });
    mockedGetProjectById.mockResolvedValue(sampleProject);
    mockedGetSprintBurndown.mockResolvedValue({
      sprint_id: 100,
      ideal_burndown: [
        { day: 1, ideal_remaining: 12 },
        { day: 2, ideal_remaining: 8 },
        { day: 3, ideal_remaining: 4 },
      ],
      actual_burndown: [
        { day: 1, remaining: 11 },
        { day: 2, remaining: 7 },
        { day: 3, remaining: 5 },
      ],
    });
    mockedGetSprintWipStatus.mockResolvedValue({ total_active: 3, limit: 6, limit_default: 6, assignees: [] });
    mockedGetIntegrationsStatus.mockResolvedValue({
      jira: { configured: true, has_token: true },
      confluence: { configured: false },
      github: { configured: false },
      gitlab: { configured: false },
    });
    mockedGetVelocity.mockResolvedValue({
      average_velocity: 4,
      sprints_analyzed: 2,
      velocity_trend: 'stable',
      sprint_velocities: [
        { sprint_id: 11, sprint_name: 'Sprint A', velocity: 3, end_date: new Date(baseNow - 14 * DAY).toISOString() },
        { sprint_id: 12, sprint_name: 'Sprint B', velocity: 5, end_date: new Date(baseNow - 7 * DAY).toISOString() },
      ],
    });
  });

  afterEach(() => {
    dateNowSpy?.mockRestore();
    dateNowSpy = null;
  });

  const renderDashboard = (customPreloadedState = preloadedState) => {
    const store = configureStore({
      reducer: {
        auth: authReducer,
        project: projectReducer,
        task: taskReducer,
        sprint: sprintReducer,
      },
      preloadedState: customPreloadedState,
    });

    return {
      store,
      ...render(
        <Provider store={store}>
          <MemoryRouter
            future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
          >
            <Dashboard />
          </MemoryRouter>
        </Provider>
      ),
    };
  };

  const openAdvancedFilters = async () => {
    fireEvent.click(screen.getByRole('button', { name: /more filters/i }));
    await screen.findByText('Advanced Options');
  };

  const selectDropdownOption = async (testId: string, optionLabel: string) => {
    const control = await screen.findByTestId(testId);
    const combo = within(control).getByRole('combobox');
    fireEvent.mouseDown(combo);
    const listbox = await screen.findByRole('listbox');
    fireEvent.click(within(listbox).getByRole('option', { name: optionLabel }));
    await waitForElementToBeRemoved(listbox);
  };

  it('maintains scenario matrix coverage for high-risk dashboard regressions', () => {
    expect(DASHBOARD_SCENARIO_MATRIX.map((scenario) => scenario.id)).toEqual(
      expect.arrayContaining([
        'date_range_empty_window',
        'date_range_preserves_burndown_sprint_context',
        'no_active_sprint_wip',
        'partial_analytics_velocity_empty',
        'multi_project_quick_filter',
        'chart_view_velocity',
        'chart_view_burndown',
        'chart_view_both',
        'chart_view_distribution',
      ])
    );
  });

  it('renders risk insights and supports drilldowns', async () => {
    renderDashboard();

    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());
    const riskItems = await screen.findAllByTestId(DASHBOARD_TEST_IDS.riskItem);
    expect(riskItems.length).toBeGreaterThan(0);

    fireEvent.click(riskItems[0]);
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(await screen.findAllByTestId(DASHBOARD_TEST_IDS.drilldownItem)).not.toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const upcomingItems = await screen.findAllByTestId(DASHBOARD_TEST_IDS.upcomingItem);
    expect(upcomingItems.length).toBeGreaterThan(0);
  }, 25000);

  it('renders only the consolidated dashboard layout', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());

    await screen.findByTestId(DASHBOARD_TEST_IDS.sectionCharts);
    await screen.findByTestId(DASHBOARD_TEST_IDS.sectionInsights);
    await screen.findByTestId(DASHBOARD_TEST_IDS.sectionStats);

    expect(screen.getAllByTestId(DASHBOARD_TEST_IDS.sectionCharts)).toHaveLength(1);
    expect(screen.getAllByTestId(DASHBOARD_TEST_IDS.sectionInsights)).toHaveLength(1);
    expect(screen.getAllByTestId(DASHBOARD_TEST_IDS.sectionStats)).toHaveLength(1);
  }, 15000);

  it('shows explicit partial scope badge when task scope is incomplete', async () => {
    mockedListTasksPaginated.mockResolvedValueOnce({
      data: sampleTasks,
      meta: {
        total: 500,
        page: 1,
        per_page: 500,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });

    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());
    expect(await screen.findByTestId(DASHBOARD_TEST_IDS.partialScopeBadge)).toBeInTheDocument();
  }, 15000);

  it('shows explicit no-active-sprint state for WIP widget', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());

    const wipCard = await screen.findByTestId(DASHBOARD_TEST_IDS.cardWip);
    expect(within(wipCard).getByText('No active sprint')).toBeInTheDocument();
    expect(within(wipCard).getByText('--')).toBeInTheDocument();
  }, 15000);

  it('shows not-available WIP state when payload carries an error flag', async () => {
    mockedListSprints.mockResolvedValueOnce([
      {
        id: 901,
        sprint_id: 901,
        name: 'Sprint X',
        state: 'active',
        start_date: new Date(baseNow - 2 * DAY).toISOString(),
        end_date: new Date(baseNow + 5 * DAY).toISOString(),
      },
    ]);
    mockedGetSprintWipStatus.mockResolvedValueOnce({
      total_active: 0,
      assignees: [],
      limit_default: 6,
      error: 'malformed payload',
    });

    renderDashboard();
    await waitFor(() => expect(mockedGetSprintWipStatus).toHaveBeenCalled());

    const wipCard = await screen.findByTestId(DASHBOARD_TEST_IDS.cardWip);
    expect(within(wipCard).getByText('WIP data not available for active sprint')).toBeInTheDocument();
    expect(within(wipCard).getByText('N/A')).toBeInTheDocument();
  }, 15000);

  it('shows WIP error state when endpoint fails', async () => {
    mockedListSprints.mockResolvedValueOnce([
      {
        id: 902,
        sprint_id: 902,
        name: 'Sprint Y',
        status: 'active',
        start_date: new Date(baseNow - 3 * DAY).toISOString(),
        end_date: new Date(baseNow + 4 * DAY).toISOString(),
      },
    ]);
    mockedGetSprintWipStatus.mockRejectedValueOnce(new Error('wip failed'));

    renderDashboard();
    await waitFor(() => expect(mockedGetSprintWipStatus).toHaveBeenCalled());

    const wipCard = await screen.findByTestId(DASHBOARD_TEST_IDS.cardWip);
    expect(within(wipCard).getByText('Failed to load WIP data')).toBeInTheDocument();
    expect(within(wipCard).getByText('N/A')).toBeInTheDocument();
  }, 15000);

  it('shows explicit burndown not-available message when sprint timeline is missing', async () => {
    mockedListSprints.mockResolvedValueOnce([
      {
        id: 903,
        sprint_id: 903,
        name: 'Sprint Z',
        status: 'active',
        start_date: new Date(baseNow - 4 * DAY).toISOString(),
        end_date: new Date(baseNow + 3 * DAY).toISOString(),
      },
    ]);
    mockedGetSprintBurndown.mockResolvedValueOnce({
      sprint_id: 903,
      ideal_burndown: [],
      actual_burndown: [],
    });

    renderDashboard();
    await waitFor(() => expect(mockedGetSprintBurndown).toHaveBeenCalled());

    expect(await screen.findByText('Not available for this sprint.')).toBeInTheDocument();
  }, 15000);

  it('toggles chart panels deterministically for each chartView mode', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());
    await openAdvancedFilters();

    await selectDropdownOption(DASHBOARD_TEST_IDS.filterChartView, 'Velocity Only');
    await waitFor(() => {
      expect(screen.getByTestId(DASHBOARD_TEST_IDS.chartVelocity)).toBeInTheDocument();
      expect(screen.queryByTestId(DASHBOARD_TEST_IDS.chartBurndown)).not.toBeInTheDocument();
      expect(screen.queryByTestId(DASHBOARD_TEST_IDS.chartDistribution)).not.toBeInTheDocument();
    });

    await selectDropdownOption(DASHBOARD_TEST_IDS.filterChartView, 'Burndown Only');
    await waitFor(() => {
      expect(screen.queryByTestId(DASHBOARD_TEST_IDS.chartVelocity)).not.toBeInTheDocument();
      expect(screen.getByTestId(DASHBOARD_TEST_IDS.chartBurndown)).toBeInTheDocument();
      expect(screen.queryByTestId(DASHBOARD_TEST_IDS.chartDistribution)).not.toBeInTheDocument();
    });

    await selectDropdownOption(DASHBOARD_TEST_IDS.filterChartView, 'Distribution Only');
    await waitFor(() => {
      expect(screen.queryByTestId(DASHBOARD_TEST_IDS.chartVelocity)).not.toBeInTheDocument();
      expect(screen.queryByTestId(DASHBOARD_TEST_IDS.chartBurndown)).not.toBeInTheDocument();
      expect(screen.getByTestId(DASHBOARD_TEST_IDS.chartDistribution)).toBeInTheDocument();
    });

    await selectDropdownOption(DASHBOARD_TEST_IDS.filterChartView, 'Velocity + Burndown');
    await waitFor(() => {
      expect(screen.getByTestId(DASHBOARD_TEST_IDS.chartVelocity)).toBeInTheDocument();
      expect(screen.getByTestId(DASHBOARD_TEST_IDS.chartBurndown)).toBeInTheDocument();
      expect(screen.queryByTestId(DASHBOARD_TEST_IDS.chartDistribution)).not.toBeInTheDocument();
    });
  }, 20000);

  it('keeps sprint burndown timeline semantics when date range changes', async () => {
    mockedListSprints.mockResolvedValueOnce([activeSprintScenario]);
    mockedListTasksPaginated.mockResolvedValueOnce({
      data: dateRangeScenarioTasks,
      meta: {
        total: dateRangeScenarioTasks.length,
        page: 1,
        per_page: 500,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });

    renderDashboard();
    await waitFor(() =>
      expect(mockedGetSprintBurndown).toHaveBeenCalledWith(
        activeSprintScenario.sprint_id,
        expect.objectContaining({ signal: expect.any(Object) })
      )
    );
    await waitFor(() => {
      expect(screen.getByText(/Timeline data/i)).toBeInTheDocument();
      expect(screen.getAllByTestId(DASHBOARD_TEST_IDS.upcomingItem)).toHaveLength(2);
    });

    await openAdvancedFilters();
    await selectDropdownOption(DASHBOARD_TEST_IDS.filterDateRange, 'Last 7 Days');

    await waitFor(() => {
      expect(screen.getByText(/Timeline data/i)).toBeInTheDocument();
      expect(screen.getAllByTestId(DASHBOARD_TEST_IDS.upcomingItem)).toHaveLength(1);
      expect(mockedGetSprintBurndown.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    expect(
      mockedGetSprintBurndown.mock.calls.every(
        ([sprintId]) => Number(sprintId) === Number(activeSprintScenario.sprint_id)
      )
    ).toBe(true);
  }, 20000);

  it('shows explicit empty upcoming state when selected date range has no activity window', async () => {
    mockedListTasksPaginated.mockResolvedValueOnce({
      data: emptyWindowScenarioTasks,
      meta: {
        total: emptyWindowScenarioTasks.length,
        page: 1,
        per_page: 500,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });

    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());
    await openAdvancedFilters();
    await selectDropdownOption(DASHBOARD_TEST_IDS.filterDateRange, 'Last 7 Days');

    expect(await screen.findByText('No upcoming tasks.')).toBeInTheDocument();
    expect(screen.queryAllByTestId(DASHBOARD_TEST_IDS.upcomingItem)).toHaveLength(0);
  }, 20000);

  it('shows explicit velocity empty-state when sprint velocity data is missing', async () => {
    mockedGetVelocity.mockResolvedValueOnce(velocitySparseScenario);
    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());

    expect(
      await screen.findByText('Not enough sprint completion data to render velocity.')
    ).toBeInTheDocument();
  }, 15000);

  it('does not emit known dashboard chart warnings in healthy render path', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());
    await screen.findByTestId(DASHBOARD_TEST_IDS.chartVelocity);
    await screen.findByTestId(DASHBOARD_TEST_IDS.chartBurndown);

    const chartWarningCalls = warnSpy.mock.calls.filter((args) => isDashboardChartWarning(args));
    expect(chartWarningCalls).toHaveLength(0);
    warnSpy.mockRestore();
  }, 15000);

  it('migrates invalid persisted dashboard filters to canonical defaults', async () => {
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.dateRange, '999d');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.chartView, 'broken');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.quickFilter, 'wrong');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.recentProjectIds, '{oops');
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.lastProjectId, 'abc');
    localStorage.setItem('date_range', '14d');
    localStorage.setItem('chart_view', 'velocity');

    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());

    expect(localStorage.getItem(DASHBOARD_STORAGE_KEYS.dateRange)).toBe(
      DASHBOARD_DEFAULTS.dateRange
    );
    expect(localStorage.getItem(DASHBOARD_STORAGE_KEYS.chartView)).toBe(
      DASHBOARD_DEFAULTS.chartView
    );
    expect(localStorage.getItem(DASHBOARD_STORAGE_KEYS.quickFilter)).toBe(
      DASHBOARD_DEFAULTS.quickFilter
    );
    expect(localStorage.getItem(DASHBOARD_STORAGE_CONTRACT.versionKey)).toBe(
      String(DASHBOARD_STORAGE_CONTRACT.currentVersion)
    );
    expect(localStorage.getItem('date_range')).toBeNull();
    expect(localStorage.getItem('chart_view')).toBeNull();
  }, 15000);

  it('shows explicit task-scope anomaly warning when scope metadata is inconsistent', async () => {
    mockedListTasksPaginated.mockResolvedValueOnce({
      data: sampleTasks,
      meta: {
        total: 1,
        page: 1,
        per_page: 500,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });

    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());
    expect(await screen.findByTestId(DASHBOARD_TEST_IDS.taskScopeAnomalyBadge)).toBeInTheDocument();
  }, 15000);

  it('ignores stale async metric responses during rapid project switching', async () => {
    let resolveSlowVelocity: ((value: VelocityResponse) => void) | null = null;
    const slowVelocityPromise = new Promise<VelocityResponse>((resolve) => {
      resolveSlowVelocity = resolve;
    });
    mockedListProjects.mockResolvedValueOnce({
      data: [sampleProject, sampleProjectSecondary],
      meta: {
        total: 2,
        page: 1,
        per_page: 50,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });
    mockedListTasksPaginated.mockImplementation((params) => {
      const projectId = Number(params?.projectId ?? sampleProject.id);
      return Promise.resolve({
        data: projectId === sampleProjectSecondary.id ? [] : sampleTasks,
        meta: {
          total: projectId === sampleProjectSecondary.id ? 0 : sampleTasks.length,
          page: 1,
          per_page: 500,
          total_pages: 1,
          has_next: false,
          has_prev: false,
        },
      });
    });
    mockedGetVelocity.mockImplementation((projectId) => {
      if (Number(projectId) === sampleProject.id) {
        return slowVelocityPromise;
      }

      return Promise.resolve({
        average_velocity: 222,
        sprints_analyzed: 2,
        velocity_trend: 'stable',
        sprint_velocities: [{ sprint_id: 2, sprint_name: 'Fast sprint', velocity: 222 }],
      });
    });

    // Project selection is global now (UX review C4): start on the "slow"
    // project, then switch via the shared selector (Redux setCurrentProject)
    // instead of the removed in-dashboard project dropdown.
    const { store } = renderDashboard({
      ...preloadedState,
      project: {
        ...preloadedState.project,
        projects: [sampleProject, sampleProjectSecondary],
        currentProject: sampleProject,
      },
    });
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());

    await waitFor(() =>
      expect(mockedGetVelocity.mock.calls.some((call) => Number(call[0]) === sampleProject.id)).toBe(true)
    );

    await act(async () => {
      store.dispatch(setCurrentProject(sampleProjectSecondary));
    });

    await waitFor(() => {
      const lastCall = mockedListTasksPaginated.mock.calls.at(-1);
      expect(lastCall?.[0]).toMatchObject({ projectId: sampleProjectSecondary.id });
    });
    await waitFor(() =>
      expect(mockedGetVelocity.mock.calls.some((call) => Number(call[0]) === sampleProjectSecondary.id)).toBe(
        true
      )
    );
    expect(await screen.findByText(/Target:\s*222h/i)).toBeInTheDocument();

    await act(async () => {
      resolveSlowVelocity?.({
        average_velocity: 111,
        sprints_analyzed: 2,
        velocity_trend: 'stable',
        sprint_velocities: [{ sprint_id: 1, sprint_name: 'Slow sprint', velocity: 111 }],
      });
      await slowVelocityPromise;
    });

    await waitFor(() => expect(screen.queryByText(/Target:\s*111h/i)).not.toBeInTheDocument());
  }, 25000);

  it('refreshes data when websocket announces sync completion', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());
    const initialTasksCalls = mockedListTasksPaginated.mock.calls.length;
    const initialBudgetCalls = mockedGetProjectBudgetHours.mock.calls.length;

    await waitFor(() => expect(MockSocket.last()?.onmessage).toBeTypeOf('function'));
    const socket = MockSocket.last();
    await act(async () => {
      socket?.triggerMessage({ type: 'jira_sync_complete', project_id: sampleProject.id });
    });

    await waitFor(() => expect(mockedListTasksPaginated.mock.calls.length).toBeGreaterThan(initialTasksCalls));
    await waitFor(() => expect(mockedGetProjectBudgetHours.mock.calls.length).toBeGreaterThan(initialBudgetCalls));
  }, 15000);

  it('surfaces error when websocket indicates sync failure', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());

    await waitFor(() => expect(MockSocket.last()?.onmessage).toBeTypeOf('function'));
    const socket = MockSocket.last();
    await act(async () => {
      socket?.triggerMessage({ type: 'jira_sync_failed', project_id: sampleProject.id, detail: 'auth' });
    });

    await screen.findByText(/Background sync failed/i);
  }, 15000);

  it('emits refresh-loop signal once on websocket burst due to latch behavior', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());
    await waitFor(() => expect(MockSocket.last()?.onmessage).toBeTypeOf('function'));

    const socket = MockSocket.last();
    await act(async () => {
      for (let i = 0; i < 8; i += 1) {
        socket?.triggerMessage({ type: 'jira_sync_complete', project_id: sampleProject.id });
      }
    });

    await waitFor(() => {
      const refreshLoopWarnings = warnSpy.mock.calls.filter(
        (args) => args[0] === DASHBOARD_GUARDRAIL_TARGETS.refreshLoop.signal
      );
      expect(refreshLoopWarnings).toHaveLength(1);
    });

    warnSpy.mockRestore();
  }, 20000);
});
