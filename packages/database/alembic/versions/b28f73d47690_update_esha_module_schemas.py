"""update_esha_module_schemas

Revision ID: b28f73d47690
Revises: a93c726359f1
Create Date: 2026-08-07 17:29:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b28f73d47690'
down_revision: Union[str, Sequence[str], None] = 'a93c726359f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Update hashtag_sets table
    op.add_column('hashtag_sets', sa.Column('client_id', sa.UUID(), nullable=True))
    with op.batch_alter_table('hashtag_sets') as batch_op:
        batch_op.create_foreign_key(
            'fk_hashtag_sets_client_id_clients',
            'clients',
            ['client_id'], ['id'],
            ondelete='SET NULL'
        )
    op.add_column('hashtag_sets', sa.Column('category', sa.String(length=50), nullable=True))
    op.add_column('hashtag_sets', sa.Column('platform', sa.String(length=50), nullable=True))
    op.add_column('hashtag_sets', sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('hashtag_sets', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))

    # 2. Update hashtag_items table
    op.add_column('hashtag_items', sa.Column('exclusions', sa.Text(), nullable=True))
    op.add_column('hashtag_items', sa.Column('performance_score', sa.Float(), nullable=True))

    # 3. Update quality_runs table
    op.add_column('quality_runs', sa.Column('content_version_id', sa.UUID(), nullable=True))
    with op.batch_alter_table('quality_runs') as batch_op:
        batch_op.create_foreign_key(
            'fk_quality_runs_content_version_id_content_versions',
            'content_versions',
            ['content_version_id'], ['id'],
            ondelete='SET NULL'
        )
    op.add_column('quality_runs', sa.Column('input_version', sa.String(length=255), nullable=True))
    op.add_column('quality_runs', sa.Column('checks', sa.Text(), nullable=True))
    op.add_column('quality_runs', sa.Column('issues', sa.Text(), nullable=True))
    op.add_column('quality_runs', sa.Column('rule_version', sa.String(length=50), nullable=True))
    op.add_column('quality_runs', sa.Column('reviewer_id', sa.UUID(), nullable=True))
    with op.batch_alter_table('quality_runs') as batch_op:
        batch_op.create_foreign_key(
            'fk_quality_runs_reviewer_id_users',
            'users',
            ['reviewer_id'], ['id'],
            ondelete='SET NULL'
        )

    # 4. Update analytics_events table
    op.add_column('analytics_events', sa.Column('client_id', sa.UUID(), nullable=True))
    with op.batch_alter_table('analytics_events') as batch_op:
        batch_op.create_foreign_key(
            'fk_analytics_events_client_id_clients',
            'clients',
            ['client_id'], ['id'],
            ondelete='CASCADE'
        )
    op.add_column('analytics_events', sa.Column('object_type', sa.String(length=100), nullable=True))
    op.add_column('analytics_events', sa.Column('object_id', sa.UUID(), nullable=True))
    op.add_column('analytics_events', sa.Column('metrics', sa.Text(), nullable=True))
    op.add_column('analytics_events', sa.Column('source', sa.String(length=100), nullable=True))
    op.add_column('analytics_events', sa.Column('occurred_at', sa.DateTime(), nullable=True))

    # 5. Update report_snapshots table
    op.add_column('report_snapshots', sa.Column('client_id', sa.UUID(), nullable=False))
    with op.batch_alter_table('report_snapshots') as batch_op:
        batch_op.create_foreign_key(
            'fk_report_snapshots_client_id_clients',
            'clients',
            ['client_id'], ['id'],
            ondelete='CASCADE'
        )
    op.add_column('report_snapshots', sa.Column('period_start', sa.Date(), nullable=False))
    op.add_column('report_snapshots', sa.Column('period_end', sa.Date(), nullable=False))
    op.drop_column('report_snapshots', 'data')
    op.add_column('report_snapshots', sa.Column('dataset', sa.Text(), nullable=False))
    op.add_column('report_snapshots', sa.Column('completeness', sa.Text(), nullable=True))

    # 6. Create test_cases table
    op.create_table(
        'test_cases',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('scenario', sa.Text(), nullable=False),
        sa.Column('expected_result', sa.Text(), nullable=False),
        sa.Column('test_group', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 7. Create test_runs table
    op.create_table(
        'test_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('test_case_id', sa.UUID(), nullable=False),
        sa.Column('actual_result', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('evidence_url', sa.String(length=500), nullable=True),
        sa.Column('run_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['test_case_id'], ['test_cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 8. Create defects table
    op.create_table(
        'defects',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('test_run_id', sa.UUID(), nullable=True),
        sa.Column('owner_id', sa.UUID(), nullable=False),
        sa.Column('severity', sa.String(length=50), nullable=False),
        sa.Column('steps_to_reproduce', sa.Text(), nullable=False),
        sa.Column('expected', sa.Text(), nullable=False),
        sa.Column('actual', sa.Text(), nullable=False),
        sa.Column('screenshot_url', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['test_run_id'], ['test_runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 8. Drop defects table
    op.drop_table('defects')

    # 7. Drop test_runs table
    op.drop_table('test_runs')

    # 6. Drop test_cases table
    op.drop_table('test_cases')

    # 5. Rollback report_snapshots table changes
    op.drop_column('report_snapshots', 'completeness')
    op.drop_column('report_snapshots', 'dataset')
    op.add_column('report_snapshots', sa.Column('data', sa.Text(), nullable=False))
    op.drop_column('report_snapshots', 'period_end')
    op.drop_column('report_snapshots', 'period_start')
    op.drop_constraint('fk_report_snapshots_client_id_clients', 'report_snapshots', type_='foreignkey')
    op.drop_column('report_snapshots', 'client_id')

    # 4. Rollback analytics_events table changes
    op.drop_column('analytics_events', 'occurred_at')
    op.drop_column('analytics_events', 'source')
    op.drop_column('analytics_events', 'metrics')
    op.drop_column('analytics_events', 'object_id')
    op.drop_column('analytics_events', 'object_type')
    op.drop_constraint('fk_analytics_events_client_id_clients', 'analytics_events', type_='foreignkey')
    op.drop_column('analytics_events', 'client_id')

    # 3. Rollback quality_runs table changes
    op.drop_constraint('fk_quality_runs_reviewer_id_users', 'quality_runs', type_='foreignkey')
    op.drop_column('quality_runs', 'reviewer_id')
    op.drop_column('quality_runs', 'rule_version')
    op.drop_column('quality_runs', 'issues')
    op.drop_column('quality_runs', 'checks')
    op.drop_column('quality_runs', 'input_version')
    op.drop_constraint('fk_quality_runs_content_version_id_content_versions', 'quality_runs', type_='foreignkey')
    op.drop_column('quality_runs', 'content_version_id')

    # 2. Rollback hashtag_items table changes
    op.drop_column('hashtag_items', 'performance_score')
    op.drop_column('hashtag_items', 'exclusions')

    # 1. Rollback hashtag_sets table changes
    op.drop_column('hashtag_sets', 'is_active')
    op.drop_column('hashtag_sets', 'version')
    op.drop_column('hashtag_sets', 'platform')
    op.drop_column('hashtag_sets', 'category')
    op.drop_constraint('fk_hashtag_sets_client_id_clients', 'hashtag_sets', type_='foreignkey')
    op.drop_column('hashtag_sets', 'client_id')
