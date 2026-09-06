import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import authReducer from '../../store/authSlice';

// Isolate the page's responsibility (admin gate + wiring) by stubbing the
// heavy SyncHealthDashboard so this test needs no API mocks.
vi.mock('../../components/traceability/SyncHealthDashboard', () => ({
  default: ({ allowAllProjects }: { allowAllProjects?: boolean }) => (
    <div data-testid="sync-health-dashboard">allowAllProjects={String(allowAllProjects)}</div>
  ),
}));

import TraceabilitySyncHealth from '../TraceabilitySyncHealth';

const adminUser = {
  id: 1,
  email: 'admin@example.com',
  username: 'admin',
  is_active: true,
  is_superuser: true,
};

const renderAt = (user: typeof adminUser | null) => {
  const store = configureStore({
    reducer: { auth: authReducer },
    preloadedState: {
      auth: { user, isAuthenticated: user !== null, sessionProbe: 'done' as const, loading: false },
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/traceability/sync-health']}>
        <Routes>
          <Route path="/" element={<div data-testid="home">home</div>} />
          <Route path="/traceability/sync-health" element={<TraceabilitySyncHealth />} />
        </Routes>
      </MemoryRouter>
    </Provider>,
  );
};

describe('TraceabilitySyncHealth (C5 admin all-projects gate)', () => {
  it('renders the all-projects Sync Health dashboard for admins', () => {
    renderAt(adminUser);
    const dash = screen.getByTestId('sync-health-dashboard');
    expect(dash).toBeInTheDocument();
    // Standalone view explicitly allows the "All Projects" aggregate.
    expect(dash).toHaveTextContent('allowAllProjects=true');
    expect(screen.getByText('Sync Health — All Projects')).toBeInTheDocument();
    expect(screen.queryByTestId('home')).not.toBeInTheDocument();
  });

  it('redirects non-admins (is_superuser=false) to home', () => {
    renderAt({ ...adminUser, is_superuser: false });
    expect(screen.queryByTestId('sync-health-dashboard')).not.toBeInTheDocument();
    expect(screen.getByTestId('home')).toBeInTheDocument();
  });

  it('redirects when there is no user', () => {
    renderAt(null);
    expect(screen.queryByTestId('sync-health-dashboard')).not.toBeInTheDocument();
    expect(screen.getByTestId('home')).toBeInTheDocument();
  });
});
