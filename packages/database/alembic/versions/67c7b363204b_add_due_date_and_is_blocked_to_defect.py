"""add_due_date_and_is_blocked_to_defect

Revision ID: 67c7b363204b
Revises: 690360ec032d
Create Date: 2026-08-31 13:01:57.802360

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '67c7b363204b'
down_revision: Union[str, Sequence[str], None] = '690360ec032d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('defects', sa.Column('due_date', sa.DateTime(), nullable=True))
    op.add_column('defects', sa.Column('is_blocked', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('defects', 'due_date')
    op.drop_column('defects', 'is_blocked')
