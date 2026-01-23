import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { analytics } from '../services/analytics';

/**
 * Tracks page views automatically via React Router
 */
export const PageViewTracker = ({ children }: { children: ReactNode }) => {
  const location = useLocation();

  useEffect(() => {
    // Extract page name from path
    const pageName = location.pathname.split('/')[1] || 'dashboard';
    analytics.pageView(pageName);

    // Track first time viewing specific pages
    const firstViewKey = `first_view_${pageName}`;
    const firstView = localStorage.getItem(firstViewKey);
    if (!firstView) {
      localStorage.setItem(firstViewKey, Date.now().toString());
      analytics.track('first_page_view', { page: pageName });

      // Track specific milestones
      if (pageName === 'projects') {
        analytics.trackTimeToValue('firstProjectViewedAt');
      } else if (pageName === 'tasks') {
        analytics.trackTimeToValue('firstTaskViewedAt');
      }
    }
  }, [location]);

  return <>{children}</>;
};
