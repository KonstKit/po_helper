"""add_rule_scheduling_columns

Revision ID: 024
Revises: 023
Create Date: 2025-10-06

Adds scheduling and webhook columns to traceability_rules table:
- schedule_cron: Cron expression for scheduled execution
- schedule_enabled: Whether scheduling is active
- trigger_on_webhook: Whether webhook triggering is enabled
- webhook_token: Secret token for webhook authentication
- next_scheduled_run: Pre-computed next run time

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '024_add_rule_scheduling_columns'
down_revision = '023_add_composite_performance_indexes'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if a table exists (database-agnostic)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns(table_name)}
    return column_name in columns


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx['name'] for idx in inspector.get_indexes(table_name)}
    return index_name in existing_indexes


def upgrade():
    if not _table_exists('traceability_rules'):
        # Table doesn't exist, skip migration
        return

    # Add scheduling columns if they don't exist
    if not _column_exists('traceability_rules', 'schedule_cron'):
        op.add_column(
            'traceability_rules',
            sa.Column('schedule_cron', sa.String(length=100), nullable=True)
        )

    if not _column_exists('traceability_rules', 'schedule_enabled'):
        op.add_column(
            'traceability_rules',
            sa.Column('schedule_enabled', sa.Boolean(), nullable=False, server_default='0')
        )

    if not _column_exists('traceability_rules', 'trigger_on_webhook'):
        op.add_column(
            'traceability_rules',
            sa.Column('trigger_on_webhook', sa.Boolean(), nullable=False, server_default='0')
        )

    if not _column_exists('traceability_rules', 'webhook_token'):
        op.add_column(
            'traceability_rules',
            sa.Column('webhook_token', sa.String(length=64), nullable=True)
        )

    if not _column_exists('traceability_rules', 'next_scheduled_run'):
        op.add_column(
            'traceability_rules',
            sa.Column('next_scheduled_run', sa.DateTime(timezone=True), nullable=True)
        )

    # Add indexes for efficient scheduling queries
    if not _index_exists('traceability_rules', 'ix_traceability_rules_schedule_enabled'):
        op.create_index(
            'ix_traceability_rules_schedule_enabled',
            'traceability_rules',
            ['schedule_enabled']
        )

    if not _index_exists('traceability_rules', 'ix_traceability_rules_next_scheduled_run'):
        op.create_index(
            'ix_traceability_rules_next_scheduled_run',
            'traceability_rules',
            ['next_scheduled_run']
        )

    if not _index_exists('traceability_rules', 'ix_traceability_rules_webhook_token'):
        op.create_index(
            'ix_traceability_rules_webhook_token',
            'traceability_rules',
            ['webhook_token'],
            unique=True
        )


def downgrade():
    if not _table_exists('traceability_rules'):
        return

    # Drop indexes first
    if _index_exists('traceability_rules', 'ix_traceability_rules_webhook_token'):
        op.drop_index('ix_traceability_rules_webhook_token', table_name='traceability_rules')

    if _index_exists('traceability_rules', 'ix_traceability_rules_next_scheduled_run'):
        op.drop_index('ix_traceability_rules_next_scheduled_run', table_name='traceability_rules')

    if _index_exists('traceability_rules', 'ix_traceability_rules_schedule_enabled'):
        op.drop_index('ix_traceability_rules_schedule_enabled', table_name='traceability_rules')

    # Drop columns
    if _column_exists('traceability_rules', 'next_scheduled_run'):
        op.drop_column('traceability_rules', 'next_scheduled_run')

    if _column_exists('traceability_rules', 'webhook_token'):
        op.drop_column('traceability_rules', 'webhook_token')

    if _column_exists('traceability_rules', 'trigger_on_webhook'):
        op.drop_column('traceability_rules', 'trigger_on_webhook')

    if _column_exists('traceability_rules', 'schedule_enabled'):
        op.drop_column('traceability_rules', 'schedule_enabled')

    if _column_exists('traceability_rules', 'schedule_cron'):
        op.drop_column('traceability_rules', 'schedule_cron')
