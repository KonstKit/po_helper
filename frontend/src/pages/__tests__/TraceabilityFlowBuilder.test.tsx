import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

vi.mock('../../services/api', () => ({
  createRule: vi.fn(),
  disableRuleWebhook: vi.fn(),
  enableRuleWebhook: vi.fn(),
  executeRule: vi.fn(),
  getRule: vi.fn(),
  getRuleSchedule: vi.fn(),
  getRules: vi.fn(),
  getRuleWebhook: vi.fn(),
  updateRule: vi.fn(),
  updateRuleSchedule: vi.fn(),
  validateRuleFlow: vi.fn(),
}));

vi.mock('../../components/traceability/Toolbox', () => ({
  default: () => <div data-testid="toolbox" />,
}));

vi.mock('../../components/traceability/PropertiesPanelEditable', () => ({
  default: () => <div data-testid="properties-panel" />,
}));

vi.mock('../../components/traceability/ImportExportDialog', () => ({
  default: () => <div data-testid="import-export-dialog" />,
}));

vi.mock('../../components/traceability/TemplateDialog', () => ({
  default: () => <div data-testid="template-dialog" />,
}));

vi.mock('../../components/traceability/ValidationPanel', () => ({
  default: () => <div data-testid="validation-panel" />,
}));

vi.mock('reactflow', () => {
  const ReactModule = React;

  const useStateTuple = <T,>(initial: T[]) => {
    const [value, setValue] = ReactModule.useState(initial);
    return [value, setValue, vi.fn()] as const;
  };

  return {
    __esModule: true,
    default: ({ children }: { children?: React.ReactNode }) => <div data-testid="reactflow">{children}</div>,
    addEdge: vi.fn((edge, existing) => existing.concat({ ...edge, id: edge.id ?? `edge-${existing.length}` })),
    Background: () => <div data-testid="reactflow-background" />,
    Connection: {},
    Controls: () => <div data-testid="reactflow-controls" />,
    Edge: {},
    MiniMap: () => <div data-testid="reactflow-minimap" />,
    Node: {},
    NodeTypes: {},
    useEdgesState: useStateTuple,
    useNodesState: useStateTuple,
  };
});

import TraceabilityFlowBuilder from '../TraceabilityFlowBuilder';
import {
  createRule,
  getRule,
  getRuleSchedule,
  getRules,
  getRuleWebhook,
  updateRule,
  updateRuleSchedule,
  validateRuleFlow,
} from '../../services/api';

const mockedCreateRule = vi.mocked(createRule);
const mockedGetRule = vi.mocked(getRule);
const mockedGetRuleSchedule = vi.mocked(getRuleSchedule);
const mockedGetRules = vi.mocked(getRules);
const mockedGetRuleWebhook = vi.mocked(getRuleWebhook);
const mockedUpdateRule = vi.mocked(updateRule);
const mockedUpdateRuleSchedule = vi.mocked(updateRuleSchedule);
const mockedValidateRuleFlow = vi.mocked(validateRuleFlow);

const EMPTY_META = {
  total: 0,
  page: 1,
  per_page: 50,
  total_pages: 1,
  has_next: false,
  has_prev: false,
};

const createdRule = {
  id: 101,
  name: 'Automation Smoke Rule',
  description: 'Created by test',
  flow_json: {
    nodes: [],
    edges: [],
    version: '1.0',
  },
  enabled: true,
  category: 'custom',
  execute_on_sync_complete: false,
};

describe('TraceabilityFlowBuilder automation state', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockedGetRules.mockResolvedValue({
      data: [],
      meta: EMPTY_META,
    });

    mockedValidateRuleFlow.mockResolvedValue({
      valid: true,
      errors: [],
      warnings: [],
    });

    mockedCreateRule.mockResolvedValue(createdRule as never);
    mockedGetRule.mockResolvedValue(createdRule as never);
    mockedGetRuleSchedule.mockResolvedValue({
      schedule_enabled: false,
      schedule_cron: '',
      next_scheduled_run: null,
    } as never);
    mockedGetRuleWebhook.mockResolvedValue({
      trigger_on_webhook: false,
      webhook_url: null,
      webhook_token: null,
    } as never);
    mockedUpdateRule.mockResolvedValue(createdRule as never);
    mockedUpdateRuleSchedule.mockResolvedValue({
      schedule_enabled: false,
      schedule_cron: '',
      next_scheduled_run: null,
    } as never);
  });

  it('keeps automation dirty state separate from rule saves', async () => {
    render(<TraceabilityFlowBuilder />);

    await waitFor(() => expect(getRules).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText(/Rule Name/i), {
      target: { value: 'Automation Smoke Rule' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    await waitFor(() => expect(createRule).toHaveBeenCalled());
    await screen.findByRole('button', { name: /Save Automation/i });

    fireEvent.change(screen.getByLabelText(/Rule Name/i), {
      target: { value: 'Automation Smoke Rule v2' },
    });
    fireEvent.click(screen.getByLabelText(/Run After Sync/i));

    fireEvent.click(screen.getByRole('button', { name: /Update/i }));

    await waitFor(() => expect(updateRule).toHaveBeenCalled());
    expect(screen.getByText(/Unsaved changes/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Save Automation/i })).toBeEnabled();
    const updateCallsBeforeAutomationSave = mockedUpdateRule.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: /Save Automation/i }));

    await waitFor(() =>
      expect(mockedUpdateRule.mock.calls.length).toBeGreaterThan(updateCallsBeforeAutomationSave)
    );
    await waitFor(() => expect(updateRuleSchedule).toHaveBeenCalled());
    const automationPersistCall = mockedUpdateRule.mock.calls.at(-1);
    expect(automationPersistCall?.[1]).toMatchObject({
      execute_on_sync_complete: true,
    });
    await waitFor(() => expect(screen.queryByText(/Unsaved changes/i)).not.toBeInTheDocument());
  });

  it('shows a recoverable failure state when automation load fails', async () => {
    mockedGetRuleSchedule.mockRejectedValueOnce(new Error('schedule service unavailable'));

    render(<TraceabilityFlowBuilder />);

    await waitFor(() => expect(getRules).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText(/Rule Name/i), {
      target: { value: 'Broken Automation Rule' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    await waitFor(() => expect(createRule).toHaveBeenCalled());

    const alert = await screen.findByText(
      /Automation controls are disabled until the current backend state is loaded/i
    );
    expect(alert).toBeInTheDocument();
    expect(screen.getByText(/schedule service unavailable|Failed to load automation settings/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Retry/i })).toBeVisible();
    expect(screen.getByRole('button', { name: /Save Automation/i })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /Retry/i }));

    await waitFor(() => expect(getRule).toHaveBeenCalledWith(createdRule.id));
    await waitFor(() =>
      expect(
        screen.queryByText(/Automation controls are disabled until the current backend state is loaded/i)
      ).not.toBeInTheDocument()
    );
    expect(screen.getByRole('button', { name: /Save Automation/i })).toBeEnabled();
  });
});
