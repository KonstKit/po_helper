import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import EmptyState from './EmptyState';
import DashboardIcon from '@mui/icons-material/Dashboard';

// Helper to wrap component with Router
const renderWithRouter = (component: ReactElement) => {
  return render(
    <MemoryRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      {component}
    </MemoryRouter>
  );
};

describe('EmptyState Component', () => {
  it('renders title and description', () => {
    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon />}
        title="No Projects Found"
        description="Get started by creating your first project"
      />
    );

    expect(screen.getByText('No Projects Found')).toBeInTheDocument();
    expect(screen.getByText('Get started by creating your first project')).toBeInTheDocument();
  });

  it('renders icon correctly', () => {
    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon data-testid="dashboard-icon" />}
        title="Test Title"
        description="Test Description"
      />
    );

    expect(screen.getByTestId('dashboard-icon')).toBeInTheDocument();
  });

  it('renders primary action button and handles click', () => {
    const handleClick = vi.fn();

    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon />}
        title="Test Title"
        description="Test Description"
        primaryAction={{
          label: 'Create Project',
          onClick: handleClick,
        }}
      />
    );

    const button = screen.getByRole('button', { name: 'Create Project' });
    expect(button).toBeInTheDocument();

    fireEvent.click(button);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('renders secondary action button', () => {
    const handleSecondary = vi.fn();

    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon />}
        title="Test Title"
        description="Test Description"
        secondaryAction={{
          label: 'Learn More',
          onClick: handleSecondary,
        }}
      />
    );

    const button = screen.getByRole('button', { name: 'Learn More' });
    expect(button).toBeInTheDocument();

    fireEvent.click(button);
    expect(handleSecondary).toHaveBeenCalledTimes(1);
  });

  it('renders benefits list when provided', () => {
    const benefits = [
      'Benefit 1: Fast setup',
      'Benefit 2: Easy to use',
      'Benefit 3: Great results',
    ];

    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon />}
        title="Test Title"
        description="Test Description"
        benefits={benefits}
      />
    );

    benefits.forEach((benefit) => {
      expect(screen.getByText(benefit)).toBeInTheDocument();
    });
  });

  it('renders documentation link when provided', () => {
    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon />}
        title="Test Title"
        description="Test Description"
        docsUrl="https://docs.example.com"
      />
    );

    const link = screen.getByText('View Documentation');
    expect(link).toBeInTheDocument();
    expect(link.closest('a')).toHaveAttribute('href', 'https://docs.example.com');
  });

  it('renders both primary and secondary actions together', () => {
    const handlePrimary = vi.fn();
    const handleSecondary = vi.fn();

    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon />}
        title="Test Title"
        description="Test Description"
        primaryAction={{
          label: 'Primary Action',
          onClick: handlePrimary,
        }}
        secondaryAction={{
          label: 'Secondary Action',
          onClick: handleSecondary,
        }}
      />
    );

    expect(screen.getByRole('button', { name: 'Primary Action' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Secondary Action' })).toBeInTheDocument();
  });

  it('applies correct button variant for primary action', () => {
    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon />}
        title="Test Title"
        description="Test Description"
        primaryAction={{
          label: 'Contained Button',
          onClick: vi.fn(),
          variant: 'contained',
        }}
      />
    );

    const button = screen.getByRole('button', { name: 'Contained Button' });
    expect(button).toHaveClass('MuiButton-contained');
  });

  it('renders minimal config without errors', () => {
    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon />}
        title="Minimal Title"
        description="Minimal Description"
      />
    );

    expect(screen.getByText('Minimal Title')).toBeInTheDocument();
  });

  it('renders full config with all optional props', () => {
    const handlePrimary = vi.fn();
    const handleSecondary = vi.fn();

    renderWithRouter(
      <EmptyState
        icon={<DashboardIcon />}
        title="Full Config"
        description="With all options"
        primaryAction={{
          label: 'Primary',
          onClick: handlePrimary,
          variant: 'contained',
        }}
        secondaryAction={{
          label: 'Secondary',
          onClick: handleSecondary,
          variant: 'outlined',
        }}
        benefits={['Benefit 1', 'Benefit 2']}
        docsUrl="https://docs.example.com"
      />
    );

    // Verify all elements are present
    expect(screen.getByText('Full Config')).toBeInTheDocument();
    expect(screen.getByText('With all options')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Primary' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Secondary' })).toBeInTheDocument();
    expect(screen.getByText('Benefit 1')).toBeInTheDocument();
    expect(screen.getByText('Benefit 2')).toBeInTheDocument();
    expect(screen.getByText('View Documentation')).toBeInTheDocument();
  });
});
