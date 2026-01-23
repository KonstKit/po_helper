-- =============================================================================
-- Performance Optimization Indexes
-- =============================================================================
-- This migration adds composite indexes for frequently queried patterns
-- identified in the PO Helper application.
--
-- Run with: alembic upgrade head (after adding corresponding revision)
-- Or manually: psql -d po_helper -f add_performance_indexes.sql
-- =============================================================================


-- =============================================================================
-- Tasks Table Indexes
-- =============================================================================

-- Composite index for common task list queries
-- Covers: GET /tasks?project_id=X&status=Y
-- Covers: Analytics queries filtering by project + status
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_project_status
ON tasks (project_id, status);

-- Composite index for sprint + status queries
-- Covers: GET /tasks?sprint_id=X&status=Y
-- Covers: Sprint burndown, WIP status calculations
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_sprint_status
ON tasks (sprint_id, status);

-- Index for assignee queries (WIP limits, capacity)
-- Covers: Sprint WIP status grouped by assignee
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_sprint_assignee
ON tasks (sprint_id, assignee_email) WHERE assignee_email IS NOT NULL;

-- Partial index for open/active tasks (most common filter)
-- Significantly reduces index size by excluding done tasks
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_project_open
ON tasks (project_id, created_date)
WHERE status NOT IN ('Done', 'Closed', 'Resolved', 'Complete', 'done', 'closed', 'resolved', 'complete');

-- Index for due date queries (overdue detection in risks endpoint)
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_due_date_status
ON tasks (project_id, due_date, status)
WHERE due_date IS NOT NULL;

-- Index for blocker detection
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_blockers
ON tasks (project_id, is_blocker)
WHERE is_blocker = TRUE;

-- Covering index for velocity calculations (estimate aggregation)
-- Includes estimate_hours for index-only scans
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_sprint_velocity
ON tasks (sprint_id, status, estimate_hours);


-- =============================================================================
-- Sprints Table Indexes
-- =============================================================================

-- Composite index for project sprints list (most common query)
-- Covers: GET /analytics/projects/{id}/sprints
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sprints_project_state_date
ON sprints (project_id, state, start_date DESC NULLS LAST);

-- Index for active sprint lookup
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sprints_project_active
ON sprints (project_id)
WHERE state = 'active';


-- =============================================================================
-- Artifacts Table Indexes
-- =============================================================================

-- Composite index for artifact lookup by type and source
-- Covers: Backfill queries, artifact search
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_artifacts_type_source_external
ON artifacts (type, source, external_id);

-- Index for project-scoped artifact queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_artifacts_project_type
ON artifacts (project_id, type)
WHERE project_id IS NOT NULL;


-- =============================================================================
-- Artifact Links Table Indexes
-- =============================================================================

-- Already has: ix_links_from_type, ix_links_to_type in model
-- Add covering index for confidence scoring queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_artifact_links_confidence
ON artifact_links (from_artifact_id, confidence DESC)
WHERE confidence IS NOT NULL;


-- =============================================================================
-- Pull Requests Table Indexes (DORA metrics)
-- =============================================================================

-- Index for DORA deployment frequency queries
-- Covers: PR metrics filtered by repository and merge date
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_pull_requests_repo_merged
ON pull_requests (repository_id, merged_at DESC)
WHERE merged_at IS NOT NULL;

-- Index for lead time calculations
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_pull_requests_lead_time
ON pull_requests (repository_id, created_at, merged_at)
WHERE merged_at IS NOT NULL;


-- =============================================================================
-- Test Results Table Indexes
-- =============================================================================

-- Index for test trend analytics
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_test_results_date_status
ON test_results (created_at, status);


-- =============================================================================
-- Coverage Reports Table Indexes
-- =============================================================================

-- Index for coverage trend analytics
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_coverage_reports_date
ON coverage_reports (created_at);


-- =============================================================================
-- Suggested Links Table Indexes
-- =============================================================================

-- Index for pending suggestions (most common query in UI)
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_suggested_links_pending
ON suggested_links (project_id, status, similarity_score DESC)
WHERE status = 'pending';


-- =============================================================================
-- Worklogs Table Indexes
-- =============================================================================

-- Index for task worklog aggregation
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_worklogs_task_date
ON worklogs (task_id, started);


-- =============================================================================
-- Sprint Snapshots Table Indexes
-- =============================================================================

-- Index for burndown history queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sprint_snapshots_sprint_date
ON sprint_snapshots (sprint_id, date DESC);


-- =============================================================================
-- Capacity Settings Table Indexes
-- =============================================================================

-- Index for capacity lookup by assignee (if table exists)
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_capacity_settings_assignee
-- ON capacity_settings (assignee_email, project_id)
-- WHERE valid_from IS NULL OR valid_from <= CURRENT_DATE;


-- =============================================================================
-- Analyze Tables After Index Creation
-- =============================================================================

-- Update table statistics for query planner
ANALYZE tasks;
ANALYZE sprints;
ANALYZE artifacts;
ANALYZE artifact_links;
ANALYZE pull_requests;
ANALYZE test_results;
ANALYZE coverage_reports;
ANALYZE suggested_links;
ANALYZE worklogs;
ANALYZE sprint_snapshots;


-- =============================================================================
-- Notes on Index Strategy
-- =============================================================================
--
-- 1. All indexes created with CONCURRENTLY to avoid table locks
-- 2. Partial indexes used where applicable to reduce size
-- 3. Composite indexes ordered by selectivity (most selective first)
-- 4. Covering indexes include columns needed for index-only scans
--
-- Monitoring queries to validate index usage:
--
-- Check index usage:
--   SELECT relname, idx_scan, idx_tup_read
--   FROM pg_stat_user_indexes
--   WHERE schemaname = 'public'
--   ORDER BY idx_scan DESC;
--
-- Find unused indexes:
--   SELECT relname, indexrelname, idx_scan
--   FROM pg_stat_user_indexes
--   WHERE idx_scan = 0 AND schemaname = 'public';
--
-- Check index size:
--   SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid))
--   FROM pg_stat_user_indexes
--   WHERE schemaname = 'public'
--   ORDER BY pg_relation_size(indexrelid) DESC;
--
-- =============================================================================
