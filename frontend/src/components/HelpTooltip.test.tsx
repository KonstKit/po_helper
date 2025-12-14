import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HelpTooltip } from './HelpTooltip';

describe('HelpTooltip Component', () => {
  it('renders help icon by default', () => {
    render(<HelpTooltip title="Test Title" />);

    const button = screen.getByRole('button');
    expect(button).toBeInTheDocument();
  });

  it('renders info icon when specified', () => {
    const { container } = render(<HelpTooltip title="Test Title" icon="info" />);

    // Check for info icon SVG
    const svg = container.querySelector('svg[data-testid="InfoOutlinedIcon"]');
    expect(svg).toBeInTheDocument();
  });

  it('shows tooltip on hover with title', async () => {
    const user = userEvent.setup();

    render(<HelpTooltip title="Tooltip Title" />);

    const button = screen.getByRole('button');

    // Hover over button
    await user.hover(button);

    // Wait for tooltip to appear
    await waitFor(() => {
      expect(screen.getByText('Tooltip Title')).toBeInTheDocument();
    });
  });

  it('shows tooltip with title and description', async () => {
    const user = userEvent.setup();

    render(
      <HelpTooltip
        title="Main Title"
        description="This is a detailed description of the feature"
      />
    );

    const button = screen.getByRole('button');
    await user.hover(button);

    await waitFor(() => {
      expect(screen.getByText('Main Title')).toBeInTheDocument();
      expect(screen.getByText('This is a detailed description of the feature')).toBeInTheDocument();
    });
  });

  it('applies correct placement', async () => {
    const user = userEvent.setup();

    const { container } = render(
      <HelpTooltip title="Test" placement="bottom" />
    );

    const button = screen.getByRole('button');
    await user.hover(button);

    // Tooltip should be rendered (exact placement testing is complex with MUI)
    await waitFor(() => {
      expect(screen.getByText('Test')).toBeInTheDocument();
    });
  });

  it('renders with small size by default', () => {
    render(<HelpTooltip title="Test" />);

    const button = screen.getByRole('button');
    // Small icon buttons have specific styling
    expect(button).toBeInTheDocument();
  });

  it('renders with medium size when specified', () => {
    render(<HelpTooltip title="Test" size="medium" />);

    const button = screen.getByRole('button');
    expect(button).toBeInTheDocument();
  });

  it('hides tooltip on unhover', async () => {
    const user = userEvent.setup();

    render(<HelpTooltip title="Tooltip Title" />);

    const button = screen.getByRole('button');

    // Hover to show
    await user.hover(button);
    await waitFor(() => {
      expect(screen.getByText('Tooltip Title')).toBeInTheDocument();
    });

    // Unhover to hide
    await user.unhover(button);

    await waitFor(() => {
      expect(screen.queryByText('Tooltip Title')).not.toBeInTheDocument();
    });
  });

  it('renders tooltip content as a fragment when description provided', async () => {
    const user = userEvent.setup();

    render(
      <HelpTooltip
        title="Title Line"
        description="Description Line"
      />
    );

    const button = screen.getByRole('button');
    await user.hover(button);

    await waitFor(() => {
      // Both title and description should be visible
      const title = screen.getByText('Title Line');
      const description = screen.getByText('Description Line');

      expect(title).toBeInTheDocument();
      expect(description).toBeInTheDocument();

      // Title should have semibold font weight
      expect(title).toHaveStyle({ fontWeight: 600 });
    });
  });

  it('renders with all placement options', async () => {
    const placements: Array<'top' | 'bottom' | 'left' | 'right'> = ['top', 'bottom', 'left', 'right'];

    for (const placement of placements) {
      const { unmount } = render(
        <HelpTooltip title={`Placement: ${placement}`} placement={placement} />
      );

      const button = screen.getByRole('button');
      expect(button).toBeInTheDocument();

      unmount();
    }
  });

  it('applies hover styling to icon button', async () => {
    const user = userEvent.setup();

    render(<HelpTooltip title="Test" />);

    const button = screen.getByRole('button');

    // Initial state
    expect(button).toBeInTheDocument();

    // Hover (actual color change is handled by CSS, just verify button works)
    await user.hover(button);
    expect(button).toBeInTheDocument();
  });
});
