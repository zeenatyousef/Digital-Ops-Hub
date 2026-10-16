from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr

from packages.database.session import get_db
from packages.database.models import User, Tenant, AuditEvent
from packages.shared_dtos.auth_dtos import UserCreate, UserRead, Token
from apps.core_gateway.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_active_user,
    get_current_tenant,
    RoleChecker,
    oauth2_scheme,
    decode_token_payload,
    denylist_jti,
    check_login_rate_limit,
    record_failed_login,
    clear_failed_logins
)

router = APIRouter(prefix="/api", tags=["Authentication & User Management"])

class AdminUserCreateRequest(BaseModel):
    email: str
    role: str
    password: str
    full_name: Optional[str] = "Admin Created User"
    phone_number: Optional[str] = None

def log_audit_event(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, action: str, entity: str, entity_id: uuid.UUID, diff: str = None):
    audit = AuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        action_name=action,
        entity_name=entity,
        entity_id=entity_id,
        diff_data=diff,
        created_at=datetime.utcnow()
    )
    db.add(audit)

@router.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    # Check if tenant exists
    tenant = db.query(Tenant).filter(Tenant.id == user_in.tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with id '{user_in.tenant_id}' not found"
        )
        
    # Check if email is already registered
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
        
    # Create new user
    user = User(
        id=uuid.uuid4(),
        tenant_id=user_in.tenant_id,
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role,
        phone_number=user_in.phone_number,
        is_active=True
    )
    db.add(user)
    
    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during user registration: {str(e)}"
        )
    return user

@router.post("/admin/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def admin_create_user(
    req: AdminUserCreateRequest,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    """
    Admin user creation endpoint. tenant_id is resolved from the caller's JWT token.
    Validates role and hashes password.
    """
    valid_roles = ["super_admin", "tenant_admin", "designer", "client_rep"]
    if req.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{req.role}'. Must be one of {valid_roles}"
        )

    existing_user = db.query(User).filter(User.email == req.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email=req.email,
        password_hash=get_password_hash(req.password),
        full_name=req.full_name,
        role=req.role,
        phone_number=req.phone_number,
        is_active=True
    )
    db.add(user)

    log_audit_event(
        db, tenant_id, current_user.id, "admin_create_user", "User", user_id,
        diff=f"email: {req.email}, role: {req.role}"
    )

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error creating user: {str(e)}")

    return user

@router.post("/auth/login", response_model=Token)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    client_ip = request.client.host if request.client else "127.0.0.1"
    rate_key = f"{client_ip}:{form_data.username}"
    
    # Check rate limit (5 failed attempts per min per IP+email)
    check_login_rate_limit(rate_key)

    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        record_failed_login(rate_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        record_failed_login(rate_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated"
        )
        
    clear_failed_logins(rate_key)

    # Generate token containing basic claims and jti
    access_token = create_access_token(
        data={
            "sub": user.email,
            "tenant_id": str(user.tenant_id),
            "role": user.role
        }
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/auth/logout")
def logout(token: str = Depends(oauth2_scheme)):
    payload = decode_token_payload(token)
    jti = payload.get("jti")
    exp = payload.get("exp", 0)
    if jti:
        denylist_jti(jti, float(exp))
    return {"message": "Successfully logged out"}

@router.post("/auth/refresh", response_model=Token)
def refresh_token(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    payload = decode_token_payload(token)
    jti = payload.get("jti")
    exp = payload.get("exp", 0)
    email = payload.get("sub")

    if not email or (jti and denylist_jti.__globals__['is_jti_denylisted'](jti)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account is inactive or not found")

    # Invalidate previous token
    if jti:
        denylist_jti(jti, float(exp))

    # Issue new access token
    new_token = create_access_token(
        data={
            "sub": user.email,
            "tenant_id": str(user.tenant_id),
            "role": user.role
        }
    )
    return {"access_token": new_token, "token_type": "bearer"}

@router.get("/auth/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_active_user)):
    return current_user

@router.get("/users", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Retrieve all users belonging to the caller's tenant."""
    users = db.query(User).filter(
        User.tenant_id == current_user.tenant_id
    ).all()
    return users

@router.patch("/users/{user_id}/disable", response_model=UserRead)
def disable_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable your own account"
        )

    user = db.query(User).filter(User.id == user_id, User.tenant_id == tenant_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = False

    log_audit_event(
        db, tenant_id, current_user.id, "disable_user", "User", user_id,
        diff=f"email: {user.email}, is_active: -> False"
    )

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error disabling user: {str(e)}")

    return user

@router.patch("/users/{user_id}/enable", response_model=UserRead)
@router.post("/users/{user_id}/enable", response_model=UserRead)
def enable_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    user = db.query(User).filter(User.id == user_id, User.tenant_id == tenant_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = True

    log_audit_event(
        db, tenant_id, current_user.id, "enable_user", "User", user_id,
        diff=f"email: {user.email}, is_active: -> True"
    )

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error enabling user: {str(e)}")

    return user
