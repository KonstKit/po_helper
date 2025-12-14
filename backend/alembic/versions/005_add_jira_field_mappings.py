"""add jira field mappings table

Revision ID: 005
Revises: 0001
Create Date: 2025-01-15

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers
revision = '005'
down_revision = '0001'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _ensure_columns(table_name: str, columns: list[sa.Column]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col['name'] for col in inspector.get_columns(table_name)}
    to_add = [column for column in columns if column.name not in existing]
    if not to_add:
        return
    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for column in to_add:
            batch_op.add_column(column)


def _ensure_index(table_name: str, name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx['name'] for idx in inspector.get_indexes(table_name)}
    if name in existing:
        return
    op.create_index(name, table_name, columns)


def _ensure_drop_index(table_name: str, name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx['name'] for idx in inspector.get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Create jira_field_mappings table for storing field discovery results
    if not _table_exists('jira_field_mappings'):
        op.create_table(
            'jira_field_mappings',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('jira_instance_url', sa.String(255), nullable=True),
            sa.Column('project_key', sa.String(50), nullable=True),
            sa.Column('field_type', sa.String(50), nullable=False),  # 'sprint', 'epic_link', etc
            sa.Column('field_id', sa.String(50), nullable=False),  # 'customfield_10601' or 'auto'
            sa.Column('field_name', sa.String(255), nullable=True),
            sa.Column('discovery_method', sa.String(20), nullable=True),  # 'manual', 'auto', 'api'
            sa.Column('confidence_score', sa.Float(), nullable=True),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
    # Ensure indexes exist (table already created above or previously)
    if _table_exists('jira_field_mappings'):
        _ensure_index(
            'jira_field_mappings',
            'idx_jira_field_mappings_lookup',
            ['jira_instance_url', 'field_type', 'is_active'],
        )
        _ensure_index(
            'jira_field_mappings',
            'idx_jira_field_mappings_project',
            ['project_key', 'field_type'],
        )

    # Add new columns to tasks table for additional Jira fields
    _ensure_columns(
        'tasks',
        [
            sa.Column('reporter_email', sa.String(255), nullable=True),
            sa.Column('reporter_name', sa.String(255), nullable=True),
            sa.Column('epic_link', sa.String(50), nullable=True),
            sa.Column('story_points', sa.Float(), nullable=True),
            sa.Column('aggregate_estimate_hours', sa.Float(), nullable=True),
            sa.Column('aggregate_spent_hours', sa.Float(), nullable=True),
            sa.Column('aggregate_remaining_hours', sa.Float(), nullable=True),
            sa.Column('custom_fields', sa.JSON(), nullable=True),
            sa.Column('parent_task_id', sa.Integer(), nullable=True),
        ],
    )

    inspector = sa.inspect(bind)
    fk_names = {fk['name'] for fk in inspector.get_foreign_keys('tasks')}
    if dialect != 'sqlite' and 'fk_tasks_parent' not in fk_names:
        op.create_foreign_key('fk_tasks_parent', 'tasks', 'tasks',
                              ['parent_task_id'], ['id'], ondelete='SET NULL')

    if _table_exists('tasks'):
        _ensure_index('tasks', 'idx_tasks_parent', ['parent_task_id'])

    _ensure_columns(
        'sprints',
        [
            sa.Column('custom_field_id', sa.String(50), nullable=True),
            sa.Column('raw_data', sa.JSON(), nullable=True),
        ],
    )


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Drop foreign key constraint
    if dialect != 'sqlite' and _table_exists('tasks'):
        inspector = sa.inspect(bind)
        fk_names = {fk['name'] for fk in inspector.get_foreign_keys('tasks')}
        if 'fk_tasks_parent' in fk_names:
            op.drop_constraint('fk_tasks_parent', 'tasks', type_='foreignkey')

    # Drop indexes
    if _table_exists('tasks'):
        _ensure_drop_index('tasks', 'idx_tasks_parent')
    if _table_exists('jira_field_mappings'):
        _ensure_drop_index('jira_field_mappings', 'idx_jira_field_mappings_project')
        _ensure_drop_index('jira_field_mappings', 'idx_jira_field_mappings_lookup')

    if _table_exists('tasks'):
        inspector = sa.inspect(bind)
        existing = {col['name'] for col in inspector.get_columns('tasks')}
        with op.batch_alter_table('tasks', schema=None) as batch_op:
            for column in [
                'reporter_email',
                'reporter_name',
                'epic_link',
                'story_points',
                'aggregate_estimate_hours',
                'aggregate_spent_hours',
                'aggregate_remaining_hours',
                'custom_fields',
                'parent_task_id',
            ]:
                if column in existing:
                    batch_op.drop_column(column)

    if _table_exists('sprints'):
        inspector = sa.inspect(bind)
        existing = {col['name'] for col in inspector.get_columns('sprints')}
        with op.batch_alter_table('sprints', schema=None) as batch_op:
            for column in ['custom_field_id', 'raw_data']:
                if column in existing:
                    batch_op.drop_column(column)

    if _table_exists('jira_field_mappings'):
        op.drop_table('jira_field_mappings')
