"""add_kb_article_filters

Revision ID: dd3fc137f4e8
Revises: 1bfc94ceaa76
Create Date: 2026-08-05 16:27:54.620775

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd3fc137f4e8'
down_revision: Union[str, Sequence[str], None] = '1bfc94ceaa76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add filters to kb_articles
    op.add_column('kb_articles', sa.Column('review_status', sa.String(length=50), nullable=False, server_default='draft'))
    op.add_column('kb_articles', sa.Column('product', sa.String(length=100), nullable=True))
    op.add_column('kb_articles', sa.Column('risk_level', sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove filters from kb_articles
    op.drop_column('kb_articles', 'risk_level')
    op.drop_column('kb_articles', 'product')
    op.drop_column('kb_articles', 'review_status')
