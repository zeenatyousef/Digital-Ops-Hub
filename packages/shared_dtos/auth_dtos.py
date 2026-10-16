from pydantic import BaseModel, Field, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional

# --- USER DTO SCHEMAS ---

class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    role: str = Field(..., description="super_admin, tenant_admin, designer, client_rep")
    phone_number: Optional[str] = None

class UserCreate(UserBase):
    tenant_id: UUID
    password: str

class UserRead(UserBase):
    id: UUID
    tenant_id: UUID
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True

# --- AUTHENTICATION SCHEMAS ---

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    tenant_id: Optional[UUID] = None
    role: Optional[str] = None
