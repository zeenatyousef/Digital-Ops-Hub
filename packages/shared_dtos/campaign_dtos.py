from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List

# --- CONTENT VERSION SCHEMAS ---

class ContentVersionBase(BaseModel):
    version_number: int = 1
    ai_output: Optional[str] = None
    edited_content: Optional[str] = None
    status: str = Field("pending", description="pending, approved, rejected")
    platform: Optional[str] = None
    language: Optional[str] = None
    caption: Optional[str] = None
    cta: Optional[str] = None
    hashtags_reference: Optional[str] = None

class ContentVersionCreate(ContentVersionBase):
    pass

class ContentVersionRead(ContentVersionBase):
    id: UUID
    campaign_id: UUID
    approved_by_id: Optional[UUID] = None
    reviewer_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        orm_mode = True

# --- CAMPAIGN SCHEMAS ---

class CampaignBase(BaseModel):
    name: str
    client_id: UUID
    scheduled_publish_at: Optional[datetime] = None

class CampaignCreate(CampaignBase):
    platform: Optional[str] = None
    language: Optional[str] = None
    caption: Optional[str] = None
    cta: Optional[str] = None
    hashtags_reference: Optional[str] = None

class CampaignRead(CampaignBase):
    id: UUID
    tenant_id: UUID
    status: str = Field("draft", description="draft, pending_approval, approved, scheduled, published")
    created_at: datetime
    versions: List[ContentVersionRead] = []

    class Config:
        orm_mode = True

# --- PUBLISHING JOB SCHEMAS ---

class PublishingJobBase(BaseModel):
    campaign_id: UUID
    scheduled_at: datetime

class PublishingJobCreate(PublishingJobBase):
    pass

class PublishingJobRead(PublishingJobBase):
    id: UUID
    status: str = Field("queued", description="queued, processing, completed, failed, manual_handoff")
    idempotency_key: str
    retry_count: int = 0
    error_logs: Optional[str] = None
    completed_at: Optional[datetime] = None

    class Config:
        orm_mode = True

# --- CALENDAR ITEM SCHEMAS ---

class CalendarItemRead(BaseModel):
    id: UUID
    tenant_id: UUID
    campaign_brief_id: UUID
    scheduled_time: datetime
    content_draft: Optional[str] = None
    platform: Optional[str] = None
    objective: Optional[str] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


# --- BRAND PROFILE SCHEMAS ---

class BrandProfileBase(BaseModel):
    brand_name: str
    brand_voice: Optional[str] = None
    target_audience: Optional[str] = None
    required_wording: Optional[str] = None
    prohibited_wording: Optional[str] = None
    contact_details: Optional[str] = None
    languages: Optional[str] = None
    client_rules: Optional[str] = None
    version_number: int = 1

class BrandProfileCreate(BrandProfileBase):
    client_id: UUID

class BrandProfileRead(BrandProfileBase):
    id: UUID
    tenant_id: UUID
    client_id: UUID
    created_at: datetime

    class Config:
        orm_mode = True


# --- CAMPAIGN BRIEF SCHEMAS ---

class CampaignBriefBase(BaseModel):
    title: str
    audience: Optional[str] = None
    location: Optional[str] = None
    offer: Optional[str] = None
    dates: Optional[str] = None
    deliverables: Optional[str] = None
    platforms: Optional[str] = None
    assets: Optional[str] = None
    source_message_ids: Optional[List[UUID]] = None
    missing_fields: Optional[List[str]] = None
    approval_status: str = "pending"

class CampaignBriefCreate(CampaignBriefBase):
    brand_profile_id: UUID

class CampaignBriefRead(CampaignBriefBase):
    id: UUID
    tenant_id: UUID
    brand_profile_id: UUID
    created_at: datetime

    class Config:
        orm_mode = True


# --- DESIGNER BRIEF SCHEMAS ---

class DesignerBriefBase(BaseModel):
    campaign_id: Optional[UUID] = None
    content_version_id: Optional[UUID] = None
    main_heading: Optional[str] = None
    supporting_text: Optional[str] = None
    cta: Optional[str] = None
    visual_direction: Optional[str] = None
    asset_references: Optional[str] = None
    sizes: Optional[str] = None
    logo_qr_rules: Optional[str] = None
    restrictions: Optional[str] = None

class DesignerBriefCreate(DesignerBriefBase):
    pass

class DesignerBriefRead(DesignerBriefBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime

    class Config:
        orm_mode = True

