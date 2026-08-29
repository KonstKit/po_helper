# Metrics Audit Report — PO Helper Application

**Generated:** 2025-12-09
**Auditor:** AI Agent
**Project:** PO Helper v1.0.0
**Codebase Location:** `c:\Users\Use\IdeaProjects\po_helper`

---

## Executive Summary

This report provides a comprehensive analysis of the current observability and metrics instrumentation state of the PO Helper application, along with actionable recommendations for implementing production-grade monitoring following OpenTelemetry and Prometheus best practices.

**Key Findings:**
- ✅ **Basic infrastructure exists:** Sentry SDK integrated, custom metrics registry implemented
- ⚠️ **Limited coverage:** Only 6 metric types tracked across 3 modules (middleware, Jira service, Git webhooks)
- ❌ **Missing critical signals:** No HTTP request latency, database query metrics, or business KPIs
- ⚠️ **Non-standard implementation:** Custom metrics registry instead of prometheus_client
- ✅ **Good foundation:** Circuit breaker metrics, webhook tracking, error classification

---

## 1. Application Characteristics

### 1.1 Application Type & Architecture

| Characteristic | Value | Implication |
|----------------|-------|-------------|
| **Type** | Web API + Background Workers (Hybrid) | Requires Pull + Sidecar approach |
| **Framework** | FastAPI (async) | Auto-instrumentation available |
| **Workers** | Celery (prefork on Linux, solo on Windows) | Needs multiprocess-aware metrics |
| **Database** | SQLite (dev) / PostgreSQL (prod) | DB query metrics critical |
| **Infrastructure** | Docker Compose | ServiceMonitor-ready |
| **Criticality** | Production (Product Owner analytics) | SLO-driven monitoring required |

**Application Profile:**
```
PO Helper
├─ Backend: FastAPI (8000) - Async Web API
│  ├─ 28 API endpoint files
│  ├─ 94 Python modules (~7,732 LOC)
│  ├─ Services: Jira, Confluence, GitHub, GitLab, TestRail
│  └─ Business Logic: Analytics, Forecasting, Risk Management
├─ Workers: Celery + Redis
│  ├─ Async Jira synchronization
│  ├─ Background data processing
│  └─ Scheduled tasks (celery-beat)
└─ Frontend: React 18 + TypeScript
```

### 1.2 Current Monitoring Stack

```python
# Existing instrumentation
✅ sentry-sdk==1.40.6
   ├─ FastAPI integration
   ├─ SQLAlchemy integration
   ├─ Celery integration
   ├─ Logging integration
   └─ Performance tracing (traces_sample_rate)

⚠️ Custom MetricsRegistry (app/core/metrics.py)
   ├─ Thread-safe counters/gauges/histograms
   ├─ Prometheus-format export (/api/v1/health/metrics)
   └─ NOT using prometheus_client (non-standard)

❌ No OpenTelemetry
❌ No StatsD
❌ No dedicated Prometheus server configured
```

**Configuration (from .env.example):**
```env
SENTRY_DSN=https://xxxxx@sentry.io/xxxxx
SENTRY_TRACES_SAMPLE_RATE=0.0  # ⚠️ Disabled by default
SENTRY_PROFILES_SAMPLE_RATE=0.0  # ⚠️ Disabled by default
# PROMETHEUS_ENABLED=false  # Commented out
```

---

## 2. Current Metrics Inventory

### 2.1 Existing Metrics Analysis

