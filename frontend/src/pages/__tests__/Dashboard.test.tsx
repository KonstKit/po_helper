import { describe, it, expect, beforeAll, afterAll, beforeEach, vi } from 'vitest';
import '../../test/setup-env';
import { render, screen, waitFor, fireEvent, act, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { MemoryRouter } from 'react-router-dom';

import Dashboard from '../Dashboard';
import { DASHBOARD_STORAGE_KEYS, DASHBOARD_TEST_IDS } from '../dashboard/dashboardContract';
import authReducer from '../../store/authSlice';
import projectReducer from '../../store/projectSlice';
import taskReducer from '../../store/taskSlice';
import sprintReducer from '../../store/sprintSlice';
import {
  listProjects,
  listTasksPaginated,
  listSprints,
  getProjectBudgetHours,
  getProjectValueMetrics,
  getProjectById,
  getSprintWipStatus,
  getIntegrationsStatus,
  getVelocity,
} from '../../services/api';

vi.mock('../../services/api', () => ({
  listProjects: vi.fn(),
  listTasksPaginated: vi.fn(),
  listSprints: vi.fn(),
  getProjectBudgetHours: vi.fn(),
  getProjectValueMetrics: vi.fn(),
  getProjectById: vi.fn(),
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

const baseNow = Date.now();

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
    currentProject: null,
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
  static CONNECTING: 0 = 0;
  static OPEN: 1 = 1;
  static CLOSING: 2 = 2;
  static CLOSED: 3 = 3;
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

    return render(
      <Provider store={store}>
        <MemoryRouter
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Dashboard />
        </MemoryRouter>
      </Provider>
    );
  };

  it('renders risk insights and supports drilldowns', async () => {
    renderDashboard();

    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());

    await waitFor(() => {
      expect(document.querySelectorAll('[data-testid^="dashboard-risk-item-"]').length).toBeGreaterThan(0);
    });
    const riskBoxes = Array.from(document.querySelectorAll('[data-testid^="dashboard-risk-item-"]')).filter(
      (node): node is HTMLElement => node instanceof HTMLElement
    );
    expect(riskBoxes.length).toBeGreaterThan(0);

    fireEvent.click(riskBoxes[0]);
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(await screen.findAllByTestId('dashboard-drilldown-item')).not.toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await waitFor(() => {
      expect(document.querySelectorAll('[data-testid="dashboard-upcoming-item"]').length).toBeGreaterThan(0);
    });
  }, 25000);

  it('renders only the consolidated dashboard layout', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasksPaginated).toHaveBeenCalled());

    await screen.findByTestId('dashboard-section-charts');
    await screen.findByTestId('dashboard-section-insights');
    await screen.findByTestId('dashboard-section-stats');

    expect(screen.queryByText('Risk Assessment')).not.toBeInTheDocument();
    expect(screen.queryByText('Upcoming Focus')).not.toBeInTheDocument();
    expect(screen.queryByText('Team Velocity')).not.toBeInTheDocument();
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

    const wipCard = await screen.findByTestId('card-wip');
    expect(within(wipCard).getByText('No active sprint')).toBeInTheDocument();
    expect(within(wipCard).getByText('--')).toBeInTheDocument();
  }, 15000);

  it('shows not-available WIP state when payload is malformed', async () => {
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
      assignees: [],
      limit_default: 6,
    } as any);

    renderDashboard();
    await waitFor(() => expect(mockedGetSprintWipStatus).toHaveBeenCalled());

    const wipCard = await screen.findByTestId('card-wip');
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

    const wipCard = await screen.findByTestId('card-wip');
    expect(within(wipCard).getByText('Failed to load WIP data')).toBeInTheDocument();
    expect(within(wipCard).getByText('N/A')).toBeInTheDocument();
  }, 15000);

  it('restores recent project context on initial load', async () => {
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

    localStorage.setItem(DASHBOARD_STORAGE_KEYS.quickFilter, 'recent');
    localStorage.setItem(
      DASHBOARD_STORAGE_KEYS.recentProjectIds,
      JSON.stringify([sampleProjectSecondary.id, sampleProject.id])
    );
    localStorage.setItem(DASHBOARD_STORAGE_KEYS.lastProjectId, String(sampleProject.id));

    renderDashboard({
      ...preloadedState,
      project: {
        ...preloadedState.project,
        projects: [sampleProject, sampleProjectSecondary],
        currentProject: null,
      },
    });

    await waitFor(() =>
      expect(mockedListTasksPaginated).toHaveBeenCalledWith(
        { projectId: sampleProjectSecondary.id, skip: 0, limit: 500 },
        { timeout: 30000 }
      )
    );
  }, 15000);

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
});
