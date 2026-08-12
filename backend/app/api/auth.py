from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.core.auth import hash_password, verify_password, create_access_token, get_current_user
from app.core.timeutils import utcnow
from app.models.orm import User
from app.models.schemas import LoginRequest, TokenResponse, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    await db.execute(update(User).where(User.id == user.id).values(last_login=utcnow()))
    await db.commit()
    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role, "store_id": str(user.store_id) if user.store_id else None, "initials": user.initials, "full_name": user.full_name})
    return TokenResponse(access_token=token, user={"id": str(user.id), "email": user.email, "full_name": user.full_name, "initials": user.initials, "role": user.role, "store_id": str(user.store_id) if user.store_id else None})
