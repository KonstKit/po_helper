"""add_capacity_health_cfd_tables

Revision ID: 019
Revises: 018
Create Date: 2025-12-30

Adds three new tables for Iteration 7 (Sprint & Capacity Analytics):
- capacity_settings: Personalized capacity per team member
- team_health_checks: Team satisfaction metrics
- cfd_snapshots: Cumulative Flow Diagram daily snapshots
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '019_add_capacity_health_cfd_tables'
down_revision = '018_add_traceability_rules'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if a table exists (database-agnostic)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx['name'] for idx in inspector.get_indexes(table_name)}
    return index_name in existing_indexes


def _ensure_index(table_name: str, index_name: str, columns: list, unique: bool = False) -> None:
    """Create index only if it doesn't exist."""
    if not _index_exists(table_name, index_name):
        op.create_index(op.f(index_name), table_name, columns, unique=unique)


def upgrade():
    # ==========================================================================
    # Table 1: capacity_settings - Personalized capacity per team member
    # ==========================================================================
    if not _table_exists('capacity_settings'):
        op.create_table(
            'capacity_settings',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('assignee_email', sa.String(length=255), nullable=False),
            sa.Column('assignee_name', sa.String(length=255), nullable=True),
            sa.Column('hours_per_week', sa.Float(), nullable=False, server_default='40.0'),
            sa.Column('focus_factor', sa.Float(), nullable=False, server_default='0.8'),
            sa.Column('valid_from', sa.Date(), nullable=True),
            sa.Column('valid_to', sa.Date(), nullable=True),
            sa.Column('notes', sa.String(length=500), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if _table_exists('capacity_settings'):
        _ensure_index('capacity_settings', 'ix_capacity_settings_id', ['id'])
        _ensure_index('capacity_settings', 'ix_capacity_settings_project_id', ['project_id'])
        _ensure_index('capacity_settings', 'ix_capacity_settings_assignee_email', ['assignee_email'])

    # ==========================================================================
    # Table 2: team_health_checks - Team satisfaction metrics
    # ==========================================================================
    if not _table_exists('team_health_checks'):
        op.create_table(
            'team_health_checks',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=False),
            sa.Column('sprint_id', sa.Integer(), nullable=True),
            # Health metrics (1-5 scale)
            sa.Column('satisfaction', sa.Float(), nullable=True),
            sa.Column('workload_balance', sa.Float(), nullable=True),
            sa.Column('technical_debt_pressure', sa.Float(), nullable=True),
            sa.Column('collaboration_quality', sa.Float(), nullable=True),
            # Computed index (weighted average)
            sa.Column('happiness_index', sa.Float(), nullable=True),
            # Burnout risk indicators
            sa.Column('burnout_risk_score', sa.Float(), nullable=True),
            sa.Column('burnout_risk_factors', sa.String(length=500), nullable=True),
            # Context
            sa.Column('check_date', sa.Date(), nullable=False),
            sa.Column('respondent_count', sa.Integer(), nullable=True),
            sa.Column('notes', sa.String(length=1000), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
            sa.ForeignKeyConstraint(['sprint_id'], ['sprints.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if _table_exists('team_health_checks'):
        _ensure_index('team_health_checks', 'ix_team_health_checks_id', ['id'])
        _ensure_index('team_health_checks', 'ix_team_health_checks_project_id', ['project_id'])
        _ensure_index('team_health_checks', 'ix_team_health_checks_sprint_id', ['sprint_id'])
        _ensure_index('team_health_checks', 'ix_team_health_checks_check_date', ['check_date'])

    # ==========================================================================
    # Table 3: cfd_snapshots - Cumulative Flow Diagram daily snapshots
    # ==========================================================================
    if not _table_exists('cfd_snapshots'):
        op.create_table(
            'cfd_snapshots',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=False),
            sa.Column('sprint_id', sa.Integer(), nullable=True),
            sa.Column('snapshot_date', sa.Date(), nullable=False),
            # Status counts (common Jira statuses)
            sa.Column('backlog_count', sa.Integer(), server_default='0', nullable=True),
            sa.Column('todo_count', sa.Integer(), server_default='0', nullable=True),
            sa.Column('in_progress_count', sa.Integer(), server_default='0', nullable=True),
            sa.Column('in_review_count', sa.Integer(), server_default='0', nullable=True),
            sa.Column('testing_count', sa.Integer(), server_default='0', nullable=True),
            sa.Column('done_count', sa.Integer(), server_default='0', nullable=True),
            # Aggregated metrics
            sa.Column('total_count', sa.Integer(), server_default='0', nullable=True),
            sa.Column('wip_count', sa.Integer(), server_default='0', nullable=True),
            # Flow metrics (calculated)
            sa.Column('throughput', sa.Integer(), nullable=True),
            sa.Column('avg_cycle_time_hours', sa.Float(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
            sa.ForeignKeyConstraint(['sprint_id'], ['sprints.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if _table_exists('cfd_snapshots'):
        _ensure_index('cfd_snapshots', 'ix_cfd_snapshots_id', ['id'])
        _ensure_index('cfd_snapshots', 'ix_cfd_snapshots_project_id', ['project_id'])
        _ensure_index('cfd_snapshots', 'ix_cfd_snapshots_sprint_id', ['sprint_id'])
        _ensure_index('cfd_snapshots', 'ix_cfd_snapshots_snapshot_date', ['snapshot_date'])


def downgrade():
    # Drop cfd_snapshots
    if _table_exists('cfd_snapshots'):
        op.drop_index(op.f('ix_cfd_snapshots_snapshot_date'), table_name='cfd_snapshots', if_exists=True)
        op.drop_index(op.f('ix_cfd_snapshots_sprint_id'), table_name='cfd_snapshots', if_exists=True)
        op.drop_index(op.f('ix_cfd_snapshots_project_id'), table_name='cfd_snapshots', if_exists=True)
        op.drop_index(op.f('ix_cfd_snapshots_id'), table_name='cfd_snapshots', if_exists=True)
        op.drop_table('cfd_snapshots')

    # Drop team_health_checks
    if _table_exists('team_health_checks'):
        op.drop_index(op.f('ix_team_health_checks_check_date'), table_name='team_health_checks', if_exists=True)
        op.drop_index(op.f('ix_team_health_checks_sprint_id'), table_name='team_health_checks', if_exists=True)
        op.drop_index(op.f('ix_team_health_checks_project_id'), table_name='team_health_checks', if_exists=True)
        op.drop_index(op.f('ix_team_health_checks_id'), table_name='team_health_checks', if_exists=True)
        op.drop_table('team_health_checks')

    # Drop capacity_settings
    if _table_exists('capacity_settings'):
        op.drop_index(op.f('ix_capacity_settings_assignee_email'), table_name='capacity_settings', if_exists=True)
        op.drop_index(op.f('ix_capacity_settings_project_id'), table_name='capacity_settings', if_exists=True)
        op.drop_index(op.f('ix_capacity_settings_id'), table_name='capacity_settings', if_exists=True)
        op.drop_table('capacity_settings')
