"""add_client_id_to_users

Revision ID: f9d021c3b4a5
Revises: e8d91f2c4a3b
Create Date: 2026-10-01 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f9d021c3b4a5'
down_revision: Union[str, Sequence[str], None] = 'e8d91f2c4a3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('client_id', sa.UUID(), nullable=True))
    with op.batch_alter_table('users') as batch_op:
        batch_op.create_foreign_key('fk_users_client_id', 'clients', ['client_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_users_client_id', 'users', type_='foreignkey')
    op.drop_column('users', 'client_id')