| Metric | Type | Location | Labels | Cardinality | Status | Comment |
|--------|------|----------|--------|-------------|--------|---------|
| **Middleware Metrics** |
| `http_request_cancelled_total` | Counter | `core/middleware.py:35` | `path`, `method` | ~50-100 | ✅ OK | Client disconnects |
| **Jira Service Metrics (Circuit Breaker)** |
| `jira_cb_open` | Gauge | `services/jira_service.py:138,155` | — | 1 | ✅ OK | CB state (0/1) |
| `jira_cb_sleep_seconds` | Gauge | `services/jira_service.py:156` | — | 1 | ✅ OK | CB timeout |
| `jira_cb_open_total` | Counter | `services/jira_service.py:154` | — | 1 | ✅ OK | CB activation count |
| **Jira Service Metrics (Error Tracking)** |
| `jira_non_json_total` | Counter | `services/jira_service.py:208,359,459,626,665,708,752` | `ep`, `ver` | ~20-30 | ✅ OK | JSON parse errors |
| `jira_json_parse_error_total` | Counter | `services/jira_service.py:220,368,468` | `ep`, `ver` | ~15-20 | ✅ OK | Invalid JSON |
| `jira_worklog_timeout_total` | Counter | `services/jira_service.py:770` | `ver` | ~3-5 | ✅ OK | Timeout tracking |
| `jira_worklog_fail_total` | Counter | `services/jira_service.py:772` | `ver` | ~3-5 | ✅ OK | Generic failures |
| **Git Webhook Metrics** |
| `webhook_received` | Counter | `endpoints/git/webhooks.py:541,655` | `provider`, `event` | ~30-50 | ✅ OK | Webhook ingestion |
| `webhook_errors` | Counter | `endpoints/git/webhooks.py:619,708` | `provider`, `type` | ~20-30 | ✅ OK | Error classification |
| `webhook_circuit_open` | Counter | `endpoints/git/webhooks.py:517,633` | `provider` | ~3-5 | ✅ OK | Webhook CB |
| `webhook_rate_limited` | Counter | `endpoints/git/webhooks.py:522,638` | `provider` | ~3-5 | ✅ OK | Rate limiting |
| `datetime_parse_failures` | Counter | `endpoints/git/webhooks.py:69` | `source` | ~5-10 | ✅ OK | Date parsing |
| **CI/CD Metrics** |
| `ci_parse_errors` | Counter | `endpoints/git/ci.py:290,354` | `provider`, `type` | ~10-15 | ✅ OK | CI data parsing |
| `ci_tests_total` | Counter | `endpoints/git/ci.py:443` | `provider` | ~3-5 | ✅ OK | Test count |
| `ci_tests_failed` | Counter | `endpoints/git/ci.py:445` | `provider` | ~3-5 | ✅ OK | Failed tests |
| `ci_tests_passed` | Counter | `endpoints/git/ci.py:447` | `provider` | ~3-5 | ✅ OK | Passed tests |
| `ci_coverage_reports` | Counter | `endpoints/git/ci.py:450` | `provider` | ~3-5 | ✅ OK | Coverage ingestion |

**Summary:**
- ✅ **Strengths:** Good error classification, circuit breaker instrumentation
- ⚠️ **Gaps:** No latency metrics, no DB metrics, no business metrics
- ❌ **Critical Missing:** HTTP request duration, endpoint-level tracking

### 2.2 Cardinality Risk Assessment

| Metric Category | Estimated Cardinality | Risk Level | Notes |
|-----------------|----------------------|------------|-------|
| HTTP paths | ~50-100 endpoints | 🟢 Low | Well-scoped |
| Jira endpoints | ~20 unique `ep` values | 🟢 Low | Controlled |
| Webhook providers | 3-5 (GitHub, GitLab) | 🟢 Low | Fixed set |
| CI providers | 3-5 | 🟢 Low | Fixed set |
| **Overall** | **~150-200 series** | **🟢 Low** | Healthy baseline |

**No high-cardinality anti-patterns detected** ✅

---

## 3. Recommended Instrumentation Strategy

### 3.1 Technology Selection

#### Decision Tree Result: **Prometheus Client (with OTLP future-proofing)**

```
Reasoning:
├─ ✅ Sentry already integrated (traces/errors covered)
├─ ✅ Docker Compose infrastructure (easy Prometheus deployment)
├─ ✅ Existing custom registry (migration path to prometheus_client)
├─ ⚠️ No existing Prometheus server (needs setup)
└─ ✅ FastAPI ecosystem → prometheus-fastapi-instrumentator
```

**Recommended Stack:**

