import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

vi.mock('../../services/api', () => ({
  createMatrixExport: vi.fn(),
  getExportStatus: vi.fn(),
  getExportDownloadUrl: vi.fn(),
}));

import MatrixExportDialog from './MatrixExportDialog';
import {
  createMatrixExport,
  getExportStatus,
  getExportDownloadUrl,
} from '../../services/api';

const mockedCreate = vi.mocked(createMatrixExport);
const mockedStatus = vi.mocked(getExportStatus);
const mockedDownloadUrl = vi.mocked(getExportDownloadUrl);

// ExportTaskStatus shape (see src/services/api/types.ts):
// { task_id, status, progress_pct, download_url, error_message, created_at, completed_at }
const processingTask = {
  task_id: 'task-abc',
  status: 'processing' as const,
  progress_pct: 10,
  download_url: null,
  error_message: null,
  created_at: '2026-05-30T00:00:00Z',
  completed_at: null,
};

const completedTask = {
  task_id: 'task-abc',
  status: 'completed' as const,
  progress_pct: 100,
  download_url: '/api/v1/traceability/exports/task-abc/download',
  error_message: null,
  created_at: '2026-05-30T00:00:00Z',
  completed_at: '2026-05-30T00:00:05Z',
};

const failedTask = {
  task_id: 'task-abc',
  status: 'failed' as const,
  progress_pct: 40,
  download_url: null,
  error_message: 'Worker crashed while building sheet',
  created_at: '2026-05-30T00:00:00Z',
  completed_at: '2026-05-30T00:00:05Z',
};

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  projectId: 7,
  projectName: 'Apollo',
};

describe('MatrixExportDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedDownloadUrl.mockReturnValue('/api/v1/traceability/exports/task-abc/download');
  });

  afterEach(() => {
    // Always restore real timers, even if a test threw before its own
    // useRealTimers() call, so fake timers never leak to later tests/files.
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // (1) initial / loading: dialog renders the export form when open
  it('renders the export form when open', () => {
    render(<MatrixExportDialog {...defaultProps} onClose={vi.fn()} />);

    expect(screen.getByText('Export Traceability Matrix')).toBeInTheDocument();
    expect(screen.getByText('Apollo')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument();
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  // (2) "empty" / closed: nothing rendered, and no result/progress UI present
  it('renders nothing and shows no result UI when closed', () => {
    render(<MatrixExportDialog {...defaultProps} open={false} onClose={vi.fn()} />);

    expect(screen.queryByText('Export Traceability Matrix')).not.toBeInTheDocument();
    expect(screen.queryByText('Export Complete!')).not.toBeInTheDocument();
    expect(screen.queryByText('Export Failed')).not.toBeInTheDocument();
  });

  // (3a) error: a failed export shows the error message
  it('shows an error message when the export fails', async () => {
    vi.useFakeTimers();
    try {
      mockedCreate.mockResolvedValue(processingTask);
      mockedStatus.mockResolvedValue(failedTask);

      render(<MatrixExportDialog {...defaultProps} onClose={vi.fn()} />);

      fireEvent.click(screen.getByRole('button', { name: 'Export' }));

      // Resolve createMatrixExport -> processing
      await vi.waitFor(() => expect(mockedCreate).toHaveBeenCalled());
      // Advance one poll interval so getExportStatus resolves -> failed (terminal)
      await vi.advanceTimersByTimeAsync(1500);

      await vi.waitFor(() => {
        expect(screen.getByText('Export Failed')).toBeInTheDocument();
        expect(
          screen.getByText('Worker crashed while building sheet')
        ).toBeInTheDocument();
      });
    } finally {
      vi.useRealTimers();
    }
  });

  // (3b) error: a failed create surfaces the rejection message in the form
  it('shows an error when starting the export fails', async () => {
    mockedCreate.mockRejectedValueOnce(new Error('Failed to start export'));

    render(<MatrixExportDialog {...defaultProps} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Export' }));

    expect(await screen.findByText('Failed to start export')).toBeInTheDocument();
  });

  // (4) success: a completed export shows the download button/label
  it('shows a download button when the export completes', async () => {
    vi.useFakeTimers();
    try {
      mockedCreate.mockResolvedValue(processingTask);
      mockedStatus.mockResolvedValue(completedTask);

      render(<MatrixExportDialog {...defaultProps} onClose={vi.fn()} />);

      fireEvent.click(screen.getByRole('button', { name: 'Export' }));

      await vi.waitFor(() => expect(mockedCreate).toHaveBeenCalled());
      await vi.advanceTimersByTimeAsync(1500);

      await vi.waitFor(() => {
        expect(screen.getByText('Export Complete!')).toBeInTheDocument();
        expect(
          screen.getByRole('button', { name: /Download XLSX/i })
        ).toBeInTheDocument();
      });
    } finally {
      vi.useRealTimers();
    }
  });

  // (5a) interaction: clicking Export calls createMatrixExport with the right payload
  it('calls createMatrixExport with project id and format when Export is clicked', async () => {
    mockedCreate.mockResolvedValue(processingTask);

    render(<MatrixExportDialog {...defaultProps} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Export' }));

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(
        expect.objectContaining({ project_id: 7, format: 'xlsx' })
      )
    );
  });

  // (5b) interaction: clicking Download builds the URL and opens it
  it('opens the download URL when the Download button is clicked', async () => {
    vi.useFakeTimers();
    const openSpy = vi
      .spyOn(window, 'open')
      .mockImplementation(() => null as unknown as Window);
    try {
      mockedCreate.mockResolvedValue(processingTask);
      mockedStatus.mockResolvedValue(completedTask);

      render(<MatrixExportDialog {...defaultProps} onClose={vi.fn()} />);
      fireEvent.click(screen.getByRole('button', { name: 'Export' }));

      await vi.waitFor(() => expect(mockedCreate).toHaveBeenCalled());
      await vi.advanceTimersByTimeAsync(1500);

      const downloadBtn = await vi.waitFor(() =>
        screen.getByRole('button', { name: /Download XLSX/i })
      );
      fireEvent.click(downloadBtn);

      expect(mockedDownloadUrl).toHaveBeenCalledWith('task-abc');
      expect(openSpy).toHaveBeenCalledWith(
        '/api/v1/traceability/exports/task-abc/download',
        '_blank'
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
