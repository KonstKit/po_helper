"""add_traceability_baselines_projections_sync

Revision ID: 027_add_traceability_baselines_projections_sync
Revises: 026_add_mfa_fields
Create Date: 2026-01-23
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "027_add_traceability_baselines_projections_sync"
down_revision = "026_add_mfa_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column("artifacts", sa.Column("source_system", sa.String(), nullable=True))
    op.add_column("artifacts", sa.Column("source_reference_id", sa.String(), nullable=True))
    op.add_column("artifacts", sa.Column("ingestion_run_id", sa.String(), nullable=True))
    op.create_index("ix_artifacts_created_by_id", "artifacts", ["created_by_id"])

    op.add_column(
        "artifact_links",
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column("artifact_links", sa.Column("created_via", sa.String(), nullable=True))
    op.add_column("artifact_links", sa.Column("source_system", sa.String(), nullable=True))
    op.add_column("artifact_links", sa.Column("source_reference_id", sa.String(), nullable=True))
    op.add_column("artifact_links", sa.Column("method", sa.String(), nullable=True))
    op.create_index("ix_artifact_links_created_by_id", "artifact_links", ["created_by_id"])

    op.create_table(
        "baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filters_json", sa.JSON(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_baselines_project_id", "baselines", ["project_id"])
    op.create_index("ix_baselines_created_by_id", "baselines", ["created_by_id"])

    op.create_table(
        "baseline_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("baseline_id", sa.Integer(), sa.ForeignKey("baselines.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("artifact_links.id"), nullable=True),
        sa.Column("included_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_baseline_items_baseline_id", "baseline_items", ["baseline_id"])
    op.create_index("ix_baseline_items_artifact_id", "baseline_items", ["artifact_id"])
    op.create_index("ix_baseline_items_link_id", "baseline_items", ["link_id"])

    op.create_table(
        "projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filters_json", sa.JSON(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_projections_project_id", "projections", ["project_id"])
    op.create_index("ix_projections_created_by_id", "projections", ["created_by_id"])

    op.create_table(
        "projection_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("projection_id", sa.Integer(), sa.ForeignKey("projections.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("artifact_links.id"), nullable=True),
        sa.Column("included_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_projection_items_projection_id", "projection_items", ["projection_id"])
    op.create_index("ix_projection_items_artifact_id", "projection_items", ["artifact_id"])
    op.create_index("ix_projection_items_link_id", "projection_items", ["link_id"])

    op.create_table(
        "sync_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("traceability_rules.id"), nullable=True),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cursor_in", sa.String(), nullable=True),
        sa.Column("cursor_out", sa.String(), nullable=True),
        sa.Column("item_counts", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sync_tasks_source_id", "sync_tasks", ["source_id"])
    op.create_index("ix_sync_tasks_project_id", "sync_tasks", ["project_id"])
    op.create_index("ix_sync_tasks_rule_id", "sync_tasks", ["rule_id"])

    op.create_table(
        "connector_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        sa.Column("auth_ref", sa.String(), nullable=True),
        sa.Column("rate_limit_policy", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
    )
    op.create_index("ix_connector_configs_project_id", "connector_configs", ["project_id"])
    op.create_index("ix_connector_configs_provider", "connector_configs", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_connector_configs_provider", table_name="connector_configs")
    op.drop_index("ix_connector_configs_project_id", table_name="connector_configs")
    op.drop_table("connector_configs")

    op.drop_index("ix_sync_tasks_rule_id", table_name="sync_tasks")
    op.drop_index("ix_sync_tasks_project_id", table_name="sync_tasks")
    op.drop_index("ix_sync_tasks_source_id", table_name="sync_tasks")
    op.drop_table("sync_tasks")

    op.drop_index("ix_projection_items_link_id", table_name="projection_items")
    op.drop_index("ix_projection_items_artifact_id", table_name="projection_items")
    op.drop_index("ix_projection_items_projection_id", table_name="projection_items")
    op.drop_table("projection_items")

    op.drop_index("ix_projections_created_by_id", table_name="projections")
    op.drop_index("ix_projections_project_id", table_name="projections")
    op.drop_table("projections")

    op.drop_index("ix_baseline_items_link_id", table_name="baseline_items")
    op.drop_index("ix_baseline_items_artifact_id", table_name="baseline_items")
    op.drop_index("ix_baseline_items_baseline_id", table_name="baseline_items")
    op.drop_table("baseline_items")

    op.drop_index("ix_baselines_created_by_id", table_name="baselines")
    op.drop_index("ix_baselines_project_id", table_name="baselines")
    op.drop_table("baselines")

    op.drop_index("ix_artifact_links_created_by_id", table_name="artifact_links")
    op.drop_column("artifact_links", "method")
    op.drop_column("artifact_links", "source_reference_id")
    op.drop_column("artifact_links", "source_system")
    op.drop_column("artifact_links", "created_via")
    op.drop_column("artifact_links", "created_by_id")

    op.drop_index("ix_artifacts_created_by_id", table_name="artifacts")
    op.drop_column("artifacts", "ingestion_run_id")
    op.drop_column("artifacts", "source_reference_id")
    op.drop_column("artifacts", "source_system")
    op.drop_column("artifacts", "created_by_id")