| Component | Technology | Justification |
|-----------|------------|---------------|
| **Metrics Library** | `prometheus_client==0.20.0` | Industry standard, battle-tested |
| **FastAPI Auto-instrumentation** | `prometheus-fastapi-instrumentator==7.0.0` | Zero-code HTTP metrics |
| **Celery Metrics** | `celery-exporter` (sidecar) | Official Celery metrics exporter |
| **Collection Model** | Pull (Prometheus scraping) | Long-running services, K8s-ready |
| **Aggregation** | Prometheus | Time-series database |
| **Visualization** | Grafana | Rich ecosystem |
| **Future-proofing** | OTLP exporter (optional) | OpenTelemetry migration path |

### 3.2 Collection Model: Hybrid Pull + Sidecar

```yaml
# Architecture
┌─────────────────────────────────────────────────────────────┐
│ FastAPI (port 8000)                                         │
│   ├─ /metrics endpoint (prometheus_client)  ← Prometheus   │
│   ├─ Auto-instrumentation (HTTP, DB)                        │
│   └─ Custom business metrics                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Celery Workers (prefork/solo)                               │
│   ├─ celery-exporter (sidecar, port 9808)  ← Prometheus    │
│   └─ Custom task metrics (multiprocess mode)                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Prometheus (port 9090)                                      │
│   ├─ Scrape interval: 15s                                   │
│   └─ Retention: 15 days                                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Missing Metrics — Prioritized Roadmap

### 4.1 CRITICAL (P0) — Implement Immediately

These metrics are **essential for production operations** and should be implemented before next deployment.

#### HTTP/API Metrics (Golden Signals)

```python
# Auto-instrumented by prometheus-fastapi-instrumentator

# Rate (Traffic)
http_requests_total{method, endpoint, status}  # Counter

# Errors
http_server_errors_total{method, endpoint, error_type}  # Counter

# Duration (Latency) — CRITICAL
http_request_duration_seconds{method, endpoint}  # Histogram
# Buckets: [.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10]

# Saturation
http_requests_in_progress{method, endpoint}  # Gauge

# Additional
http_request_size_bytes{endpoint}  # Histogram
http_response_size_bytes{endpoint}  # Histogram
```

**Implementation:** Add to `backend/requirements.txt`:
```txt
prometheus-client==0.20.0
prometheus-fastapi-instrumentator==7.0.0
```

**Code (main.py):**
```python
from prometheus_fastapi_instrumentator import Instrumentator

instrumentator = Instrumentator(
    should_group_status_codes=True,  # 200, 201 → 2xx
    should_ignore_untemplated=True,
    excluded_handlers=["/health", "/ready", "/metrics"],
)
instrumentator.instrument(app).expose(app, endpoint="/metrics")
```

#### Database Metrics

```python
# Location: Create app/core/db_metrics.py
from prometheus_client import Histogram, Gauge

db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query execution time',
    ['operation', 'table'],  # operation: select, insert, update, delete
    buckets=[.001, .005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5]
)

db_connection_pool_size = Gauge('db_connection_pool_size', 'Total pool size')
db_connection_pool_used = Gauge('db_connection_pool_used', 'Active connections')
db_connection_pool_available = Gauge('db_connection_pool_available', 'Idle connections')
```

**Integration Point:** SQLAlchemy event listeners in `app/core/database.py`

#### Celery Worker Metrics (via celery-exporter)

**Deployment:** Add to `docker-compose.yml`:
```yaml
celery-exporter:
  image: danihodovic/celery-exporter:latest
  ports:
    - "9808:9808"
  environment:
    - CELERY_BROKER_URL=${REDIS_URL}
  depends_on:
    - redis
```

**Auto-exported metrics:**
```
celery_task_total{task_name, status}  # sent, started, succeeded, failed, retried
celery_task_duration_seconds{task_name}
celery_queue_length{queue_name}
celery_worker_tasks_active{worker_name}
```

---

### 4.2 IMPORTANT (P1) — Next Sprint

#### External Dependencies Metrics

```python
# Jira API Metrics (enhance existing)
jira_request_duration_seconds = Histogram(
    'jira_request_duration_seconds',
    'Jira API request latency',
    ['endpoint', 'method'],
    buckets=[.1, .25, .5, 1, 2.5, 5, 10, 30]
)

jira_requests_total = Counter(
    'jira_requests_total',
    'Total Jira API requests',
    ['endpoint', 'method', 'status']
)

