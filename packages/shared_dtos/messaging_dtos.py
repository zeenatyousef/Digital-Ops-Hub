from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List

# --- MESSAGE SCHEMAS ---

class MentionCreate(BaseModel):
    mentioned_user_id: UUID

class MentionRead(BaseModel):
    mentioned_user_id: UUID

    class Config:
        from_attributes = True
        orm_mode = True

class AttachmentCreate(BaseModel):
    file_url: str
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None

class AttachmentRead(BaseModel):
    file_url: str
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None

    class Config:
        from_attributes = True
        orm_mode = True

class MessageCreate(BaseModel):
    client_room_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    content_type: str = Field("text", description="text, file, system")
    content: str
    visibility: str = Field("external", description="external (visible to client), internal (internal only)")
    parent_message_id: Optional[UUID] = None
    mentioned_user_ids: Optional[List[UUID]] = []
    attachments: Optional[List[AttachmentCreate]] = []

class MessageRead(BaseModel):
    id: UUID
    client_room_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    sender_id: Optional[UUID] = None
    sender_role: Optional[str] = None
    content_type: str
    content: str
    visibility: str
    read_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime
    parent_message_id: Optional[UUID] = None
    mentions: List[MentionRead] = []
    attachments: List[AttachmentRead] = []

    class Config:
        from_attributes = True
        orm_mode = True

# --- CONVERSATION / DM SCHEMAS ---

class ConversationCreate(BaseModel):
    participant_ids: List[UUID]

class ConversationRead(BaseModel):
    id: UUID
    created_at: datetime

    class Config:
        orm_mode = True

# --- WORKITEM CONVERSION ---

class WorkitemConvertRequest(BaseModel):
    target_type: str = Field(..., description="defect, task, or test_case")
    severity: Optional[str] = Field("medium", description="critical, high, medium, low")
    owner_id: Optional[UUID] = Field(None, description="Owner ID for defect assignment")

# --- CLIENT ROOM / SUPPORT TICKET LIFE CYCLE ---

class ClientRoomCreate(BaseModel):
    client_id: UUID

class ClientRoomRead(BaseModel):
    id: UUID
    client_id: UUID
    tenant_id: UUID
    status: str
    created_at: datetime

    class Config:
        orm_mode = True

class ClientRoomStatusUpdate(BaseModel):
    status: str

# --- DEFECT / TASK SCHEMAS ---

class DefectRead(BaseModel):
    id: UUID
    tenant_id: UUID
    test_run_id: Optional[UUID] = None
    owner_id: UUID
    severity: str
    steps_to_reproduce: str
    expected: str
    actual: str
    screenshot_url: Optional[str] = None
    status: str
    due_date: Optional[datetime] = None
    is_blocked: bool = False
    created_at: datetime

    class Config:
        orm_mode = True

class DefectStatusUpdate(BaseModel):
    status: str

