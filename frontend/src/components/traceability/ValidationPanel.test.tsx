import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

import ValidationPanel from './ValidationPanel';
import type { ValidationResult } from '../../utils/ruleValidation';

// ValidationPanel is purely presentational and is driven entirely via props.
// It imports no API functions, so services/api is intentionally NOT mocked.
// It uses no Router primitives, so no MemoryRouter wrapper is required.

const emptyValid: ValidationResult = {
  valid: true,
  errors: [],
  warnings: [],
};

const withErrors: ValidationResult = {
  valid: false,
  errors: [
    {
      type: 'error',
      message: 'Rule must have at least one Source node',
    },
    {
      type: 'error',
      message: 'Filter node "My Filter" must specify a field to filter on',
      nodeId: 'filter-7',
    },
  ],
  warnings: [],
};

const withWarnings: ValidationResult = {
  valid: true,
  errors: [],
  warnings: [
    {
      type: 'warning',
      message: 'Source node "Commit Source" has no outgoing connections',
      nodeId: 'commit-1',
    },
  ],
};

const withErrorsAndWarnings: ValidationResult = {
  valid: false,
  errors: [
    {
      type: 'error',
      message: 'Decision node "Gate" must have a numeric threshold',
      nodeId: 'decision-3',
    },
  ],
  warnings: [
    {
      type: 'warning',
      message: 'Processor node "Extractor" has no output',
      nodeId: 'extractor-2',
    },
  ],
};

describe('ValidationPanel', () => {
  // (1) initial / default render: errors + warnings both expanded by default.
  it('renders the panel with both error and warning sections expanded by default', () => {
    render(<ValidationPanel validation={withErrorsAndWarnings} />);

    const panel = screen.getByTestId('validation-panel');
    expect(panel).toBeInTheDocument();

    // Section headers reflect the singular counts.
    expect(within(panel).getByText('1 Error')).toBeInTheDocument();
    expect(within(panel).getByText('1 Warning')).toBeInTheDocument();

    // Default expanded state means both list items are visible.
    expect(
      screen.getByText('Decision node "Gate" must have a numeric threshold'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Processor node "Extractor" has no output'),
    ).toBeInTheDocument();
  });

  // (2) empty data -> valid/empty state message.
  it('shows the valid empty state when there are no errors or warnings', () => {
    render(<ValidationPanel validation={emptyValid} />);

    expect(screen.getByTestId('validation-panel')).toBeInTheDocument();
    expect(screen.getByText('Rule is Valid')).toBeInTheDocument();
    expect(
      screen.getByText('This rule has no errors or warnings and is ready to use.'),
    ).toBeInTheDocument();

    // Error/warning section headers must not appear in the valid state.
    expect(screen.queryByText(/Error/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Warning/)).not.toBeInTheDocument();
  });

  // (3) error state -> error messages + node ids visible, count pluralized.
  it('renders error messages with node ids and a pluralized error count', () => {
    render(<ValidationPanel validation={withErrors} />);

    // Two errors -> pluralized header.
    expect(screen.getByText('2 Errors')).toBeInTheDocument();

    // Both error messages are rendered.
    expect(
      screen.getByText('Rule must have at least one Source node'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Filter node "My Filter" must specify a field to filter on'),
    ).toBeInTheDocument();

    // The node id is surfaced for the error that carries one.
    expect(screen.getByText('Node: filter-7')).toBeInTheDocument();

    // No warning section because there are no warnings.
    expect(screen.queryByText(/Warning/)).not.toBeInTheDocument();
  });

  // (4) success/data -> warning rows + labels/counts render.
  it('renders warning messages with node ids and a singular warning count', () => {
    render(<ValidationPanel validation={withWarnings} />);

    expect(screen.getByText('1 Warning')).toBeInTheDocument();
    expect(
      screen.getByText('Source node "Commit Source" has no outgoing connections'),
    ).toBeInTheDocument();
    expect(screen.getByText('Node: commit-1')).toBeInTheDocument();

    // A valid result that only has warnings must not show an error section.
    expect(screen.queryByText(/Error/)).not.toBeInTheDocument();
  });

  // (5a) interaction: clicking an error row with a nodeId invokes onNodeClick.
  it('calls onNodeClick with the node id when an error row is clicked', () => {
    const onNodeClick = vi.fn();
    render(<ValidationPanel validation={withErrors} onNodeClick={onNodeClick} />);

    fireEvent.click(
      screen.getByText('Filter node "My Filter" must specify a field to filter on'),
    );

    expect(onNodeClick).toHaveBeenCalledTimes(1);
    expect(onNodeClick).toHaveBeenCalledWith('filter-7');
  });

  // (5b) interaction: clicking an error row WITHOUT a nodeId does not invoke onNodeClick.
  it('does not call onNodeClick when an error row has no node id', () => {
    const onNodeClick = vi.fn();
    render(<ValidationPanel validation={withErrors} onNodeClick={onNodeClick} />);

    fireEvent.click(screen.getByText('Rule must have at least one Source node'));

    expect(onNodeClick).not.toHaveBeenCalled();
  });

  // (5c) interaction: clicking a warning row with a nodeId invokes onNodeClick.
  it('calls onNodeClick with the node id when a warning row is clicked', () => {
    const onNodeClick = vi.fn();
    render(<ValidationPanel validation={withWarnings} onNodeClick={onNodeClick} />);

    fireEvent.click(
      screen.getByText('Source node "Commit Source" has no outgoing connections'),
    );

    expect(onNodeClick).toHaveBeenCalledTimes(1);
    expect(onNodeClick).toHaveBeenCalledWith('commit-1');
  });
});
