import os
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from uuid import UUID

from packages.database.session import get_db
from packages.database.models import User

# Load settings from environment
SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY:
    is_testing_or_dev = (
        os.getenv("ALLOW_SQLITE_FALLBACK", "").lower() == "true" or
        os.getenv("TESTING", "").lower() == "true"
    )
    if is_testing_or_dev:
        SECRET_KEY = "super_secret_jwt_token_2026_zeenat_yousef_lead"
    else:
        raise RuntimeError(
            "JWT_SECRET environment variable is not set. "
            "Refusing to start with an insecure default signing key."
        )
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "5"))

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# In-memory token denylist (jti -> expire_timestamp) for logout invalidation
denylisted_jtis: Dict[str, float] = {}

# In-memory failed login tracking (key: "ip:email" -> list of failed timestamps)
failed_login_attempts: Dict[str, List[float]] = {}

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def denylist_jti(jti: str, expire_ts: float):
    denylisted_jtis[jti] = expire_ts

def is_jti_denylisted(jti: str) -> bool:
    if not jti:
        return True
    # Clean up expired entries lazily
    now = time.time()
    if jti in denylisted_jtis:
        if denylisted_jtis[jti] < now:
            del denylisted_jtis[jti]
            return False
        return True
    return False

def check_login_rate_limit(key: str):
    if LOGIN_RATE_LIMIT <= 0:
        return
    now = time.time()
    window_start = now - 60.0
    attempts = failed_login_attempts.get(key, [])
    # keep attempts within the last 60 seconds
    attempts = [t for t in attempts if t > window_start]
    failed_login_attempts[key] = attempts

    if len(attempts) >= LOGIN_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again in a minute."
        )

def record_failed_login(key: str):
    now = time.time()
    attempts = failed_login_attempts.get(key, [])
    attempts.append(now)
    failed_login_attempts[key] = attempts

def clear_failed_logins(key: str):
    if key in failed_login_attempts:
        del failed_login_attempts[key]

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Ensure jti claim is present in token payload
    jti = to_encode.get("jti") or uuid.uuid4().hex
    to_encode.update({
        "exp": expire,
        "jti": jti
    })
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token_payload(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        jti: str = payload.get("jti")
        
        if email is None or not jti or is_jti_denylisted(jti):
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated"
        )
    return current_user

def get_current_tenant(current_user: User = Depends(get_current_active_user)) -> UUID:
    return current_user.tenant_id

# Dependency factory for checking roles
class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_active_user)):
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' does not have permission to access this resource"
            )
        return current_user
