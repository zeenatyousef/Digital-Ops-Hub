from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional, List

from packages.shared_dtos.campaign_dtos import CampaignRead
from packages.shared_dtos.auth_dtos import UserRead


class ClientCreate(BaseModel):
    company_name: str
    industry: Optional[str] = None
    contact_email: EmailStr


class ClientRead(BaseModel):
    id: UUID
    tenant_id: UUID
    company_name: str
    industry: Optional[str] = None
    contact_email: str
    created_at: datetime

    class Config:
        orm_mode = True


class ClientDetailRead(ClientRead):
    campaigns: List[CampaignRead] = []
    team_members: List[UserRead] = []

    class Config:
        orm_mode = True