#!/usr/bin/env python3
"""
Performance Profiling Script for PO Helper

Run this script to measure actual performance bottlenecks
before deciding on optimizations.

Usage:
    cd backend
    python scripts/profile_performance.py

Requirements:
    - Running PostgreSQL database
    - Some test data in the database
"""

import asyncio
import time
import statistics
from datetime import datetime
from typing import List, Dict, Any

# Database setup
import sys
sys.path.insert(0, '.')

from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


# =============================================================================
# Configuration
# =============================================================================

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/po_helper"
# Adjust if your DB is different

SAMPLE_PROJECT_ID = 1  # Change to an existing project ID
NUM_ITERATIONS = 5     # Number of times to run each test


# =============================================================================
# Query Logger - Captures all SQL queries and their timing
# =============================================================================

class QueryLogger:
    """Logs all SQL queries with execution time."""

    def __init__(self):
        self.queries: List[Dict[str, Any]] = []
        self._start_times: Dict[int, float] = {}

    def before_execute(self, conn, clauseelement, multiparams, params, execution_options):
        self._start_times[id(clauseelement)] = time.perf_counter()

    def after_execute(self, conn, clauseelement, multiparams, params, execution_options, result):
        start = self._start_times.pop(id(clauseelement), None)
        if start:
            duration_ms = (time.perf_counter() - start) * 1000
            self.queries.append({
                'sql': str(clauseelement)[:200],  # Truncate long queries
                'duration_ms': duration_ms,
                'timestamp': datetime.now().isoformat(),
            })

    def clear(self):
        self.queries = []

    def summary(self) -> Dict[str, Any]:
        if not self.queries:
            return {'total_queries': 0}

        durations = [q['duration_ms'] for q in self.queries]
        return {
            'total_queries': len(self.queries),
            'total_time_ms': sum(durations),
            'avg_time_ms': statistics.mean(durations),
            'max_time_ms': max(durations),
            'min_time_ms': min(durations),
            'slowest_query': max(self.queries, key=lambda x: x['duration_ms']),
        }


# =============================================================================
# Profiling Functions
# =============================================================================

async def profile_endpoint(
    session: AsyncSession,
    name: str,
    query_func,
    logger: QueryLogger,
    iterations: int = NUM_ITERATIONS
) -> Dict[str, Any]:
    """Profile a single endpoint/query."""

    times = []
    query_counts = []
    success = True

    for i in range(iterations):
        logger.clear()

        start = time.perf_counter()
        try:
            await query_func(session)
        except Exception as e:
            success = False
            if i == 0:  # Only print error once
                print(f"  ⚠️  Error in {name}: {str(e)[:100]}")
            # Rollback to clear failed transaction
            await session.rollback()
        end = time.perf_counter()

        times.append((end - start) * 1000)  # ms
        query_counts.append(len(logger.queries))

    return {
        'name': name,
        'success': success,
        'iterations': iterations,
        'avg_time_ms': statistics.mean(times) if times else 0,
        'min_time_ms': min(times) if times else 0,
        'max_time_ms': max(times) if times else 0,
        'std_dev_ms': statistics.stdev(times) if len(times) > 1 else 0,
        'avg_queries': statistics.mean(query_counts) if query_counts else 0,
        'query_details': logger.summary(),
    }


async def test_tasks_list(session: AsyncSession):
    """Profile tasks list endpoint."""
    result = await session.execute(
        text("""
            SELECT t.*, p.name as project_name
            FROM tasks t
            LEFT JOIN projects p ON t.project_id = p.id
            WHERE t.project_id = :project_id
            LIMIT 500
        """),
        {'project_id': SAMPLE_PROJECT_ID}
    )
    return result.fetchall()


async def test_tasks_with_filters(session: AsyncSession):
    """Profile tasks with multiple filters (common dashboard query)."""
    result = await session.execute(
        text("""
            SELECT t.*
            FROM tasks t
            WHERE t.project_id = :project_id
              AND t.status NOT IN ('Done', 'Closed')
            ORDER BY t.created_at DESC
            LIMIT 100
        """),
        {'project_id': SAMPLE_PROJECT_ID}
    )
    return result.fetchall()


