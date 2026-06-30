"""
Authentication for AutoMap v2.

Strategy: JWT stored in an httpOnly cookie named 'session'.
- Token lifetime: EXPIRE_DAYS days (renewed on each login, not on activity).
- Secret key must be set via JWT_SECRET env var; startup will crash if missing.
- `get_current_user` is the standard FastAPI dependency for protected API routes.
- `get_user_or_none` is used by HTML routes that redirect manually instead of raising 401.
- `require_permission(slug)` is a dependency factory for permission-gated routes.
"""
import os
from datetime import datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from models import User, get_db

SECRET_KEY  = os.environ["JWT_SECRET"]
ALGORITHM   = "HS256"
EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=EXPIRE_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")


# ── Dependencies ──────────────────────────────────────────────────────────────

def get_current_user(
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user_id = _decode_token(session)
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_user_or_none(session: str | None, db: Session) -> User | None:
    """Returns the authenticated user or None — for HTML routes that redirect manually."""
    if not session:
        return None
    try:
        user_id = _decode_token(session)
    except HTTPException:
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()


def require_permission(slug: str):
    def _check(user: User = Depends(get_current_user)) -> User:
        if not user.has_permission(slug):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission required: {slug}")
        return user
    return _check