# Enhance existing circuit breaker metrics (already present ✅)
```

#### Cache Metrics

```python
# Location: app/services/cache_service.py
cache_operations_total = Counter(
    'cache_operations_total',
    'Cache operations',
    ['cache_name', 'operation', 'result']  # operation: get/set, result: hit/miss
)

cache_hit_ratio = Gauge(
    'cache_hit_ratio',
    'Cache hit ratio (0-1)',
    ['cache_name']
)
```

---

### 4.3 DESIRABLE (P2) — Backlog

#### Business Metrics (Domain-Specific)

Based on the Product Owner analytics domain:

```python
# Project/Sprint Metrics
sprints_created_total = Counter('sprints_created_total', 'Total sprints', ['project'])
sprints_completed_total = Counter('sprints_completed_total', 'Completed sprints', ['project'])

sprint_velocity_points = Gauge(
    'sprint_velocity_points',
    'Current sprint velocity',
    ['project', 'sprint_id']
)

# Jira Sync Metrics
jira_sync_duration_seconds = Histogram(
    'jira_sync_duration_seconds',
    'Jira data sync duration',
    ['project', 'sync_type'],  # sync_type: full, incremental
    buckets=[1, 5, 10, 30, 60, 300, 600]
)

jira_sync_issues_total = Counter(
    'jira_sync_issues_total',
    'Issues synchronized from Jira',
    ['project', 'status']  # status: created, updated, skipped
)

# Analytics Usage
analytics_queries_total = Counter(
    'analytics_queries_total',
    'Analytics endpoint queries',
    ['query_type']  # velocity, burndown, forecast, risk
)

analytics_query_duration_seconds = Histogram(
    'analytics_query_duration_seconds',
    'Analytics query latency',
    ['query_type'],
    buckets=[.1, .5, 1, 2.5, 5, 10, 30]
)
```

#### Git Integration Metrics (enhance existing)

```python
# Already have webhook_* metrics ✅
# Add:
pull_request_metrics_total = Counter(
    'pull_request_metrics_total',
    'Pull request events',
    ['repo', 'action']  # opened, merged, closed
)

pull_request_cycle_time_hours = Histogram(
    'pull_request_cycle_time_hours',
    'PR cycle time (created to merged)',
    ['repo'],
    buckets=[1, 4, 8, 24, 72, 168]  # hours
)
```

---

## 5. Implementation Plan

### Phase 1: Foundation (1-2 days)

**Goal:** Replace custom metrics with prometheus_client, add HTTP auto-instrumentation

**Tasks:**
1. ✅ Add dependencies:
   ```bash
   cd backend
   echo "prometheus-client==0.20.0" >> requirements.txt
   echo "prometheus-fastapi-instrumentator==7.0.0" >> requirements.txt
   pip install -r requirements.txt
   ```

2. ✅ Replace `app/core/metrics.py`:
   ```python
   # Old: Custom MetricsRegistry
   # New: Use prometheus_client directly
   from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
   ```

3. ✅ Update `app/main.py`:
   ```python
   from prometheus_fastapi_instrumentator import Instrumentator

   instrumentator = Instrumentator(
       should_group_status_codes=True,
       excluded_handlers=["/health", "/metrics"],
   ).instrument(app).expose(app)
   ```

4. ✅ Migrate existing metrics:
   - `jira_cb_*` → prometheus_client Gauge/Counter
   - `webhook_*` → prometheus_client Counter
   - `ci_*` → prometheus_client Counter

5. ✅ Test `/metrics` endpoint:
   ```bash
   curl http://localhost:8000/metrics
   ```

**Expected Output:**
```prometheus
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="GET",endpoint="/api/v1/projects",status="2xx"} 42.0

