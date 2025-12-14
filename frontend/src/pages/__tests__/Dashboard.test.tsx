import { describe, it, expect, beforeAll, afterAll, beforeEach, vi } from 'vitest';
import '../../test/setup-env';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
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
    key: 'WAB-3',
    summary: 'Stale progress',
    status: 'In Progress',
    updated_date: new Date(baseNow - 7 * DAY).toISOString(),
    project_id: 1,
  },
  {
    id: 4,
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

class MockSocket {
  static instances: MockSocket[] = [];
  onopen: ((event?: any) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: ((event?: any) => void) | null = null;
  onclose: ((event?: any) => void) | null = null;
  readyState = 1;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockSocket.instances.push(this);
    setTimeout(() => this.onopen?.({ target: this }), 0);
  }

  close() {
    this.readyState = 3;
    this.onclose?.({ target: this });
  }

  send() {}

  triggerMessage(payload: any) {
    this.onmessage?.({ data: JSON.stringify(payload) });
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
    (globalThis as any).WebSocket = MockSocket as unknown as typeof WebSocket;
  });

  afterAll(() => {
    (globalThis as any).WebSocket = originalWebSocket;
  });

  beforeEach(() => {
    MockSocket.reset();
    vi.clearAllMocks();

    listProjects.mockResolvedValue([sampleProject]);
    listTasks.mockResolvedValue(sampleTasks);
    listSprints.mockResolvedValue([]);
    getProjectBudgetHours.mockResolvedValue({
      remaining_hours: 12,
      total_spent_hours: 18,
      total_estimate_hours: 30,
      overrun: false,
    });
    getProjectValueMetrics.mockResolvedValue({ value_delivered: 42, roi: 1.6 });
    getProjectById.mockResolvedValue(sampleProject);
    getSprintWipStatus.mockResolvedValue({ total_active: 3, limit: 6, assignees: [] });
    getIntegrationsStatus.mockResolvedValue({ jira: { configured: true, has_token: true } });
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
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </Provider>
    );
  };

  it('renders risk insights and supports drilldowns', async () => {
    renderDashboard();

    await waitFor(() => expect(listTasks).toHaveBeenCalled());

    await waitFor(() => {
      expect(document.querySelectorAll('[data-testid^="risk-item-"]').length).toBeGreaterThan(0);
    });
    const riskBoxes = Array.from(document.querySelectorAll('[data-testid^="risk-item-"]')) as HTMLElement[];
    expect(riskBoxes.length).toBeGreaterThan(0);

    fireEvent.click(riskBoxes[0]);
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(await screen.findAllByTestId('drilldown-item')).not.toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await waitFor(() => {
      expect(document.querySelectorAll('[data-testid="upcoming-item"]').length).toBeGreaterThan(0);
    });
  });

  it('refreshes data when websocket announces sync completion', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasks).toHaveBeenCalled());
    const initialTasksCalls = listTasks.mock.calls.length;
    const initialBudgetCalls = getProjectBudgetHours.mock.calls.length;

    const socket = MockSocket.last();
    expect(socket).toBeTruthy();
    socket?.triggerMessage({ type: 'jira_sync_complete', project_id: sampleProject.id });

    await waitFor(() => expect(listTasks.mock.calls.length).toBeGreaterThan(initialTasksCalls));
    await waitFor(() => expect(getProjectBudgetHours.mock.calls.length).toBeGreaterThan(initialBudgetCalls));
  });

  it('surfaces error when websocket indicates sync failure', async () => {
    renderDashboard();
    await waitFor(() => expect(listTasks).toHaveBeenCalled());

    const socket = MockSocket.last();
    socket?.triggerMessage({ type: 'jira_sync_failed', project_id: sampleProject.id, detail: 'auth' });

    await screen.findByText(/Background sync failed/i);
  });
});
