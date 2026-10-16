from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class MediaAssetCreate(BaseModel):
    campaign_id: Optional[UUID] = None
    file_url: str


class MediaAssetRead(BaseModel):
    id: UUID
    tenant_id: UUID
    campaign_id: Optional[UUID] = None
    file_url: str
    version_number: int
    is_locked: bool
    status: str
    reviewed_by_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        orm_mode = True