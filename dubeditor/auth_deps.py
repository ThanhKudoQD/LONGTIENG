"""
Auth dependencies cho FastAPI endpoints.

Sử dụng:
    @router.get("/", dependencies=[Depends(require_auth)])
    @router.get("/", dependencies=[Depends(require_admin)])
    @router.get("/")
    def list(user: User = Depends(get_current_user)):
        ...
"""
from typing import Optional
from fastapi import Depends, HTTPException, Request, Cookie
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import User, Project
from dubeditor.auth_service import get_user_by_session


SESSION_COOKIE_NAME = "nano_session"


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Trả User nếu có session hợp lệ, None nếu không. Không raise."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    return get_user_by_session(db, session_id)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Bắt buộc có user. Raise 401 nếu chưa login."""
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Cần đăng nhập")
    return user


def require_auth(user: User = Depends(get_current_user)) -> User:
    """Decorator-style: yêu cầu login."""
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Decorator-style: yêu cầu admin."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Cần quyền admin")
    return user


def check_project_access(project: Project, user: User) -> None:
    """Kiểm tra user có quyền truy cập project. Raise 403 nếu không.
    - Admin: full access.
    - User: chỉ project có owner_id == user.id.
    - Project legacy (owner_id NULL): chỉ admin access (đã được migrate gán admin).
    """
    if user.is_admin:
        return
    owner_id = getattr(project, 'owner_id', None)
    if owner_id is None:
        # Legacy — admin only
        raise HTTPException(status_code=403, detail="Project chưa có chủ — chỉ admin truy cập được")
    if owner_id != user.id:
        raise HTTPException(status_code=403, detail="Không có quyền truy cập project này")


def get_project_with_access(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    """Load project + check access. Dùng làm dependency."""
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project không tồn tại")
    check_project_access(p, user)
    return p
