"""update_asma_module_schemas

Revision ID: a93c726359f1
Revises: dd3fc137f4e8
Create Date: 2026-08-07 16:31:18.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a93c726359f1'
down_revision: Union[str, Sequence[str], None] = 'dd3fc137f4e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Update brand_profiles table
    # Adding client_id as nullable=True first to make it compatible, then we can enforce constraint if needed, 
    # but since there are no existing rows in development, we can create it as nullable=False directly.
    op.add_column('brand_profiles', sa.Column('client_id', sa.UUID(), nullable=False))
    with op.batch_alter_table('brand_profiles') as batch_op:
        batch_op.create_foreign_key(
            'fk_brand_profiles_client_id_clients',
            'clients',
            ['client_id'], ['id'],
            ondelete='CASCADE'
        )
    op.add_column('brand_profiles', sa.Column('required_wording', sa.Text(), nullable=True))
    op.add_column('brand_profiles', sa.Column('prohibited_wording', sa.Text(), nullable=True))
    op.add_column('brand_profiles', sa.Column('contact_details', sa.Text(), nullable=True))
    op.add_column('brand_profiles', sa.Column('languages', sa.Text(), nullable=True))
    op.add_column('brand_profiles', sa.Column('client_rules', sa.Text(), nullable=True))
    op.add_column('brand_profiles', sa.Column('version_number', sa.Integer(), nullable=False, server_default='1'))

    # 2. Update campaign_briefs table
    op.drop_column('campaign_briefs', 'objectives')
    op.add_column('campaign_briefs', sa.Column('audience', sa.Text(), nullable=True))
    op.add_column('campaign_briefs', sa.Column('location', sa.Text(), nullable=True))
    op.add_column('campaign_briefs', sa.Column('offer', sa.Text(), nullable=True))
    op.add_column('campaign_briefs', sa.Column('dates', sa.Text(), nullable=True))
    op.add_column('campaign_briefs', sa.Column('deliverables', sa.Text(), nullable=True))
    op.add_column('campaign_briefs', sa.Column('platforms', sa.Text(), nullable=True))
    op.add_column('campaign_briefs', sa.Column('assets', sa.Text(), nullable=True))
    op.add_column('campaign_briefs', sa.Column('source_message_ids', sa.JSON(), nullable=True))
    op.add_column('campaign_briefs', sa.Column('missing_fields', sa.JSON(), nullable=True))
    op.add_column('campaign_briefs', sa.Column('approval_status', sa.String(length=50), nullable=False, server_default='pending'))

    # 3. Update calendar_items table
    op.add_column('calendar_items', sa.Column('platform', sa.String(length=100), nullable=True))
    op.add_column('calendar_items', sa.Column('objective', sa.Text(), nullable=True))
    op.add_column('calendar_items', sa.Column('status', sa.String(length=50), nullable=True))
    op.add_column('calendar_items', sa.Column('owner', sa.String(length=255), nullable=True))

    # 4. Update designer_briefs table
    op.drop_column('designer_briefs', 'instructions')
    op.add_column('designer_briefs', sa.Column('main_heading', sa.String(length=255), nullable=True))
    op.add_column('designer_briefs', sa.Column('supporting_text', sa.Text(), nullable=True))
    op.add_column('designer_briefs', sa.Column('cta', sa.Text(), nullable=True))
    op.add_column('designer_briefs', sa.Column('visual_direction', sa.Text(), nullable=True))
    op.add_column('designer_briefs', sa.Column('asset_references', sa.Text(), nullable=True))
    op.add_column('designer_briefs', sa.Column('sizes', sa.Text(), nullable=True))
    op.add_column('designer_briefs', sa.Column('logo_qr_rules', sa.Text(), nullable=True))
    op.add_column('designer_briefs', sa.Column('restrictions', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # 4. Rollback designer_briefs table changes
    op.drop_column('designer_briefs', 'restrictions')
    op.drop_column('designer_briefs', 'logo_qr_rules')
    op.drop_column('designer_briefs', 'sizes')
    op.drop_column('designer_briefs', 'asset_references')
    op.drop_column('designer_briefs', 'visual_direction')
    op.drop_column('designer_briefs', 'cta')
    op.drop_column('designer_briefs', 'supporting_text')
    op.drop_column('designer_briefs', 'main_heading')
    op.add_column('designer_briefs', sa.Column('instructions', sa.Text(), nullable=False, server_default=''))

    # 3. Rollback calendar_items table changes
    op.drop_column('calendar_items', 'owner')
    op.drop_column('calendar_items', 'status')
    op.drop_column('calendar_items', 'objective')
    op.drop_column('calendar_items', 'platform')

    # 2. Rollback campaign_briefs table changes
    op.drop_column('campaign_briefs', 'approval_status')
    op.drop_column('campaign_briefs', 'missing_fields')
    op.drop_column('campaign_briefs', 'source_message_ids')
    op.drop_column('campaign_briefs', 'assets')
    op.drop_column('campaign_briefs', 'platforms')
    op.drop_column('campaign_briefs', 'deliverables')
    op.drop_column('campaign_briefs', 'dates')
    op.drop_column('campaign_briefs', 'offer')
    op.drop_column('campaign_briefs', 'location')
    op.drop_column('campaign_briefs', 'audience')
    op.add_column('campaign_briefs', sa.Column('objectives', sa.Text(), nullable=True))

    # 1. Rollback brand_profiles table changes
    op.drop_column('brand_profiles', 'version_number')
    op.drop_column('brand_profiles', 'client_rules')
    op.drop_column('brand_profiles', 'languages')
    op.drop_column('brand_profiles', 'contact_details')
    op.drop_column('brand_profiles', 'prohibited_wording')
    op.drop_column('brand_profiles', 'required_wording')
    op.drop_constraint('fk_brand_profiles_client_id_clients', 'brand_profiles', type_='foreignkey')
    op.drop_column('brand_profiles', 'client_id')
