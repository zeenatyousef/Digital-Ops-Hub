from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional

# --- MESSAGE SCHEMAS ---

class MessageBase(BaseModel):
    client_room_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    sender_id: Optional[UUID] = None
    content_type: str = Field("text", description="e.g., text, file, system")
    content: str
    visibility: str = Field("external", description="external (visible to client), internal (internal team only)")

class MessageCreate(MessageBase):
    pass

class MessageRead(MessageBase):
    id: UUID
    created_at: datetime

    class Config:
        orm_mode = True

# --- TICKET CLASSIFICATION SCHEMAS ---

class TicketPredictionBase(BaseModel):
    tenant_id: UUID
    client_room_id: Optional[UUID] = None
    predicted_category: str
    actual_category: Optional[str] = None
    confidence: Optional[float] = None

class TicketPredictionCreate(TicketPredictionBase):
    corrected_by_id: Optional[UUID] = None

class TicketPredictionRead(TicketPredictionBase):
    id: UUID
    corrected_by_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        orm_mode = True

# --- CONVERSATION SUMMARY SCHEMAS ---

class ConversationSummaryBase(BaseModel):
    tenant_id: UUID
    client_room_id: UUID
    summary_text: str

class ConversationSummaryCreate(ConversationSummaryBase):
    reviewer_id: Optional[UUID] = None

class ConversationSummaryRead(ConversationSummaryBase):
    id: UUID
    reviewer_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        orm_mode = True

# --- KNOWLEDGE BASE ARTICLE SCHEMAS ---

class KBArticleBase(BaseModel):
    tenant_id: UUID
    title: str
    content: str
    review_status: str = "draft"
    product: Optional[str] = None
    risk_level: Optional[str] = None

class KBArticleCreate(KBArticleBase):
    pass

class KBArticleRead(KBArticleBase):
    id: UUID
    created_at: datetime

    class Config:
        orm_mode = True

class KBArticleChunkRead(BaseModel):
    id: UUID
    kb_article_id: UUID
    chunk_index: int
    chunk_content: str
    vector_embedding: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True
