"""add_traceability_rules

Revision ID: 018
Revises: 017
Create Date: 2025-10-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '018_add_traceability_rules'
down_revision = '017_add_rbac_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Create traceability_rules table
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
    op.create_index(op.f('ix_traceability_rules_name'), 'traceability_rules', ['name'], unique=False)
    op.create_index(op.f('ix_traceability_rules_created_by_id'), 'traceability_rules', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_traceability_rules_project_id'), 'traceability_rules', ['project_id'], unique=False)
    op.create_index(op.f('ix_traceability_rules_enabled'), 'traceability_rules', ['enabled'], unique=False)
    op.create_index(op.f('ix_traceability_rules_category'), 'traceability_rules', ['category'], unique=False)

    # Create traceability_rule_executions table
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
    op.create_index(op.f('ix_traceability_rule_executions_rule_id'), 'traceability_rule_executions', ['rule_id'], unique=False)
    op.create_index(op.f('ix_traceability_rule_executions_status'), 'traceability_rule_executions', ['status'], unique=False)
    op.create_index(op.f('ix_traceability_rule_executions_started_at'), 'traceability_rule_executions', ['started_at'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_traceability_rule_executions_started_at'), table_name='traceability_rule_executions')
    op.drop_index(op.f('ix_traceability_rule_executions_status'), table_name='traceability_rule_executions')
    op.drop_index(op.f('ix_traceability_rule_executions_rule_id'), table_name='traceability_rule_executions')
    op.drop_table('traceability_rule_executions')

    op.drop_index(op.f('ix_traceability_rules_category'), table_name='traceability_rules')
    op.drop_index(op.f('ix_traceability_rules_enabled'), table_name='traceability_rules')
    op.drop_index(op.f('ix_traceability_rules_project_id'), table_name='traceability_rules')
    op.drop_index(op.f('ix_traceability_rules_created_by_id'), table_name='traceability_rules')
    op.drop_index(op.f('ix_traceability_rules_name'), table_name='traceability_rules')
    op.drop_table('traceability_rules')
