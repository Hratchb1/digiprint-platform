from datetime import timedelta
from typing import Optional
from uuid import UUID
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import get_settings
from app.core.timeutils import utcnow

settings = get_settings()
security = HTTPBearer()

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    payload = decode_token(credentials.credentials)
    return payload

async def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("store_admin", "master_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def effective_store_id(current_user: dict = Depends(get_current_user)) -> Optional[UUID]:
    """Single source of truth for store scoping.

    master_admin -> None (all stores; may still opt into a single store via
    an explicit ?store_id= query param handled by the caller).
    Everyone else -> their token's store_id, always. Client-supplied
    store_id query params are never consulted for non-admins — a store
    login cannot widen its own access by passing a different store_id.
    A non-admin with no store_id on their token (should not happen in
    practice, but the token is client-controlled data) gets 403 rather
    than silently falling through to all-stores.
    """
    if current_user.get("role") == "master_admin":
        return None
    sid = current_user.get("store_id")
    if not sid:
        raise HTTPException(status_code=403, detail="Account is not assigned to a store")
    return UUID(sid)


def assert_can_access(record, current_user: dict) -> None:
    """Raise 404 if the current user's token does not own this record's store.

    Works for any ORM object with a .store_id (Order, Roll, ...).
    404 (not 403) so cross-store IDs don't confirm a record exists.
    master_admin always passes.
    """
    if current_user.get("role") == "master_admin":
        return
    if str(record.store_id) != current_user.get("store_id"):
        raise HTTPException(status_code=404, detail="Not found")
