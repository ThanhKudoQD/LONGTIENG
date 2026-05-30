"""
Admin router — CRUD users + filter projects.
Endpoints under /api/admin/*. Yêu cầu admin.
"""
from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
from pydantic import BaseModel, Field

from dubeditor.database import get_db
from dubeditor.models import User, Project
from dubeditor.auth_service import (
    create_user, hash_password, serialize_user,
    delete_all_sessions_of_user,
)
from dubeditor.auth_deps import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CreateUserIn(BaseModel):
    username: str
    password: str = Field(..., min_length=4)
    display_name: Optional[str] = None
    is_admin: bool = False


class UpdateUserIn(BaseModel):
    display_name: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(..., min_length=4)


# ─── User CRUD ────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id.asc()).all()
    # Đếm project per user
    from sqlalchemy import func
    counts = dict(db.query(Project.owner_id, func.count(Project.id))
                    .group_by(Project.owner_id).all())
    return [
        {**serialize_user(u), 'project_count': counts.get(u.id, 0)}
        for u in users
    ]


@router.post("/users")
def admin_create_user(body: CreateUserIn, db: Session = Depends(get_db)):
    try:
        u = create_user(db,
                        username=body.username,
                        password=body.password,
                        display_name=body.display_name,
                        is_admin=body.is_admin)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return serialize_user(u)


@router.patch("/users/{user_id}")
def admin_update_user(user_id: int, body: UpdateUserIn,
                      db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User không tồn tại")
    # Không cho phép admin tự deactivate hoặc xóa quyền admin của CHÍNH mình
    if u.id == admin.id:
        if body.is_active is False:
            raise HTTPException(400, "Không thể deactivate chính mình")
        if body.is_admin is False:
            raise HTTPException(400, "Không thể xóa quyền admin của chính mình")
    if body.display_name is not None:
        u.display_name = body.display_name.strip() or u.username
    if body.is_admin is not None:
        u.is_admin = bool(body.is_admin)
    if body.is_active is not None:
        u.is_active = bool(body.is_active)
        if not u.is_active:
            # Deactivate → xóa hết session
            delete_all_sessions_of_user(db, u.id)
    db.commit()
    db.refresh(u)
    return serialize_user(u)


@router.delete("/users/{user_id}")
def admin_delete_user(user_id: int,
                      db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    """
    Xóa user. Project của user → giữ nguyên (admin quyết định xóa riêng).
    """
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User không tồn tại")
    if u.id == admin.id:
        raise HTTPException(400, "Không thể xóa chính mình")

    # Đếm project trước khi xóa user (để báo admin)
    n_projects = db.query(Project).filter(Project.owner_id == u.id).count()

    # Xóa sessions trước (FK cascade nên không bắt buộc, nhưng explicit cho rõ)
    delete_all_sessions_of_user(db, u.id)

    # Project: set owner_id = NULL → orphan. Admin quyết định xóa riêng.
    db.query(Project).filter(Project.owner_id == u.id).update({'owner_id': None})

    db.delete(u)
    db.commit()
    return {
        'ok': True,
        'orphaned_projects': n_projects,
        'message': f"Đã xóa user. {n_projects} project trở thành mồ côi — vào trang Admin > Projects để xử lý.",
    }


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(user_id: int, body: ResetPasswordIn,
                          db: Session = Depends(get_db)):
    """
    Admin reset password cho user. Xóa hết session của user đó.
    """
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User không tồn tại")
    u.password_hash = hash_password(body.new_password)
    delete_all_sessions_of_user(db, u.id)
    db.commit()
    return {'ok': True}


# ─── Project filtering (admin only) ───────────────────────────────────────────

@router.get("/projects")
def admin_list_projects(
    owner_id: Optional[int] = None,
    days: Optional[int] = None,           # filter project tạo trong N ngày gần đây
    orphan_only: bool = False,            # chỉ project owner_id NULL
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List tất cả project (admin only).
    Filter:
      - owner_id: chỉ project của user này
      - days: chỉ tạo trong N ngày gần đây
      - orphan_only: chỉ project chưa có owner
      - search: tìm theo tên (case-insensitive)
    """
    from dubeditor.models import Subtitle
    from sqlalchemy import func

    q = db.query(Project)

    if orphan_only:
        q = q.filter(Project.owner_id == None)  # noqa: E711
    elif owner_id is not None:
        q = q.filter(Project.owner_id == owner_id)

    if days is not None and days > 0:
        cutoff = datetime.utcnow() - timedelta(days=days)
        q = q.filter(Project.created_at >= cutoff)

    if search:
        s = f"%{search.lower()}%"
        q = q.filter(func.lower(Project.name).like(s))

    projects = q.order_by(desc(Project.id)).all()

    # Tải tên owner cho mỗi project
    owner_ids = {p.owner_id for p in projects if p.owner_id is not None}
    owners = {u.id: u for u in db.query(User).filter(User.id.in_(owner_ids)).all()} if owner_ids else {}

    # Đếm subtitles per project
    sub_counts = dict(
        db.query(Subtitle.project_id, func.count(Subtitle.id))
          .filter(Subtitle.project_id.in_([p.id for p in projects]))
          .group_by(Subtitle.project_id).all()
    ) if projects else {}

    result = []
    for p in projects:
        owner = owners.get(p.owner_id) if p.owner_id else None
        result.append({
            'id': p.id,
            'name': p.name,
            'video_path': p.video_path,
            'created_at': (p.created_at.isoformat() + 'Z') if p.created_at else None,
            'owner_id': p.owner_id,
            'owner_username': owner.username if owner else None,
            'owner_display_name': owner.display_name if owner else None,
            'subtitle_count': sub_counts.get(p.id, 0),
        })
    return result


@router.post("/projects/{project_id}/transfer")
def admin_transfer_project(project_id: int, body: dict,
                            db: Session = Depends(get_db)):
    """Chuyển ownership project sang user khác. body: {new_owner_id: int | null}"""
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project không tồn tại")
    new_owner_id = body.get('new_owner_id')
    if new_owner_id is not None:
        # Verify user tồn tại
        if not db.query(User).filter(User.id == new_owner_id).first():
            raise HTTPException(400, "User mới không tồn tại")
    p.owner_id = new_owner_id
    db.commit()
    return {'ok': True}
