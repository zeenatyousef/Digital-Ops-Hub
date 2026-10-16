"""add_read_at_to_messages

Revision ID: e8d91f2c4a3b
Revises: 277c674d3f4a
Create Date: 2026-09-30 12:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8d91f2c4a3b'
down_revision: Union[str, Sequence[str], None] = '277c674d3f4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('read_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'read_at')
