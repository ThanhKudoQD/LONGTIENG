"""
Auth service — password hash, session management.

Dùng bcrypt cho password hash. Session store trong DB (table user_sessions).
Session vĩnh viễn — không expires_at, chỉ hết khi logout hoặc admin xóa.
"""
import logging
import secrets
import hashlib
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from dubeditor.models import User, UserSession

logger = logging.getLogger(__name__)

# Import bcrypt lazily để không crash nếu thiếu
try:
    import bcrypt
    _BCRYPT_AVAILABLE = True
except ImportError:
    bcrypt = None
    _BCRYPT_AVAILABLE = False
    logger.warning("bcrypt chưa cài. pip install bcrypt")


def hash_password(password: str) -> str:
    """Hash password với bcrypt. Fallback SHA256+salt nếu thiếu bcrypt (KHÔNG khuyến khích)."""
    if _BCRYPT_AVAILABLE:
        salt = bcrypt.gensalt(rounds=10)
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    # Fallback yếu — chỉ để dev test
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"sha256${salt}${h}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify password vs hash. Support cả bcrypt + sha256 fallback."""
    if not hashed:
        return False
    if hashed.startswith('sha256$'):
        try:
            _, salt, h = hashed.split('$')
            return hashlib.sha256((salt + password).encode()).hexdigest() == h
        except Exception:
            return False
    if _BCRYPT_AVAILABLE:
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception:
            return False
    return False


# ─── User CRUD ────────────────────────────────────────────────────────────────

def create_user(db: Session, username: str, password: str,
                display_name: Optional[str] = None,
                is_admin: bool = False) -> User:
    """Tạo user mới. Raise ValueError nếu username trùng."""
    username = username.strip().lower()
    if not username:
        raise ValueError("Username không được rỗng")
    if not password or len(password) < 4:
        raise ValueError("Password tối thiểu 4 ký tự")
    if db.query(User).filter(User.username == username).first():
        raise ValueError(f"Username '{username}' đã tồn tại")
    u = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        is_admin=is_admin,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    logger.info(f"[Auth] Created user: {username} (admin={is_admin})")
    return u


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    """Verify username/password → trả User nếu hợp lệ."""
    username = username.strip().lower()
    user = db.query(User).filter(User.username == username,
                                  User.is_active == True).first()  # noqa: E712
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


# ─── Session management ───────────────────────────────────────────────────────

def create_session(db: Session, user: User,
                   user_agent: Optional[str] = None,
                   ip: Optional[str] = None) -> str:
    """Tạo session row → trả session_id (UUID hex)."""
    session_id = secrets.token_hex(32)  # 64 chars
    sess = UserSession(
        id=session_id,
        user_id=user.id,
        user_agent=(user_agent or '')[:500],
        ip_address=(ip or '')[:50],
    )
    db.add(sess)
    # Update last_login_at
    user.last_login_at = datetime.utcnow()
    db.commit()
    return session_id


def get_user_by_session(db: Session, session_id: str) -> Optional[User]:
    """Load user từ session_id. Update last_seen_at."""
    if not session_id:
        return None
    sess = db.query(UserSession).filter(UserSession.id == session_id).first()
    if not sess:
        return None
    user = db.query(User).filter(User.id == sess.user_id,
                                  User.is_active == True).first()  # noqa: E712
    if not user:
        # User bị deactivate → xóa session
        db.delete(sess)
        db.commit()
        return None
    # Update last_seen (best-effort, không cần commit ngay)
    sess.last_seen_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
    return user


def delete_session(db: Session, session_id: str) -> bool:
    """Xóa session (logout)."""
    if not session_id:
        return False
    sess = db.query(UserSession).filter(UserSession.id == session_id).first()
    if not sess:
        return False
    db.delete(sess)
    db.commit()
    return True


def delete_all_sessions_of_user(db: Session, user_id: int) -> int:
    """Xóa tất cả session của 1 user (vd khi đổi password hoặc bị disable)."""
    n = db.query(UserSession).filter(UserSession.user_id == user_id).delete()
    db.commit()
    return n


# ─── Helper for endpoints ─────────────────────────────────────────────────────

def serialize_user(u: User) -> dict:
    return {
        'id': u.id,
        'username': u.username,
        'display_name': u.display_name,
        'is_admin': bool(u.is_admin),
        'is_active': bool(u.is_active),
        'created_at': (u.created_at.isoformat() + 'Z') if u.created_at else None,
        'last_login_at': (u.last_login_at.isoformat() + 'Z') if u.last_login_at else None,
    }