# HELP http_request_duration_seconds HTTP request latency
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{method="GET",endpoint="/api/v1/projects",le="0.005"} 10.0
...
```

---

### Phase 2: Database & Celery (2-3 days)

**Goal:** Add DB query tracking and Celery worker metrics

**Tasks:**
1. ✅ Implement SQLAlchemy event listeners:
   ```python
   # app/core/database.py
   from sqlalchemy import event
   from prometheus_client import Histogram
   import time

   db_query_duration_seconds = Histogram(...)

   @event.listens_for(Engine, "before_cursor_execute")
   def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
       conn.info.setdefault('query_start_time', []).append(time.time())

   @event.listens_for(Engine, "after_cursor_execute")
   def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
       total = time.time() - conn.info['query_start_time'].pop()
       operation = statement.split()[0].lower()  # SELECT, INSERT, etc.
       db_query_duration_seconds.labels(operation=operation, table="unknown").observe(total)
   ```

2. ✅ Deploy celery-exporter:
   ```yaml
   # docker-compose.yml
   celery-exporter:
     image: danihodovic/celery-exporter:latest
     ports:
       - "9808:9808"
     environment:
       - CELERY_BROKER_URL=${REDIS_URL}
   ```

3. ✅ Configure Celery multiprocess mode (if using prefork):
   ```python
   # app/tasks/__init__.py
   import os
   from prometheus_client import CollectorRegistry, multiprocess

   if platform.system() != 'Windows':
       os.environ.setdefault('PROMETHEUS_MULTIPROC_DIR', '/tmp/prometheus_multiproc')
   ```

---

### Phase 3: Business Metrics (2-3 days)

**Goal:** Track domain-specific operations

**Tasks:**
1. ✅ Create `app/core/business_metrics.py`:
   ```python
   from prometheus_client import Counter, Histogram, Gauge

   # Sprint metrics
   sprints_created_total = Counter(...)
   sprint_velocity_points = Gauge(...)

   # Jira sync metrics
   jira_sync_duration_seconds = Histogram(...)
   jira_sync_issues_total = Counter(...)
   ```

2. ✅ Instrument sync services:
   ```python
   # app/services/sync/project_sync_orchestrator.py
   from app.core.business_metrics import jira_sync_duration_seconds, jira_sync_issues_total

   async def sync_project(project_id: int):
       start = time.time()
       try:
           issues = await fetch_jira_issues()
           jira_sync_issues_total.labels(project=project.key, status='created').inc(len(issues))
           ...
       finally:
           jira_sync_duration_seconds.labels(project=project.key, sync_type='full').observe(time.time() - start)
   ```

3. ✅ Instrument analytics endpoints:
   ```python
   # app/api/api_v1/endpoints/analytics.py
   from app.core.business_metrics import analytics_queries_total, analytics_query_duration_seconds

   @router.get("/velocity")
   async def get_velocity(...):
       with analytics_query_duration_seconds.labels(query_type='velocity').time():
           analytics_queries_total.labels(query_type='velocity').inc()
           ...
   ```

---

### Phase 4: Infrastructure Setup (1-2 days)

**Goal:** Deploy Prometheus and Grafana

**Tasks:**
1. ✅ Update `docker-compose.yml`:
   ```yaml
   prometheus:
     image: prom/prometheus:latest
     ports:
       - "9090:9090"
     volumes:
       - ./docker/prometheus.yml:/etc/prometheus/prometheus.yml
       - prometheus_data:/prometheus
     command:
       - '--config.file=/etc/prometheus/prometheus.yml'
       - '--storage.tsdb.retention.time=15d'

   grafana:
     image: grafana/grafana:latest
     ports:
       - "3001:3000"
     environment:
       - GF_SECURITY_ADMIN_PASSWORD=admin
     volumes:
       - grafana_data:/var/lib/grafana
     depends_on:
       - prometheus

   volumes:
     prometheus_data:
     grafana_data:
   ```

2. ✅ Create `docker/prometheus.yml`:
   ```yaml
   global:
     scrape_interval: 15s
     evaluation_interval: 15s

   scrape_configs:
     - job_name: 'fastapi'
       static_configs:
         - targets: ['backend:8000']
       metrics_path: '/metrics'

     - job_name: 'celery'
       static_configs:
         - targets: ['celery-exporter:9808']
   ```

3. ✅ Create Grafana dashboards:
   - Golden Signals Dashboard (HTTP latency, errors, traffic)
   - Database Performance Dashboard
   - Celery Workers Dashboard
   - Business Metrics Dashboard (Jira sync, analytics)

---

## 6. Metrics Placement Guidelines

### 6.1 Layered Instrumentation (Preferred → Less Preferred)

```
1. AUTO-INSTRUMENTATION (Best)
   ├─ prometheus-fastapi-instrumentator → HTTP metrics
   ├─ celery-exporter → Celery metrics
   └─ SQLAlchemy events → DB metrics

