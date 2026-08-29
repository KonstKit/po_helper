import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import types

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
import sqlalchemy.ext.asyncio as sa_asyncio
import sqlalchemy.orm as sa_orm
from sqlalchemy.orm import sessionmaker

if not hasattr(sa_asyncio, "async_sessionmaker"):
    sa_asyncio.async_sessionmaker = sessionmaker  # type: ignore[attr-defined]

if not hasattr(sa_orm, "DeclarativeBase"):
    _Base = sa_orm.declarative_base()

    class _CompatDeclarativeBase(_Base):
        __abstract__ = True

    sa_orm.DeclarativeBase = _CompatDeclarativeBase  # type: ignore[attr-defined]

rate_limit_module = types.ModuleType("app.core.rate_limit")


class _NoopLimiter:
    def limit(self, *_args, **_kwargs):
        def decorator(func):
            return func

        return decorator


rate_limit_module.limiter = _NoopLimiter()
rate_limit_module.RateLimitExceeded = Exception
rate_limit_module._rate_limit_exceeded_handler = lambda *args, **kwargs: None
sys.modules["app.core.rate_limit"] = rate_limit_module

links_module = importlib.import_module("app.api.api_v1.endpoints.traceability.links")
common_module = importlib.import_module("app.api.api_v1.endpoints.traceability.common")
settings = importlib.import_module("app.core.config").settings

traceability_matrix = links_module.traceability_matrix
_would_create_cycle = common_module._would_create_cycle


async def _fake_ensure_project_access(project_id, _db, _current_user):
    return SimpleNamespace(id=project_id)


links_module.ensure_project_access = _fake_ensure_project_access


@dataclass
class _DummyArtifact:
    id: int
    type: str
    project_id: int


class _DummyResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return [(value,) for value in self._values]


class _DummySession:
    def __init__(self, responses):
        self._responses = list(responses)

    async def execute(self, *_args, **_kwargs):
        if not self._responses:
            return _DummyResult([])
        return _DummyResult(self._responses.pop(0))


class _MatrixResult:
    def __init__(self, payload, scalar=False):
        self._payload = payload
        self._scalar = scalar

    def scalars(self):
        if not self._scalar:
            raise RuntimeError("Scalar data not available")
        return self

    def all(self):
        return self._payload


class _MatrixSession:
    def __init__(self, artifacts, outgoing_links, incoming_links=None):
        self._artifacts = artifacts
        self._outgoing_links = outgoing_links
        self._incoming_links = incoming_links if incoming_links is not None else []
        self._calls = 0

    async def execute(self, *_args, **_kwargs):
        if self._calls == 0:
            self._calls += 1
            return _MatrixResult(self._artifacts, scalar=True)
        elif self._calls == 1:
            self._calls += 1
            return _MatrixResult(self._outgoing_links)
        else:
            return _MatrixResult(self._incoming_links)


@pytest.mark.asyncio
async def test_would_create_cycle_detects_cycle():
    db = _DummySession(
        [
            [3],  # from node 2 -> [3]
            [1],  # from node 3 -> [1] closes the loop back to 1
        ]
    )
    assert await _would_create_cycle(db, from_id=1, to_id=2, link_type="implements") is True


@pytest.mark.asyncio
async def test_would_create_cycle_handles_acyclic_graph():
    db = _DummySession(
        [
            [3],  # node 2 -> [3]
            [],  # node 3 -> [] (no cycle)
        ]
    )
    assert await _would_create_cycle(db, from_id=1, to_id=2, link_type="implements") is False


@pytest.mark.asyncio
async def test_would_create_cycle_skips_non_dag_types():
    db = _DummySession([[99]])
    assert await _would_create_cycle(db, from_id=1, to_id=2, link_type="relates_to") is False


@pytest.mark.asyncio
async def test_traceability_matrix_includes_link_type_counts():
    original_cache = settings.ENABLE_MATRIX_CACHE
    settings.ENABLE_MATRIX_CACHE = False

    artifacts = [
        _DummyArtifact(id=1, type="requirement", project_id=42),
        _DummyArtifact(id=2, type="commit", project_id=42),
        _DummyArtifact(id=3, type="test_case", project_id=42),
    ]
    outgoing_links = [
        (1, "implements"),
        (1, "tests"),
        (2, "derives_from"),
    ]
    # incoming_links=[] means no links where these artifacts are targets
    session = _MatrixSession(artifacts, outgoing_links, incoming_links=[])

    try:
        result = await traceability_matrix(
            project_id=42, db=session, current_user=SimpleNamespace(is_active=True)
        )
    finally:
        settings.ENABLE_MATRIX_CACHE = original_cache

    assert result["total"] == 3
    per_type = result["per_type"]
    requirement_stats = per_type["requirement"]
    assert requirement_stats["link_type_counts"]["implements"] == 1
    assert requirement_stats["link_type_counts"]["tests"] == 1
    assert requirement_stats["link_type_artifact_counts"]["implements"] == 1
    assert requirement_stats["link_type_artifact_counts"]["tests"] == 1
    assert requirement_stats["link_count"] == pytest.approx(2.0)

    commit_stats = per_type["commit"]
    assert commit_stats["link_type_counts"]["derives_from"] == 1
    assert commit_stats["link_type_artifact_counts"]["derives_from"] == 1
