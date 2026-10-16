"""alter media_assets file_url to text

Revision ID: 277c674d3f4a
Revises: 7e269f8587ea
Create Date: 2026-09-28 13:50:50.710574

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '277c674d3f4a'
down_revision: Union[str, Sequence[str], None] = '7e269f8587ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('media_assets') as batch_op:
        batch_op.alter_column('file_url', type_=sa.Text(), existing_type=sa.String(500))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('media_assets', 'file_url', type_=sa.String(500), existing_type=sa.Text())

