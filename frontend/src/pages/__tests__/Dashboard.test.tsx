import { describe, it, expect, beforeAll, afterAll, beforeEach, vi } from 'vitest';
import '../../test/setup-env';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { MemoryRouter } from 'react-router-dom';

import Dashboard from '../Dashboard';
import authReducer from '../../store/authSlice';
import projectReducer from '../../store/projectSlice';
import taskReducer from '../../store/taskSlice';
import sprintReducer from '../../store/sprintSlice';
import {
  listProjects,
  listTasks,
  listSprints,
  getProjectBudgetHours,
  getProjectValueMetrics,
  getProjectById,
  getSprintWipStatus,
  getIntegrationsStatus,
} from '../../services/api';

vi.mock('../../services/api', () => ({
  listProjects: vi.fn(),
  listTasks: vi.fn(),
  listSprints: vi.fn(),
  getProjectBudgetHours: vi.fn(),
  getProjectValueMetrics: vi.fn(),
  getProjectById: vi.fn(),
  getSprintWipStatus: vi.fn(),
  getIntegrationsStatus: vi.fn(),
}));

vi.mock('react-chartjs-2', () => ({
  Line: () => null,
  Bar: () => null,
  Doughnut: () => null,
}));

const mockedListProjects = vi.mocked(listProjects);
const mockedListTasks = vi.mocked(listTasks);
const mockedListSprints = vi.mocked(listSprints);
const mockedGetProjectBudgetHours = vi.mocked(getProjectBudgetHours);
const mockedGetProjectValueMetrics = vi.mocked(getProjectValueMetrics);
const mockedGetProjectById = vi.mocked(getProjectById);
const mockedGetSprintWipStatus = vi.mocked(getSprintWipStatus);
const mockedGetIntegrationsStatus = vi.mocked(getIntegrationsStatus);

const DAY = 24 * 60 * 60 * 1000;

const sampleProject = {
  id: 1,
  jira_key: 'WAB',
  name: 'WaBank',
  status: 'active',
  total_tasks: 5,
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
    currentProject: sampleProject,
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
    tasksByProject: {},
  },
  sprint: {
    sprints: [],
    activeSprint: null,
    loading: false,
    error: null,
    lastLoadedAt: null,
    sprintsByProject: {},
  },
};

class MockSocket extends EventTarget implements WebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockSocket[] = [];

  binaryType: 'blob' | 'arraybuffer' = 'blob';
  bufferedAmount = 0;
  extensions = '';
  protocol = '';
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: Event) => void) | null = null;
  readyState = MockSocket.OPEN;
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
    mockedListTasks.mockResolvedValue(sampleTasks);
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
  });

  const renderDashboard = () => {
    const store = configureStore({
      reducer: {
        auth: authReducer,
        project: projectReducer,
        task: taskReducer,
        sprint: sprintReducer,
      },
      preloadedState,
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

    await waitFor(() => expect(listTasks).toHaveBeenCalled());

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
  });

  it('renders only the consolidated dashboard layout', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasks).toHaveBeenCalled());

    await screen.findByTestId('dashboard-section-charts');
    await screen.findByTestId('dashboard-section-insights');
    await screen.findByTestId('dashboard-section-stats');

    expect(screen.queryByText('Risk Assessment')).not.toBeInTheDocument();
    expect(screen.queryByText('Upcoming Focus')).not.toBeInTheDocument();
    expect(screen.queryByText('Team Velocity')).not.toBeInTheDocument();
  });

  it('refreshes data when websocket announces sync completion', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasks).toHaveBeenCalled());
    const initialTasksCalls = mockedListTasks.mock.calls.length;
    const initialBudgetCalls = mockedGetProjectBudgetHours.mock.calls.length;

    await waitFor(() => expect(MockSocket.last()?.onmessage).toBeTypeOf('function'));
    const socket = MockSocket.last();
    await act(async () => {
      socket?.triggerMessage({ type: 'jira_sync_complete', project_id: sampleProject.id });
    });

    await waitFor(() => expect(mockedListTasks.mock.calls.length).toBeGreaterThan(initialTasksCalls));
    await waitFor(() => expect(mockedGetProjectBudgetHours.mock.calls.length).toBeGreaterThan(initialBudgetCalls));
  });

  it('surfaces error when websocket indicates sync failure', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasks).toHaveBeenCalled());

    await waitFor(() => expect(MockSocket.last()?.onmessage).toBeTypeOf('function'));
    const socket = MockSocket.last();
    await act(async () => {
      socket?.triggerMessage({ type: 'jira_sync_failed', project_id: sampleProject.id, detail: 'auth' });
    });

    await screen.findByText(/Background sync failed/i);
  });
});
