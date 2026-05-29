import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import '@testing-library/jest-dom/vitest';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock('../../services/api', () => ({
  getRules: vi.fn(),
  updateRule: vi.fn(),
  createRule: vi.fn(),
  deleteRule: vi.fn(),
  executeRule: vi.fn(),
}));

import RulesManagement from '../RulesManagement';
import { createRule, deleteRule, executeRule, getRules, updateRule } from '../../services/api';

const mockedGetRules = vi.mocked(getRules);
const mockedUpdateRule = vi.mocked(updateRule);
const mockedCreateRule = vi.mocked(createRule);
const mockedDeleteRule = vi.mocked(deleteRule);
const mockedExecuteRule = vi.mocked(executeRule);

const rule = {
  id: 7,
  name: 'My Rule',
  description: null,
  flow_json: { nodes: [], edges: [] },
  enabled: true,
  category: 'custom' as const,
  tags: [],
  total_executions: 3,
  successful_executions: 2,
  failed_executions: 1,
  last_executed_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const renderPage = () =>
  render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <RulesManagement />
    </MemoryRouter>
  );

describe('RulesManagement', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetRules.mockResolvedValue({ data: [rule], meta: { total: 1 } } as never);
    mockedUpdateRule.mockResolvedValue({ ...rule, enabled: false } as never);
    mockedCreateRule.mockResolvedValue({ ...rule, id: 8 } as never);
    mockedDeleteRule.mockResolvedValue(undefined as never);
    mockedExecuteRule.mockResolvedValue({} as never);
  });

  it('lists rules from the API', async () => {
    renderPage();
    expect(await screen.findByText('My Rule')).toBeInTheDocument();
    expect(mockedGetRules).toHaveBeenCalled();
  });

  it('shows empty state when no rules match the filter', async () => {
    mockedGetRules.mockResolvedValueOnce({ data: [], meta: { total: 0 } } as never);
    renderPage();
    expect(await screen.findByText(/No rules match/i)).toBeInTheDocument();
  });

  it('shows an error with retry when loading fails', async () => {
    mockedGetRules.mockRejectedValueOnce(new Error('boom'));
    renderPage();
    expect(await screen.findByText('boom')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('toggles enabled state via updateRule', async () => {
    renderPage();
    await screen.findByText('My Rule');
    fireEvent.click(screen.getByRole('button', { name: 'Disable' }));
    await waitFor(() => expect(mockedUpdateRule).toHaveBeenCalledWith(7, { enabled: false }));
  });

  it('duplicates a rule with a (copy) name and disabled', async () => {
    renderPage();
    await screen.findByText('My Rule');
    fireEvent.click(screen.getByRole('button', { name: /Duplicate My Rule/i }));
    await waitFor(() => expect(mockedCreateRule).toHaveBeenCalled());
    expect(mockedCreateRule.mock.calls[0][0]).toMatchObject({
      name: 'My Rule (copy)',
      enabled: false,
    });
  });

  it('requires confirmation before delete and surfaces a 409 cascade error', async () => {
    mockedDeleteRule.mockRejectedValueOnce(new Error('unresolved review item(s)'));
    renderPage();
    await screen.findByText('My Rule');
    fireEvent.click(screen.getByRole('button', { name: /Delete My Rule/i }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(mockedDeleteRule).toHaveBeenCalledWith(7));
    expect(await screen.findByText(/unresolved review item/i)).toBeInTheDocument();
  });

  it('navigates to the builder for visual editing', async () => {
    renderPage();
    await screen.findByText('My Rule');
    fireEvent.click(screen.getByRole('button', { name: /Edit My Rule/i }));
    expect(navigateMock).toHaveBeenCalledWith('/traceability/flow-builder?ruleId=7');
  });
});
