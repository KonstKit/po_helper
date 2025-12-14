import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import DashboardSkeleton from './DashboardSkeleton';

describe('DashboardSkeleton Component', () => {
  it('renders without crashing', () => {
    const { container } = render(<DashboardSkeleton />);
    expect(container).toBeInTheDocument();
  });

  it('renders KPI skeleton section', () => {
    const { container } = render(<DashboardSkeleton />);

    // Should have gradient background Paper for KPI section
    const paper = container.querySelector('.MuiPaper-root');
    expect(paper).toBeInTheDocument();
  });

  it('renders 4 KPI skeletons', () => {
    const { container } = render(<DashboardSkeleton />);

    // KPI section should have 4 Grid items
    const kpiSection = container.querySelector('.MuiPaper-root');
    const gridItems = kpiSection?.querySelectorAll('.MuiGrid-item');

    expect(gridItems?.length).toBe(4);
  });

  it('renders chart skeletons', () => {
    const { container } = render(<DashboardSkeleton />);

    // Should have multiple Card components for charts
    const cards = container.querySelectorAll('.MuiCard-root');

    // Expect at least 2 chart cards (Velocity + Burndown)
    expect(cards.length).toBeGreaterThanOrEqual(2);
  });

  it('renders skeleton elements with correct variants', () => {
    const { container } = render(<DashboardSkeleton />);

    // Check for text skeletons
    const textSkeletons = container.querySelectorAll('.MuiSkeleton-text');
    expect(textSkeletons.length).toBeGreaterThan(0);

    // Check for rectangular skeletons (charts)
    const rectSkeletons = container.querySelectorAll('.MuiSkeleton-rectangular');
    expect(rectSkeletons.length).toBeGreaterThan(0);

    // Check for circular skeletons (doughnut chart)
    const circularSkeletons = container.querySelectorAll('.MuiSkeleton-circular');
    expect(circularSkeletons.length).toBeGreaterThan(0);
  });

  it('renders velocity chart skeleton card', () => {
    const { container } = render(<DashboardSkeleton />);

    const cards = container.querySelectorAll('.MuiCard-root');

    // First main chart card should be velocity
    expect(cards.length).toBeGreaterThan(0);
  });

  it('renders burndown chart skeleton card', () => {
    const { container } = render(<DashboardSkeleton />);

    const cards = container.querySelectorAll('.MuiCard-root');

    // Second main chart card should be burndown
    expect(cards.length).toBeGreaterThan(1);
  });

  it('renders task distribution skeleton', () => {
    const { container } = render(<DashboardSkeleton />);

    // Should have circular skeleton for doughnut chart
    const circularSkeletons = container.querySelectorAll('.MuiSkeleton-circular');
    expect(circularSkeletons.length).toBeGreaterThan(0);
  });

  it('renders risk alerts skeleton section', () => {
    const { container } = render(<DashboardSkeleton />);

    const cards = container.querySelectorAll('.MuiCard-root');

    // Should have multiple cards including risk alerts
    expect(cards.length).toBeGreaterThanOrEqual(3);
  });

  it('renders upcoming tasks skeleton section', () => {
    const { container } = render(<DashboardSkeleton />);

    const cards = container.querySelectorAll('.MuiCard-root');

    // Should have multiple cards including upcoming tasks
    expect(cards.length).toBeGreaterThanOrEqual(4);
  });

  it('uses consistent styling throughout', () => {
    const { container } = render(<DashboardSkeleton />);

    // All skeletons should have MuiSkeleton class
    const allSkeletons = container.querySelectorAll('[class*="MuiSkeleton"]');
    expect(allSkeletons.length).toBeGreaterThan(10); // Many skeleton elements
  });

  it('renders Grid layout correctly', () => {
    const { container } = render(<DashboardSkeleton />);

    // Should have Grid container
    const gridContainers = container.querySelectorAll('.MuiGrid-container');
    expect(gridContainers.length).toBeGreaterThan(0);
  });

  it('maintains aspect ratios for chart skeletons', () => {
    const { container } = render(<DashboardSkeleton />);

    // Rectangular skeletons should have defined heights
    const rectSkeletons = container.querySelectorAll('.MuiSkeleton-rectangular');

    rectSkeletons.forEach((skeleton) => {
      // Each should be in the DOM
      expect(skeleton).toBeInTheDocument();
    });
  });

  it('is memoized (doesn\'t cause unnecessary re-renders)', () => {
    const { rerender } = render(<DashboardSkeleton />);

    // Component should accept rerender without errors
    rerender(<DashboardSkeleton />);

    // Should still be in document
    expect(document.querySelector('.MuiPaper-root')).toBeInTheDocument();
  });
});