2. MIDDLEWARE LEVEL
   ├─ HTTP middleware → request/response tracking
   └─ Database middleware → query tracking

3. DECORATOR LEVEL
   └─ @track_metrics decorators on functions

4. MANUAL INSTRUMENTATION (Only when necessary)
   └─ Business metrics inside functions
```

### 6.2 Anti-Patterns to Avoid

❌ **DO NOT:**
```python
# High cardinality — user IDs as labels
requests.labels(user_id=user.id).inc()

# Dynamic URLs without normalization
requests.labels(path=request.path).inc()  # /users/123, /users/456 → explosion

# Full error messages
errors.labels(message=str(exception)).inc()

# Metrics creation inside functions
def process_order():
    counter = Counter('orders', 'Orders')  # ❌ Created on every call!
```

✅ **DO:**
```python
# Classify users by type
requests.labels(user_type=user.subscription_tier).inc()  # free, pro, enterprise

# Normalize URLs
def normalize_path(path: str) -> str:
    return re.sub(r'/\d+', '/{id}', path)
requests.labels(path=normalize_path(request.path)).inc()

# Classify errors
def classify_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "validation"
    elif isinstance(exc, TimeoutError):
        return "timeout"
    return "internal"
errors.labels(error_type=classify_error(e)).inc()

# Global metric objects
ORDERS_TOTAL = Counter('orders_total', 'Orders')  # ✅ Module-level
```

---

## 7. Configuration & Environment Variables

### 7.1 Recommended .env Additions

```env
# ====================
# Metrics & Monitoring
# ====================
PROMETHEUS_ENABLED=true
PROMETHEUS_PORT=9090
PROMETHEUS_SCRAPE_INTERVAL=15s
PROMETHEUS_RETENTION_DAYS=15

# Sentry (already exists, update)
SENTRY_DSN=https://xxxxx@sentry.io/xxxxx
SENTRY_TRACES_SAMPLE_RATE=0.1  # 10% of transactions (was 0.0)
SENTRY_PROFILES_SAMPLE_RATE=0.1  # 10% profiling (was 0.0)
SENTRY_ENVIRONMENT=${ENVIRONMENT}

# Metrics export
METRICS_ENDPOINT=/metrics
METRICS_INCLUDE_PYTHON_RUNTIME=true  # gc, memory, etc.
```

### 7.2 Settings Class Updates

```python
# app/core/config.py
class Settings(BaseSettings):
    # ... existing ...

    # Sentry (enhance existing)
    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1  # Changed from 0.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.1  # Changed from 0.0

    # Prometheus (new)
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090
    PROMETHEUS_SCRAPE_INTERVAL: str = "15s"
    PROMETHEUS_RETENTION_DAYS: int = 15

    # Metrics (new)
    METRICS_ENDPOINT: str = "/metrics"
    METRICS_INCLUDE_PYTHON_RUNTIME: bool = True
```

---

## 8. Testing & Validation

### 8.1 Metrics Endpoint Smoke Test

```bash
# 1. Start services
docker-compose up -d

# 2. Generate traffic
curl http://localhost:8000/api/v1/projects
curl http://localhost:8000/api/v1/analytics/projects/1/velocity

# 3. Check metrics endpoint
curl http://localhost:8000/metrics | grep -E '^(http_|db_|celery_|jira_)'

# Expected output:
# http_requests_total{method="GET",endpoint="/api/v1/projects",status="2xx"} 1.0
# http_request_duration_seconds_bucket{...} ...
# db_query_duration_seconds_bucket{...} ...
```

### 8.2 Prometheus Query Examples

```promql
# Golden Signals

# 1. Request Rate (Traffic)
rate(http_requests_total[5m])

# 2. Error Rate
rate(http_server_errors_total[5m]) / rate(http_requests_total[5m])