async def test_sprint_velocity(session: AsyncSession):
    """Profile sprint velocity calculation."""
    result = await session.execute(
        text("""
            SELECT
                s.id,
                s.name,
                COUNT(t.id) as total_tasks,
                SUM(CASE WHEN t.status IN ('Done', 'Closed') THEN 1 ELSE 0 END) as completed,
                SUM(COALESCE(t.estimate_hours, 0)) as total_hours,
                SUM(CASE WHEN t.status IN ('Done', 'Closed')
                    THEN COALESCE(t.estimate_hours, 0) ELSE 0 END) as completed_hours
            FROM sprints s
            LEFT JOIN tasks t ON t.sprint_id = s.id
            WHERE s.project_id = :project_id
            GROUP BY s.id, s.name
            ORDER BY s.start_date DESC
            LIMIT 10
        """),
        {'project_id': SAMPLE_PROJECT_ID}
    )
    return result.fetchall()


async def test_test_results_trend(session: AsyncSession):
    """Profile test results trend (last 30 days)."""
    result = await session.execute(
        text("""
            SELECT
                DATE(created_at) as day,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'passed' THEN 1 ELSE 0 END) as passed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM test_results
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY day DESC
        """)
    )
    return result.fetchall()


async def test_coverage_history(session: AsyncSession):
    """Profile coverage history query."""
    result = await session.execute(
        text("""
            SELECT *
            FROM coverage_reports
            WHERE created_at >= NOW() - INTERVAL '30 days'
            ORDER BY created_at DESC
            LIMIT 100
        """)
    )
    return result.fetchall()


async def test_n1_simulation(session: AsyncSession):
    """Simulate N+1 query pattern to show the problem."""
    # First get all projects
    projects = await session.execute(text("SELECT id FROM projects LIMIT 10"))
    project_ids = [r[0] for r in projects.fetchall()]

    # N+1: query tasks for each project separately
    all_tasks = []
    for pid in project_ids:
        tasks = await session.execute(
            text("SELECT * FROM tasks WHERE project_id = :pid LIMIT 50"),
            {'pid': pid}
        )
        all_tasks.extend(tasks.fetchall())

    return all_tasks


async def test_batch_alternative(session: AsyncSession):
    """Show batch alternative to N+1."""
    # First get all projects
    projects = await session.execute(text("SELECT id FROM projects LIMIT 10"))
    project_ids = [r[0] for r in projects.fetchall()]

    if not project_ids:
        return []

    # Batch: single query for all projects
    tasks = await session.execute(
        text("""
            SELECT * FROM tasks
            WHERE project_id = ANY(:pids)
            LIMIT 500
        """),
        {'pids': project_ids}
    )
    return tasks.fetchall()


# =============================================================================
# Index Analysis
# =============================================================================

async def analyze_indexes(session: AsyncSession) -> Dict[str, Any]:
    """Analyze existing indexes and suggest improvements."""

    # Get existing indexes
    indexes = await session.execute(
        text("""
            SELECT
                schemaname,
                tablename,
                indexname,
                indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY tablename, indexname
        """)
    )
    existing = indexes.fetchall()

    # Get table sizes
    sizes = await session.execute(
        text("""
            SELECT
                relname as table_name,
                pg_size_pretty(pg_total_relation_size(relid)) as total_size,
                pg_size_pretty(pg_indexes_size(relid)) as index_size,
                n_live_tup as row_count
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(relid) DESC
        """)
    )
    table_sizes = sizes.fetchall()

    # Get slow queries (if pg_stat_statements is enabled)
    slow_queries = []
    try:
        slow = await session.execute(
            text("""
                SELECT
                    query,
                    calls,
                    mean_exec_time,
                    total_exec_time
                FROM pg_stat_statements
                WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
                ORDER BY mean_exec_time DESC
                LIMIT 10
            """)
        )
        slow_queries = slow.fetchall()
    except Exception:
        pass  # pg_stat_statements not enabled

    return {
        'existing_indexes': len(existing),
        'indexes': [dict(zip(['schema', 'table', 'name', 'definition'], r)) for r in existing],
        'table_sizes': [dict(zip(['table', 'total_size', 'index_size', 'rows'], r)) for r in table_sizes],
        'slow_queries': slow_queries,
    }


# =============================================================================
# Main Profiling Runner
# =============================================================================

