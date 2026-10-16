"""add_edited_deleted_at_and_job_proof

Revision ID: c10d3f82b7a9
Revises: f9d021c3b4a5
Create Date: 2026-10-03 03:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c10d3f82b7a9'
down_revision: Union[str, Sequence[str], None] = 'f9d021c3b4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('edited_at', sa.DateTime(), nullable=True))
    op.add_column('messages', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('publishing_jobs', sa.Column('platform_post_id', sa.String(length=255), nullable=True))
    op.add_column('publishing_jobs', sa.Column('manual_proof', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'deleted_at')
    op.drop_column('messages', 'edited_at')
    op.drop_column('publishing_jobs', 'manual_proof')
    op.drop_column('publishing_jobs', 'platform_post_id')