# 3. Latency (p95)
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# 4. Saturation
http_requests_in_progress

# Business Metrics

# Jira sync success rate
sum(rate(jira_sync_issues_total{status="created"}[1h])) /
sum(rate(jira_sync_issues_total[1h]))

# Average sprint velocity (last 6 sprints)
avg_over_time(sprint_velocity_points[6w])
```

### 8.3 Alerting Rules (Prometheus)

```yaml
# docker/prometheus/alerts.yml
groups:
  - name: po_helper_alerts
    interval: 30s
    rules:
      # High error rate
      - alert: HighErrorRate
        expr: rate(http_server_errors_total[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High HTTP error rate (> 5%)"

      # Slow responses
      - alert: SlowResponses
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency > 5s"

      # Jira circuit breaker open
      - alert: JiraCircuitBreakerOpen
        expr: jira_cb_open == 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Jira API circuit breaker is open"

      # Database connection pool saturation
      - alert: DBPoolSaturated
        expr: db_connection_pool_available / db_connection_pool_size < 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "< 10% DB connections available"
```

---

## 9. Migration from Custom Metrics Registry

### 9.1 Backward Compatibility Strategy

**Option A: Drop-in Replacement (Recommended)**
```python
# Replace app/core/metrics.py entirely
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Compatibility wrapper (if needed)
class MetricsRegistry:
    def inc(self, name, value=1.0, labels=None):
        # Lookup or create Counter dynamically
        ...

    def set_gauge(self, name, value, labels=None):
        ...

    def observe(self, name, value, labels=None):
        ...

    def export_prometheus(self):
        return generate_latest().decode('utf-8')

metrics = MetricsRegistry()  # Keep existing API
```

**Option B: Gradual Migration**
1. Keep custom registry for 1 sprint
2. Add prometheus_client metrics alongside
3. Deprecate custom registry in sprint N+1
4. Remove in sprint N+2

### 9.2 Breaking Changes

| Old API | New API | Notes |
|---------|---------|-------|
| `metrics.inc(name, labels={...})` | `COUNTER.labels(**labels).inc()` | Metric must be defined globally |
| `metrics.set_gauge(name, value, labels)` | `GAUGE.labels(**labels).set(value)` | Same |
| `metrics.observe(name, value, labels)` | `HISTOGRAM.labels(**labels).observe(value)` | Same |
| `metrics.export_prometheus()` | `generate_latest()` | Returns bytes, not str |

**Migration Script:**
```python
# scripts/migrate_metrics.py
import re

# Regex patterns to find and replace
patterns = [
    (r"metrics\.inc\('(\w+)', labels=(\{[^}]+\})\)",
     r"\1_total.labels(**\2).inc()"),
    # ... more patterns
]

# Run on all .py files
```

---

## 10. Operational Checklist

### Pre-Deployment
- [ ] All dependencies added to `requirements.txt`
- [ ] Metrics endpoint returns valid Prometheus format
- [ ] No high-cardinality labels (all < 100 unique values)
- [ ] Multiprocess mode configured for Celery (if prefork)
- [ ] Prometheus server configured and scraping
- [ ] Grafana dashboards imported

### Post-Deployment
- [ ] Verify metrics appear in Prometheus UI
- [ ] Check for cardinality explosion (Query: `count({__name__=~".+"})`)
- [ ] Test alerting rules
- [ ] Set up Grafana alerts
- [ ] Document metric catalog (Grafana Explore + descriptions)
- [ ] Train team on PromQL queries

### Ongoing Maintenance
- [ ] Review metric cardinality weekly
- [ ] Prune unused metrics
- [ ] Update dashboards based on incidents
- [ ] Adjust alert thresholds

---

## 11. Resources & References

### Documentation
- **Prometheus Best Practices:** https://prometheus.io/docs/practices/instrumentation/
- **prometheus-fastapi-instrumentator:** https://github.com/trallnag/prometheus-fastapi-instrumentator
- **celery-exporter:** https://github.com/danihodovic/celery-exporter
- **OpenTelemetry Python:** https://opentelemetry.io/docs/languages/python/
- **Google SRE Book (Monitoring):** https://sre.google/sre-book/monitoring-distributed-systems/

### Tools
- **Prometheus:** https://prometheus.io/
- **Grafana:** https://grafana.com/
- **Sentry:** https://docs.sentry.io/platforms/python/

---

## 12. Summary & Next Steps

### Current State
- ✅ Basic error tracking via Sentry
- ✅ Custom metrics registry with Prometheus export
- ⚠️ **Only 18 metrics** across 3 modules
- ❌ **No HTTP latency tracking**
- ❌ **No database query metrics**
- ❌ **No business KPI metrics**

### Target State (after implementation)
- ✅ Auto-instrumented HTTP metrics (latency, errors, traffic)
- ✅ Database query performance tracking
- ✅ Celery worker/task metrics via sidecar
- ✅ Business metrics (Jira sync, analytics, sprints)
- ✅ Prometheus + Grafana stack deployed
- ✅ SLO-based alerting

### Implementation Timeline

| Phase | Duration | Priority | Dependencies |
|-------|----------|----------|--------------|
| **Phase 1: Foundation** | 1-2 days | P0 | None |
| **Phase 2: DB & Celery** | 2-3 days | P0 | Phase 1 |
| **Phase 3: Business Metrics** | 2-3 days | P1 | Phase 1 |
| **Phase 4: Infrastructure** | 1-2 days | P1 | Phases 1-3 |
| **Total** | **6-10 days** | — | — |

### Success Criteria
1. `/metrics` endpoint returns >50 unique metric series
2. P95 HTTP latency visible in Grafana
3. Database query breakdown by operation type
4. Jira sync duration tracked per project
5. Alerts firing for error rate > 5%

---

## Appendix A: Metric Naming Convention

Follow OpenTelemetry Semantic Conventions:

```
<domain>.<entity>.<action>_<unit>

Examples:
✅ http.server.request.duration_seconds
✅ db.client.query.duration_seconds
✅ jira.api.request.duration_seconds
✅ celery.task.execution.duration_seconds
✅ sprint.velocity.points (gauge)

❌ request_time (missing unit)
❌ errors (missing context)
❌ httpRequestDuration (camelCase)
```

---

## Appendix B: Cardinality Calculator

```python
# scripts/estimate_cardinality.py
"""
Estimate metric cardinality for PO Helper
"""

estimates = {
    'http_requests_total': {
        'method': 5,  # GET, POST, PUT, DELETE, PATCH
        'endpoint': 50,  # ~50 API endpoints
        'status': 5,  # 2xx, 3xx, 4xx, 5xx, timeout
    },
    'jira_requests_total': {
        'endpoint': 20,  # ~20 Jira API endpoints
        'method': 3,  # GET, POST, PUT
        'status': 5,
    },
    'webhook_received': {
        'provider': 3,  # GitHub, GitLab, Bitbucket
        'event': 10,  # push, pr, issue, etc.
    },
}

def calculate_cardinality(metric):
    import math
    return math.prod(estimates[metric].values())

for metric, labels in estimates.items():
    card = calculate_cardinality(metric)
    print(f"{metric}: {card} series ({labels})")

# Total:
total = sum(calculate_cardinality(m) for m in estimates)
print(f"\nEstimated total series: {total}")
```

**Output:**
```
http_requests_total: 1250 series ({'method': 5, 'endpoint': 50, 'status': 5})
jira_requests_total: 300 series ({'endpoint': 20, 'method': 3, 'status': 5})
webhook_received: 30 series ({'provider': 3, 'event': 10})

Estimated total series: 1580
```

**Risk Assessment:** 🟢 Low (< 10,000 series is healthy)

---

**END OF REPORT**

---

## How to Apply This Report

1. **Review:** Share with DevOps/SRE team
2. **Prioritize:** Confirm P0 vs P1 classification
3. **Assign:** Allocate 1-2 developers for 1 sprint
4. **Implement:** Follow Phase 1-4 sequentially
5. **Deploy:** Test in staging, then production
6. **Monitor:** Watch Grafana dashboards, tune alerts
7. **Iterate:** Add more business metrics as needed

**Questions?** Refer to the Resources section or contact the Observability team.
