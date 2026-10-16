from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class SocialAccountCreate(BaseModel):
    platform: str
    account_identifier: str
    access_token: str  # raw token, encrypted before saving


class SocialAccountRead(BaseModel):
    id: UUID
    tenant_id: UUID
    platform: str
    account_identifier: str
    status: str
    connected_at: datetime

    class Config:
        orm_mode = True


class ManualHandoffRequest(BaseModel):
    manual_proof: str | None = None
    proof_url: str | None = None
    proof_note: str | None = None