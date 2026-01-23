"""Add composite indexes for query performance optimization.

This migration adds composite indexes identified through performance analysis:
- ix_artifacts_type_source_external: Fast artifact lookup by type/source/external_id
- ix_artifact_links_to_confidence: Optimized link queries with confidence filtering
- ix_suggested_score_project: Fast similarity-ordered suggestions per project
- ix_defect_metrics_period: Time-range queries for defect trend analysis
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if a table exists using SQLAlchemy inspector."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        indexes = inspector.get_indexes(table_name)
        return any(idx['name'] == index_name for idx in indexes)
    except Exception:
        return False


# Composite indexes for performance-critical query patterns
_COMPOSITE_INDEXES = (
    # Artifact lookup: type + source + external_id is common pattern for deduplication
    # and linking. The ix_artifact_identity index already covers (tenant_id, project_id, type, source, external_id)
    # but this narrower index helps when tenant/project are not in the query
    ("ix_artifacts_type_source_external", "artifacts", ["type", "source", "external_id"]),

    # ArtifactLink: queries often filter by to_artifact_id and sort/filter by confidence
    ("ix_artifact_links_to_confidence", "artifact_links", ["to_artifact_id", "confidence"]),

    # SuggestedLink: admin UI queries suggestions ordered by score within a project
    ("ix_suggested_score_project", "suggested_links", ["similarity_score", "project_id"]),

    # DefectMetrics: time-range trend analysis per project is common dashboard query
    ("ix_defect_metrics_period", "defect_metrics", ["project_id", "period_end"]),
)


def upgrade() -> None:
    for name, table, columns in _COMPOSITE_INDEXES:
        # Skip if table doesn't exist
        if not _table_exists(table):
            continue
        # Skip if index already exists
        if _index_exists(table, name):
            continue

        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(_COMPOSITE_INDEXES):
        if _table_exists(table):
            op.drop_index(name, table_name=table, if_exists=True)
