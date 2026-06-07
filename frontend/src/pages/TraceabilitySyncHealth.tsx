import React from 'react';
import { Navigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { Box, Typography } from '@mui/material';
import { RootState } from '../store/store';
import SyncHealthDashboard from '../components/traceability/SyncHealthDashboard';

/**
 * Admin-only cross-project sync-health review (backlog item C5).
 *
 * The backend `/traceability/sync-health` endpoint already aggregates across
 * every project when `project_id` is omitted, but only for admins
 * (`has_admin_access` = is_superuser OR the ADMIN permission). The single
 * place SyncHealthDashboard renders in-app (the Traceability tab) hides the
 * "All Projects" option because there it is driven by the global project
 * selector. This standalone page gives admins a dedicated entry point: it
 * manages its own internal project filter (defaulting to "All Projects") and
 * does not touch the global selected project, so it cannot leave other tabs
 * on a stale project.
 *
 * Gating is on `is_superuser` — the only admin signal carried by the frontend
 * user model. A non-admin who reaches this route directly is redirected home;
 * the nav entry is hidden for them in Layout.
 */
const TraceabilitySyncHealth: React.FC = () => {
  const user = useSelector((s: RootState) => s.auth.user);
  const isAdmin = Boolean(user?.is_superuser);

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Sync Health — All Projects
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Cross-project synchronization health (admin view). Defaults to all
        projects; use the filter to focus on a single project.
      </Typography>
      <SyncHealthDashboard allowAllProjects />
    </Box>
  );
};

export default TraceabilitySyncHealth;
