"""Add RBAC tables (roles and user_roles)

Revision ID: 017
Revises: 016
Create Date: 2025-10-01

This migration adds Role-Based Access Control (RBAC) tables:
- roles: Stores role definitions with permissions
- user_roles: Many-to-many association between users and roles

Default roles created:
- admin: Full system access
- po: Product Owner role
- developer: Team member role
- qa: Quality assurance role
- viewer: Read-only access
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from datetime import datetime


# revision identifiers, used by Alembic.
revision = '017_add_rbac_tables'
down_revision = '016'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if a table exists (database-agnostic)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Create RBAC tables and populate with system roles."""

    roles_created = False

    # Create roles table if it doesn't exist
    if not _table_exists('roles'):
        op.create_table(
            'roles',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('display_name', sa.String(), nullable=False),
            sa.Column('description', sa.String(), nullable=True),
            sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('permissions', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_roles_id'), 'roles', ['id'], unique=False, if_not_exists=True)
        op.create_index(op.f('ix_roles_name'), 'roles', ['name'], unique=True, if_not_exists=True)
        roles_created = True

    # Create user_roles association table if it doesn't exist
    if not _table_exists('user_roles'):
        op.create_table(
            'user_roles',
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('role_id', sa.Integer(), nullable=False),
            sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('user_id', 'role_id')
        )

    # Insert system roles only if table was just created (no existing data)
    connection = op.get_bind()
    result = connection.execute(sa.text("SELECT COUNT(*) FROM roles"))
    roles_count = result.scalar()

    if roles_count == 0:
        roles_table = table(
            'roles',
            column('name', sa.String),
            column('display_name', sa.String),
            column('description', sa.String),
            column('is_system', sa.Boolean),
            column('permissions', sa.String),
        )

        op.bulk_insert(
            roles_table,
            [
                {
                    'name': 'admin',
                    'display_name': 'Administrator',
                    'description': 'Full system access. Can manage users, settings, and all resources.',
                    'is_system': True,
                    'permissions': '["admin"]',
                },
                {
                    'name': 'po',
                    'display_name': 'Product Owner',
                    'description': 'Manage projects, sprints, and view analytics. Primary stakeholder role.',
                    'is_system': True,
                    'permissions': '["project:view", "project:create", "project:update", "project:delete", "task:view", "task:create", "task:update", "task:delete", "sprint:view", "sprint:create", "sprint:update", "sprint:delete", "analytics:view", "quality:view", "test:view", "traceability:view", "knowledge:view", "settings:view"]',
                },
                {
                    'name': 'developer',
                    'display_name': 'Developer',
                    'description': 'Create and update tasks, view project data. Team member role.',
                    'is_system': True,
                    'permissions': '["project:view", "task:view", "task:create", "task:update", "sprint:view", "analytics:view", "quality:view", "test:view", "traceability:view", "knowledge:view"]',
                },
                {
                    'name': 'qa',
                    'display_name': 'QA Engineer',
                    'description': 'Manage quality metrics, tests, and view project data. Quality assurance role.',
                    'is_system': True,
                    'permissions': '["project:view", "task:view", "task:update", "sprint:view", "quality:view", "quality:manage", "test:view", "test:manage", "analytics:view", "traceability:view", "knowledge:view"]',
                },
                {
                    'name': 'viewer',
                    'display_name': 'Viewer',
                    'description': 'Read-only access to projects, analytics, and reports. Stakeholder role.',
                    'is_system': True,
                    'permissions': '["project:view", "task:view", "sprint:view", "analytics:view", "quality:view", "test:view", "traceability:view", "knowledge:view", "settings:view"]',
                },
            ]
        )

    # Assign admin role to all existing superusers (only if users table exists)
    if _table_exists('users'):
        result = connection.execute(sa.text("SELECT id FROM roles WHERE name = 'admin'"))
        admin_role_id = result.scalar()

        if admin_role_id:
            # Get all superuser ids (use = true for PostgreSQL compatibility)
            result = connection.execute(sa.text("SELECT id FROM users WHERE is_superuser = true"))
            superuser_ids = [row[0] for row in result.fetchall()]

            # Assign admin role to superusers
            if superuser_ids:
                user_roles_table = table(
                    'user_roles',
                    column('user_id', sa.Integer),
                    column('role_id', sa.Integer),
                )
                # Use INSERT ... ON CONFLICT DO NOTHING for idempotency
                for uid in superuser_ids:
                    connection.execute(
                        sa.text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid) ON CONFLICT DO NOTHING"),
                        {"uid": uid, "rid": admin_role_id}
                    )


def downgrade() -> None:
    """Drop RBAC tables."""
    if _table_exists('user_roles'):
        op.drop_table('user_roles')
    if _table_exists('roles'):
        op.drop_index(op.f('ix_roles_name'), table_name='roles', if_exists=True)
        op.drop_index(op.f('ix_roles_id'), table_name='roles', if_exists=True)
        op.drop_table('roles')
