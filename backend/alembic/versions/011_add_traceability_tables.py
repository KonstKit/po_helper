"""add traceability tables"""

import sqlalchemy as sa
from alembic import op


revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


_ARTIFACT_TABLE = 'artifacts'
_ARTIFACT_LINKS_TABLE = 'artifact_links'
_SOURCES_TABLE = 'sources'
_SYNC_STATES_TABLE = 'sync_states'


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists(_ARTIFACT_TABLE):
        op.create_table(
            _ARTIFACT_TABLE,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tenant_id', sa.String(), nullable=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
            sa.Column('type', sa.String(), nullable=False),
            sa.Column('source', sa.String(), nullable=False),
            sa.Column('external_id', sa.String(), nullable=False),
            sa.Column('display_key', sa.String(), nullable=True),
            sa.Column('title', sa.String(), nullable=True),
            sa.Column('status', sa.String(), nullable=True),
            sa.Column('url', sa.String(), nullable=True),
            sa.Column('meta', sa.JSON(), nullable=True),
            sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
            sa.Column('parent_version_id', sa.Integer(), sa.ForeignKey('artifacts.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint('tenant_id', 'project_id', 'type', 'source', 'external_id', 'version', name='uq_artifact_identity'),
        )
        op.create_index('ix_artifact_identity', _ARTIFACT_TABLE, ['tenant_id', 'project_id', 'type', 'source', 'external_id'])

    if not _table_exists(_ARTIFACT_LINKS_TABLE):
        op.create_table(
            _ARTIFACT_LINKS_TABLE,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tenant_id', sa.String(), nullable=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
            sa.Column('from_artifact_id', sa.Integer(), sa.ForeignKey('artifacts.id'), nullable=False),
            sa.Column('to_artifact_id', sa.Integer(), sa.ForeignKey('artifacts.id'), nullable=False),
            sa.Column('link_type', sa.String(), nullable=False),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.Column('confidence_factors', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.UniqueConstraint('tenant_id', 'project_id', 'from_artifact_id', 'to_artifact_id', 'link_type', name='uq_artifact_link'),
        )
        op.create_index('ix_links_from_type', _ARTIFACT_LINKS_TABLE, ['from_artifact_id', 'link_type', 'to_artifact_id'])
        op.create_index('ix_links_to_type', _ARTIFACT_LINKS_TABLE, ['to_artifact_id', 'link_type', 'from_artifact_id'])
        op.create_index('idx_links_confidence_high', _ARTIFACT_LINKS_TABLE, ['from_artifact_id', 'to_artifact_id'])

    if not _table_exists(_SOURCES_TABLE):
        op.create_table(
            _SOURCES_TABLE,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tenant_id', sa.String(), nullable=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
            sa.Column('type', sa.String(), nullable=False),
            sa.Column('base_url', sa.String(), nullable=True),
            sa.Column('auth', sa.JSON(), nullable=True),
            sa.Column('scopes', sa.JSON(), nullable=True),
            sa.Column('settings', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_sources_identity', _SOURCES_TABLE, ['tenant_id', 'project_id', 'type'])

    if not _table_exists(_SYNC_STATES_TABLE):
        op.create_table(
            _SYNC_STATES_TABLE,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tenant_id', sa.String(), nullable=True),
            sa.Column('source_id', sa.Integer(), sa.ForeignKey('sources.id'), nullable=True),
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=True),
            sa.Column('last_cursor', sa.String(), nullable=True),
            sa.Column('last_event_id', sa.String(), nullable=True),
            sa.Column('etag', sa.String(), nullable=True),
            sa.Column('lag_seconds', sa.Float(), nullable=True),
            sa.Column('rate_limit_reset_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_sync_states_lookup', _SYNC_STATES_TABLE, ['tenant_id', 'project_id', 'source_id'])


def downgrade() -> None:
    for index_name in ('ix_sync_states_lookup',):
        op.drop_index(index_name, table_name=_SYNC_STATES_TABLE, if_exists=True)
    if _table_exists(_SYNC_STATES_TABLE):
        op.drop_table(_SYNC_STATES_TABLE)

    for index_name in ('ix_sources_identity',):
        op.drop_index(index_name, table_name=_SOURCES_TABLE, if_exists=True)
    if _table_exists(_SOURCES_TABLE):
        op.drop_table(_SOURCES_TABLE)

    for index_name in ('idx_links_confidence_high', 'ix_links_to_type', 'ix_links_from_type'):
        op.drop_index(index_name, table_name=_ARTIFACT_LINKS_TABLE, if_exists=True)
    if _table_exists(_ARTIFACT_LINKS_TABLE):
        op.drop_table(_ARTIFACT_LINKS_TABLE)

    for index_name in ('ix_artifact_identity',):
        op.drop_index(index_name, table_name=_ARTIFACT_TABLE, if_exists=True)
    if _table_exists(_ARTIFACT_TABLE):
        op.drop_table(_ARTIFACT_TABLE)
