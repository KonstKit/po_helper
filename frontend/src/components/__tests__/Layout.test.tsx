import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import '@testing-library/jest-dom';

vi.mock('../../services/api', () => {
  const resolved = { data: [], meta: { total: 0, page: 1, per_page: 50, total_pages: 0, has_next: false, has_prev: false } };
  const cache: Record<string, unknown> = {};
  return new Proxy({}, {
    get: (_target, name) => {
      if (typeof name !== 'string' || ['then', '__esModule'].includes(name)) {
        return undefined;
      }
      if (!cache[name]) cache[name] = vi.fn().mockResolvedValue(resolved);
      return cache[name];
    },
  });
});
vi.mock('../../services/api/client', () => ({ default: { post: vi.fn().mockRejectedValue(new Error('offline')), get: vi.fn().mockRejectedValue(new Error('offline')) } }));

import Layout from '../Layout';
import authReducer from '../../store/authSlice';
import projectReducer from '../../store/projectSlice';

const renderLayout = (initialPath: string = '/') => {
  const store = configureStore({
    reducer: { auth: authReducer, project: projectReducer },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route element={<Layout />}>
            <Route path='/' element={<div>home-page</div>} />
            <Route path='/traceability' element={<div>trace-page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </Provider>
  );
};

describe('Layout sidebar', () => {
  it('renders data-driven labels, never the item.text literal', () => {
    renderLayout();
    // The drawer renders twice (desktop permanent + mobile temporary).
    expect(screen.getAllByText('Traceability').length).toBe(2);
    expect(screen.getAllByText('Knowledge').length).toBe(2);
    expect(screen.getAllByText('Quality').length).toBe(2);
    expect(screen.queryByText('item.text')).not.toBeInTheDocument();
  });

  it('chevron toggles submenu without navigation; parent click navigates', () => {
    renderLayout();
    // The closed mobile drawer does not mount the toggle, so the
    // chevron is unambiguous in the DOM.
    fireEvent.click(screen.getByRole('button', { name: 'Expand submenu' }));
    expect(screen.getAllByText('D3 Visualization').length).toBe(2);
    expect(screen.getAllByText('home-page').length).toBe(1);
    // parent click: navigate to /traceability, submenu stays open
    fireEvent.click(screen.getAllByText('Traceability')[0]);
    expect(screen.getAllByText('trace-page').length).toBe(1);
    expect(screen.getAllByText('D3 Visualization').length).toBe(2);
    // the chevron has a real role/label (not a bare span) for a11y
    expect(screen.getByRole('button', { name: 'Collapse submenu' }).tagName).toBe('BUTTON');
  });
});
