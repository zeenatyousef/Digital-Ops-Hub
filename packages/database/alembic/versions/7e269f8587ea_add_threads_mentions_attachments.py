"""add_threads_mentions_attachments

Revision ID: 7e269f8587ea
Revises: d060346f5186
Create Date: 2026-09-25 16:14:05.908405

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7e269f8587ea'
down_revision: Union[str, Sequence[str], None] = 'd060346f5186'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('messages', sa.Column('parent_message_id', sa.UUID(), nullable=True))
    with op.batch_alter_table('messages') as batch_op:
        batch_op.create_foreign_key(
            'fk_messages_parent_message_id', 'messages',
            ['parent_message_id'], ['id'], ondelete='SET NULL'
        )

    op.create_table(
        'message_mentions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('mentioned_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'message_attachments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_url', sa.Text(), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=True),
        sa.Column('file_type', sa.String(100), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('message_attachments')
    op.drop_table('message_mentions')
    op.drop_constraint('fk_messages_parent_message_id', 'messages', type_='foreignkey')
    op.drop_column('messages', 'parent_message_id')