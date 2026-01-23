# Performance Optimization Architecture

## Overview

This document describes the comprehensive caching and performance optimization architecture for the PO Helper application (FastAPI + React + async SQLAlchemy + Redis).

---

## Table of Contents

1. [Backend Caching Strategy](#1-backend-caching-strategy)
2. [Database Optimization](#2-database-optimization)
3. [API Design Patterns](#3-api-design-patterns)
4. [Frontend Optimization](#4-frontend-optimization)
5. [Implementation Checklist](#5-implementation-checklist)

---

## 1. Backend Caching Strategy

### 1.1 Tiered TTL Policies

Cache entries are categorized by data volatility:

| Tier | TTL | Stale-While-Revalidate | Use Cases |
|------|-----|------------------------|-----------|
| **REALTIME** | 15s | 5s | Active sprint status, WIP limits |
| **HOT** | 60s | 30s | Task lists, team health, burndown |
| **WARM** | 5min | 60s | Velocity trends, DORA metrics |
| **COLD** | 30min | 5min | Historical analytics, completed sprints |
| **STATIC** | 1hr | 10min | Traceability matrix, forecasts |

### 1.2 Cache Key Patterns

Structured key format enables predictable invalidation:

```
{prefix}:{domain}:{resource}:{id}:{variant}
```

Examples:
- `po_helper:analytics:project:123:velocity_sprints_5`
- `po_helper:analytics:sprint:456:burndown`
- `po_helper:traceability:project:123:matrix`
- `po_helper:tasks:list:query:a1b2c3d4`

### 1.3 Cache Key Builders (Backend)

Location: `/backend/app/core/cache_enhanced.py`

```python
from app.core.cache_enhanced import AnalyticsCacheKeys, CacheTier

# Build cache keys
key = AnalyticsCacheKeys.velocity(project_id=123, sprints_count=5)
# Result: "po_helper:analytics:project:123:velocity_sprints_5"

# Use in endpoints
cached = await cache_service.get(key, tier=CacheTier.WARM)
if cached:
    return cached

result = await compute_velocity(...)
await cache_service.set(key, result, tier=CacheTier.WARM)
```

### 1.4 Cache Invalidation Strategy

**Pattern-based invalidation:**

```python
from app.core.cache_enhanced import CacheInvalidator

# After task update
await CacheInvalidator.on_task_update(project_id=123, sprint_id=456)

# After Jira sync
await CacheInvalidator.on_jira_sync(project_id=123)

# After artifact link change
await CacheInvalidator.on_artifact_link_change(project_id=123)
```

**Invalidation triggers:**
- Task CRUD operations -> Invalidate project + sprint caches
- Sprint updates -> Invalidate sprint + project caches
- Jira sync completion -> Invalidate all project caches
- Traceability changes -> Invalidate matrix caches

### 1.5 Cache Decorator for Endpoints

```python
from app.core.cache_enhanced import cached_endpoint, CacheTier, AnalyticsCacheKeys

@router.get("/projects/{project_id}/velocity")
@cached_endpoint(
    key_builder=lambda project_id, sprints_count=5, **_:
        AnalyticsCacheKeys.velocity(project_id, sprints_count),
    tier=CacheTier.WARM
)
async def get_project_velocity(
    project_id: int,
    sprints_count: int = 5,
    db: AsyncSession = Depends(get_db)
):
    # Cache miss - compute result
    ...
```

---

## 2. Database Optimization

### 2.1 Composite Index Recommendations

Location: `/backend/migrations/add_performance_indexes.sql`

**Tasks Table:**

```sql
-- Common task list queries
CREATE INDEX ix_tasks_project_status ON tasks (project_id, status);
CREATE INDEX ix_tasks_sprint_status ON tasks (sprint_id, status);

-- WIP and capacity queries
CREATE INDEX ix_tasks_sprint_assignee ON tasks (sprint_id, assignee_email)
    WHERE assignee_email IS NOT NULL;

-- Partial index for open tasks (reduces index size)
CREATE INDEX ix_tasks_project_open ON tasks (project_id, created_date)
    WHERE status NOT IN ('Done', 'Closed', 'Resolved', 'Complete');

-- Velocity calculations (covering index)
CREATE INDEX ix_tasks_sprint_velocity ON tasks (sprint_id, status, estimate_hours);
```

**Sprints Table:**

```sql
-- Project sprints list query
CREATE INDEX ix_sprints_project_state_date
    ON sprints (project_id, state, start_date DESC NULLS LAST);

-- Active sprint lookup
CREATE INDEX ix_sprints_project_active ON sprints (project_id)
    WHERE state = 'active';
```

**Pull Requests Table (DORA):**

```sql
-- Deployment frequency
CREATE INDEX ix_pull_requests_repo_merged
    ON pull_requests (repository_id, merged_at DESC)
    WHERE merged_at IS NOT NULL;
```

### 2.2 Query Optimization Patterns

**Before (N+1 Problem):**

```python
# Bad: N+1 queries for velocity
for sprint in sprints:
    tasks = await db.execute(select(Task).where(Task.sprint_id == sprint.id))
    velocity = sum(t.estimate_hours for t in tasks if t.status in DONE)
```

**After (Single Query):**

```python
# Good: GROUP BY in single query
from app.utils.batch_operations import aggregate_by_group

velocity_by_sprint = await aggregate_by_group(
    db, Task, "sprint_id",
    {"completed_hours": ("estimate_hours", "sum")},
    filters=[Task.sprint_id.in_(sprint_ids), Task.status.in_(DONE_STATUSES)]
)
```

### 2.3 Batch Operations

Location: `/backend/app/utils/batch_operations.py`

**Bulk Delete:**

```python
from app.utils.batch_operations import bulk_delete_by_ids

# Instead of N DELETE queries
deleted_count = await bulk_delete_by_ids(db, Task, task_ids, chunk_size=500)
```

**Batch Fetch:**

```python
from app.utils.batch_operations import batch_fetch_by_ids, batch_fetch_related

# Fetch multiple records with eager loading
tasks_by_id = await batch_fetch_by_ids(db, Task, task_ids, eager_load=["project"])

# Fetch related records grouped by parent
worklogs_by_task = await batch_fetch_related(db, Task, task_ids, WorkLog, "task_id")
```

**Cycle Detection (Graph Traversal):**

```python
from app.utils.batch_operations import detect_cycles_batched

# Instead of N+1 BFS queries
would_cycle = await detect_cycles_batched(
    db, ArtifactLink,
    "from_artifact_id", "to_artifact_id",
    start_id=new_from, target_id=new_to
)
```

---

## 3. API Design Patterns

### 3.1 Standard Pagination

Location: `/backend/app/schemas/pagination.py`

**Offset Pagination (simpler):**

```python
from app.schemas.pagination import paginate_with_count, paginated_response

@router.get("/tasks")
async def list_tasks(skip: int = 0, limit: int = 50, db = Depends(get_db)):
    query = select(Task).where(Task.project_id == project_id)
    tasks, total = await paginate_with_count(db, query, Task, skip, limit)

    return paginated_response(tasks, total, skip, limit)
```

**Response format:**

```json
{
  "data": [...],
  "meta": {
    "total": 150,
    "page": 1,
    "per_page": 50,
    "total_pages": 3,
    "has_next": true,
    "has_prev": false
  }
}
```

**Cursor Pagination (for large datasets):**

```python
from app.schemas.pagination import CursorPaginationParams, cursor_paginate

@router.get("/artifacts")
async def list_artifacts(
    cursor: Optional[str] = None,
    limit: int = 50,
    db = Depends(get_db)
):
    params = CursorPaginationParams(cursor=cursor, limit=limit)
    query = select(Artifact).where(Artifact.project_id == project_id)
    artifacts, meta = await cursor_paginate(db, query, Artifact, params)

    return {"data": artifacts, "meta": meta}
```

### 3.2 Batch Endpoints

**Batch Create/Update:**

```python
@router.post("/tasks/batch")
async def batch_create_tasks(tasks: List[TaskCreate], db = Depends(get_db)):
    created = []
    async with db.begin():
        for task_data in tasks:
            task = Task(**task_data.dict())
            db.add(task)
            created.append(task)

    return {"created": len(created), "tasks": created}
```

**Batch Delete:**

```python
@router.delete("/tasks/batch")
async def batch_delete_tasks(task_ids: List[int], db = Depends(get_db)):
    from app.utils.batch_operations import bulk_delete_by_ids

    count = await bulk_delete_by_ids(db, Task, task_ids)

    # Invalidate caches
    await CacheInvalidator.on_task_update(project_id=None, sprint_id=None)

    return {"deleted": count}
```

### 3.3 Parallel Analytics Endpoint

Single endpoint that returns all analytics in parallel:

```python
@router.get("/projects/{project_id}/analytics/summary")
async def get_analytics_summary(project_id: int, db = Depends(get_db)):
    import asyncio

    # Run all analytics queries in parallel
    velocity_task = get_project_velocity(project_id, 5, db)
    team_health_task = get_project_team_health(project_id, db)
    budget_task = project_budget_hours(project_id, 5, db)
    risks_task = identify_project_risks(project_id, db)

    velocity, health, budget, risks = await asyncio.gather(
        velocity_task, team_health_task, budget_task, risks_task,
        return_exceptions=True
    )

    return {
        "velocity": velocity if not isinstance(velocity, Exception) else None,
        "team_health": health if not isinstance(health, Exception) else None,
        "budget": budget if not isinstance(budget, Exception) else None,
        "risks": risks if not isinstance(risks, Exception) else None,
    }
```

---

## 4. Frontend Optimization

### 4.1 Request Deduplication

Location: `/frontend/src/utils/apiOptimization.ts`

Prevents duplicate concurrent requests (e.g., React StrictMode double-mounting):

```typescript
import { deduplicateRequest } from '../utils/apiOptimization';

export async function getProjectById(id: number): Promise<Project> {
  return deduplicateRequest(
    `project-${id}`,
    () => api.get(`/v1/projects/${id}`)
  );
}
```

### 4.2 Debouncing Search/Filter Inputs

Location: `/frontend/src/hooks/useDebounce.ts`

```typescript
import { useDebouncedValue, DEBOUNCE_DELAYS } from '../hooks/useDebounce';

function TaskSearch() {
  const [query, setQuery] = useState('');
  const debouncedQuery = useDebouncedValue(query, DEBOUNCE_DELAYS.SEARCH);

  useEffect(() => {
    if (debouncedQuery) {
      searchTasks(debouncedQuery);
    }
  }, [debouncedQuery]);

  return (
    <TextField
      value={query}
      onChange={(e) => setQuery(e.target.value)}
      placeholder="Search tasks..."
    />
  );
}
```

**Recommended delays:**
- `SEARCH_FAST`: 150ms - Autocomplete
- `SEARCH`: 300ms - Standard search
- `FILTER`: 200ms - Dropdowns/checkboxes
- `EXPENSIVE`: 500ms - Heavy analytics

### 4.3 Parallel Analytics Loading

```typescript
import { loadParallel } from '../utils/apiOptimization';

async function loadDashboardData(projectId: number) {
  const { data, errors, isComplete } = await loadParallel({
    velocity: () => getProjectVelocity(projectId),
    teamHealth: () => getProjectTeamHealth(projectId),
    burndown: () => getSprintBurndown(activeSprintId),
    dora: () => getDoraMetrics(projectId),
    risks: () => getProjectRisks(projectId),
  });

  // All requests run in parallel
  // Partial failures don't break the page
  if (errors.dora) {
    console.warn('DORA metrics failed:', errors.dora);
  }

  return data;
}
```

### 4.4 In-Memory Cache with TTL

```typescript
import { fetchWithCache, invalidateProjectCache } from '../utils/apiOptimization';

// Cached fetch with stale-while-revalidate
const project = await fetchWithCache(
  `project-${projectId}`,
  () => api.get(`/v1/projects/${projectId}`),
  {
    ttlMs: 60000,                    // Fresh for 1 minute
    staleWhileRevalidateMs: 30000,   // Serve stale for 30s while refreshing
    deduplicate: true                // Prevent duplicate concurrent requests
  }
);

// Invalidate after mutation
await updateProject(projectId, changes);
invalidateProjectCache(projectId);
```

### 4.5 Batch Loading with DataLoader Pattern

```typescript
import { createBatchLoader } from '../utils/apiOptimization';

const userLoader = createBatchLoader({
  maxSize: 100,
  maxWaitMs: 10,
  batchFn: async (userIds: number[]) => {
    const users = await fetchUsersByIds(userIds);
    return new Map(users.map(u => [u.id, u]));
  }
});

// These calls are automatically batched:
const user1 = await userLoader.load(1);
const user2 = await userLoader.load(2);
const users = await userLoader.loadMany([3, 4, 5]);
// Result: Single API call with all IDs
```

---

## 5. Implementation Checklist

### Phase 1: Database Indexes (Immediate)

- [ ] Run `migrations/add_performance_indexes.sql` on database
- [ ] Verify index usage with `EXPLAIN ANALYZE`
- [ ] Monitor query performance

### Phase 2: Backend Caching (Week 1)

- [ ] Initialize `EnhancedCacheService` in application startup
- [ ] Add caching to `/analytics/projects/{id}/velocity` (WARM tier)
- [ ] Add caching to `/analytics/projects/{id}/team-health` (HOT tier)
- [ ] Add caching to `/analytics/sprints/{id}/burndown` (HOT tier)
- [ ] Add caching to `/traceability/matrix` (STATIC tier)
- [ ] Implement cache invalidation in mutation endpoints

### Phase 3: Batch Operations (Week 2)

- [ ] Replace N+1 queries in `traceability.py` cycle detection
- [ ] Replace N+1 queries in bulk delete endpoints
- [ ] Replace N+1 queries in flow graph traversal
- [ ] Add batch endpoints for task operations

### Phase 4: Pagination (Week 2)

- [ ] Add pagination to `/tasks` endpoint
- [ ] Add pagination to `/artifacts` endpoint
- [ ] Add cursor pagination for large lists
- [ ] Update frontend to handle pagination

### Phase 5: Frontend Optimization (Week 3)

- [ ] Add debouncing to task search input
- [ ] Add debouncing to filter dropdowns
- [ ] Convert sequential analytics loading to parallel
- [ ] Add request deduplication to project fetches
- [ ] Implement frontend caching layer

### Phase 6: Monitoring (Ongoing)

- [ ] Add cache hit/miss metrics
- [ ] Add query timing logs
- [ ] Set up slow query alerts
- [ ] Monitor Redis memory usage

---

## File Locations Summary

### Backend

| File | Purpose |
|------|---------|
| `/backend/app/core/cache_enhanced.py` | Redis caching service with tiered TTL |
| `/backend/app/utils/batch_operations.py` | Bulk delete, batch fetch, graph traversal |
| `/backend/app/schemas/pagination.py` | Pagination schemas and utilities |
| `/backend/migrations/add_performance_indexes.sql` | Database index migrations |

### Frontend

| File | Purpose |
|------|---------|
| `/frontend/src/utils/apiOptimization.ts` | Request deduplication, caching, batching |
| `/frontend/src/hooks/useDebounce.ts` | Debounce hooks for inputs |

---

## Performance Targets

| Metric | Current | Target |
|--------|---------|--------|
| Analytics page load | ~3-5s | <1s |
| Task list (1000 tasks) | ~2s | <500ms |
| Cache hit rate | 0% | >80% |
| Duplicate requests | ~30% | 0% |
| DB queries per page | ~50 | <10 |
