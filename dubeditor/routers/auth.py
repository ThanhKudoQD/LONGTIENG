"""
Auth router — login, logout, me, change-password.

Endpoints under /api/auth/*
"""
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from dubeditor.database import get_db
from dubeditor.models import User
from dubeditor.auth_service import (
    authenticate, create_session, delete_session,
    verify_password, hash_password, serialize_user,
    delete_all_sessions_of_user,
)
from dubeditor.auth_deps import (
    SESSION_COOKIE_NAME,
    get_current_user, get_current_user_optional,
)

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=4)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Login. Set cookie session_id, trả user info.
    """
    user = authenticate(db, body.username, body.password)
    if not user:
        raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu")

    session_id = create_session(
        db, user,
        user_agent=request.headers.get('user-agent'),
        ip=request.client.host if request.client else None,
    )

    # Cookie: HttpOnly để JS không đọc được (chống XSS).
    # Không set Secure để dev local HTTP vẫn dùng được.
    # SameSite=lax — cho phép GET cross-site nhưng chặn POST CSRF.
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite='lax',
        max_age=60 * 60 * 24 * 365 * 5,   # 5 năm — coi như vĩnh viễn
        path='/',
    )

    return {'user': serialize_user(user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Logout. Xóa session DB + clear cookie.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        delete_session(db, session_id)
    response.delete_cookie(SESSION_COOKIE_NAME, path='/')
    return {'ok': True}


@router.get("/me")
def me(user: User = Depends(get_current_user_optional)):
    """
    Trả info user hiện tại (hoặc null nếu chưa login).
    Dùng cho FE check trạng thái auth.
    """
    if not user:
        return {'user': None}
    return {'user': serialize_user(user)}


@router.post("/change-password")
def change_password(body: ChangePasswordIn,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """
    Đổi mật khẩu. Yêu cầu mật khẩu cũ đúng.
    Sau khi đổi → invalidate tất cả session khác (force logout các tab/máy khác).
    """
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Mật khẩu cũ không đúng")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    # Xóa hết session của user này (force logout tất cả) — trừ session hiện tại
    # Cho đơn giản, xóa hết → user sẽ phải login lại trong tab này luôn.
    delete_all_sessions_of_user(db, user.id)
    return {'ok': True, 'message': 'Đổi mật khẩu thành công. Vui lòng đăng nhập lại.'}
