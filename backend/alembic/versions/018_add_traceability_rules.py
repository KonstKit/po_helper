"""add_traceability_rules

Revision ID: 018
Revises: 017
Create Date: 2025-10-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '018_add_traceability_rules'
down_revision = '017_add_rbac_tables'
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
    # Create traceability_rules table if it doesn't exist
    if not _table_exists('traceability_rules'):
        op.create_table(
            'traceability_rules',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('flow_json', sa.Text(), nullable=False),  # SQLite doesn't have JSON type
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('category', sa.String(length=50), nullable=True, server_default='custom'),
            sa.Column('tags', sa.Text(), nullable=True, server_default='[]'),  # SQLite doesn't have JSON type
            sa.Column('total_executions', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('successful_executions', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('failed_executions', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('last_executed_at', sa.DateTime(), nullable=True),
            sa.Column('created_by_id', sa.Integer(), nullable=True),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    # Create indexes for traceability_rules (idempotent)
    if _table_exists('traceability_rules'):
        _ensure_index('traceability_rules', 'ix_traceability_rules_name', ['name'])
        _ensure_index('traceability_rules', 'ix_traceability_rules_created_by_id', ['created_by_id'])
        _ensure_index('traceability_rules', 'ix_traceability_rules_project_id', ['project_id'])
        _ensure_index('traceability_rules', 'ix_traceability_rules_enabled', ['enabled'])
        _ensure_index('traceability_rules', 'ix_traceability_rules_category', ['category'])

    # Create traceability_rule_executions table if it doesn't exist
    if not _table_exists('traceability_rule_executions'):
        op.create_table(
            'traceability_rule_executions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('rule_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=False),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('links_created', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('links_updated', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('artifacts_processed', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('error_details', sa.Text(), nullable=True),  # SQLite doesn't have JSON type
            sa.Column('execution_context', sa.Text(), nullable=True),  # SQLite doesn't have JSON type
            sa.ForeignKeyConstraint(['rule_id'], ['traceability_rules.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )

    # Create indexes for traceability_rule_executions (idempotent)
    if _table_exists('traceability_rule_executions'):
        _ensure_index('traceability_rule_executions', 'ix_traceability_rule_executions_rule_id', ['rule_id'])
        _ensure_index('traceability_rule_executions', 'ix_traceability_rule_executions_status', ['status'])
        _ensure_index('traceability_rule_executions', 'ix_traceability_rule_executions_started_at', ['started_at'])


def downgrade():
    if _table_exists('traceability_rule_executions'):
        op.drop_index(op.f('ix_traceability_rule_executions_started_at'), table_name='traceability_rule_executions', if_exists=True)
        op.drop_index(op.f('ix_traceability_rule_executions_status'), table_name='traceability_rule_executions', if_exists=True)
        op.drop_index(op.f('ix_traceability_rule_executions_rule_id'), table_name='traceability_rule_executions', if_exists=True)
        op.drop_table('traceability_rule_executions')

    if _table_exists('traceability_rules'):
        op.drop_index(op.f('ix_traceability_rules_category'), table_name='traceability_rules', if_exists=True)
        op.drop_index(op.f('ix_traceability_rules_enabled'), table_name='traceability_rules', if_exists=True)
        op.drop_index(op.f('ix_traceability_rules_project_id'), table_name='traceability_rules', if_exists=True)
        op.drop_index(op.f('ix_traceability_rules_created_by_id'), table_name='traceability_rules', if_exists=True)
        op.drop_index(op.f('ix_traceability_rules_name'), table_name='traceability_rules', if_exists=True)
        op.drop_table('traceability_rules')