async def run_profiling():
    """Run all profiling tests."""

    print("=" * 60)
    print("🔍 PO Helper Performance Profiler")
    print("=" * 60)
    print()

    # Create engine with query logging
    engine = create_async_engine(DATABASE_URL, echo=False)
    logger = QueryLogger()

    # Attach query logger
    event.listen(engine.sync_engine, "before_execute", logger.before_execute)
    event.listen(engine.sync_engine, "after_execute", logger.after_execute)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Test database connection
        try:
            await session.execute(text("SELECT 1"))
            print("✅ Database connection OK")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            print("   Please check DATABASE_URL and ensure PostgreSQL is running")
            return

        print()
        print("-" * 60)
        print("📊 ENDPOINT PROFILING")
        print("-" * 60)

        tests = [
            ("Tasks List (500 items)", test_tasks_list),
            ("Tasks with Filters", test_tasks_with_filters),
            ("Sprint Velocity", test_sprint_velocity),
            ("Test Results Trend", test_test_results_trend),
            ("Coverage History", test_coverage_history),
            ("N+1 Pattern (bad)", test_n1_simulation),
            ("Batch Query (good)", test_batch_alternative),
        ]

        results = []
        for name, func in tests:
            print(f"\n  Testing: {name}...")
            result = await profile_endpoint(session, name, func, logger)
            results.append(result)

            status = "✅" if result['avg_time_ms'] < 100 else "⚠️" if result['avg_time_ms'] < 500 else "🔴"
            print(f"  {status} Avg: {result['avg_time_ms']:.2f}ms | Queries: {result['avg_queries']:.0f}")

        print()
        print("-" * 60)
        print("📈 RESULTS SUMMARY")
        print("-" * 60)
        print()
        print(f"{'Endpoint':<30} {'Avg (ms)':<12} {'Queries':<10} {'Status'}")
        print("-" * 60)

        for r in results:
            status = "✅ OK" if r['avg_time_ms'] < 100 else "⚠️ SLOW" if r['avg_time_ms'] < 500 else "🔴 CRITICAL"
            print(f"{r['name']:<30} {r['avg_time_ms']:<12.2f} {r['avg_queries']:<10.0f} {status}")

        # N+1 comparison
        n1_result = next((r for r in results if 'N+1' in r['name']), None)
        batch_result = next((r for r in results if 'Batch' in r['name']), None)

        if n1_result and batch_result and n1_result['avg_queries'] > 0:
            print()
            print("-" * 60)
            print("🔄 N+1 vs BATCH COMPARISON")
            print("-" * 60)
            speedup = n1_result['avg_time_ms'] / max(batch_result['avg_time_ms'], 0.1)
            query_reduction = n1_result['avg_queries'] / max(batch_result['avg_queries'], 1)
            print(f"  Time improvement: {speedup:.1f}x faster")
            print(f"  Query reduction:  {query_reduction:.1f}x fewer queries")

        # Index analysis
        print()
        print("-" * 60)
        print("🗂️  INDEX ANALYSIS")
        print("-" * 60)

        index_info = await analyze_indexes(session)
        print(f"\n  Total indexes: {index_info['existing_indexes']}")
        print("\n  Table sizes:")
        for ts in index_info['table_sizes'][:10]:
            print(f"    {ts['table']:<30} {ts['total_size']:<12} ({ts['rows']} rows)")

        # Recommendations
        print()
        print("-" * 60)
        print("💡 RECOMMENDATIONS")
        print("-" * 60)

        needs_optimization = [r for r in results if r['avg_time_ms'] > 100]

        if not needs_optimization:
            print("\n  ✅ All endpoints are performing well (<100ms)")
            print("  No immediate optimizations needed.")
        else:
            print(f"\n  ⚠️  {len(needs_optimization)} endpoints need attention:")
            for r in needs_optimization:
                print(f"    - {r['name']}: {r['avg_time_ms']:.0f}ms")
                if r['avg_queries'] > 5:
                    print(f"      → Consider batching ({r['avg_queries']:.0f} queries)")
                if r['avg_time_ms'] > 500:
                    print("      → Consider caching (response time > 500ms)")

        # Cache recommendation
        slow_endpoints = [r for r in results if r['avg_time_ms'] > 300]
        if slow_endpoints:
            print("\n  📦 Redis cache recommended for:")
            for r in slow_endpoints:
                print(f"    - {r['name']} (would reduce {r['avg_time_ms']:.0f}ms → ~5ms)")

    await engine.dispose()
    print()
    print("=" * 60)
    print("Profiling complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_profiling())
