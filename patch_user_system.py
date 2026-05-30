#!/usr/bin/env python3
"""
patch_user_system.py — Auto patch script cài User System v5.0.

Sửa an toàn:
  - dubeditor/router.py — thêm 2 router (auth, admin)
  - dubeditor/models.py — append User + UserSession (nếu chưa có)

Idempotent. Backup .bak trước khi sửa.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
ROUTER_FILE = ROOT / "dubeditor" / "router.py"
MODELS_FILE = ROOT / "dubeditor" / "models.py"


ROUTER_IMPORT = "from dubeditor.routers import auth as auth_router  # v5.0 — User auth\nfrom dubeditor.routers import admin as admin_router  # v5.0 — Admin CRUD"

ROUTER_INCLUDES = '''router.include_router(auth_router.router,  prefix="/api/auth",  tags=["v5-auth"])
router.include_router(admin_router.router, prefix="/api/admin", tags=["v5-admin"])'''


MODELS_BLOCK = '''

# ─── User & Session Models (v5.0) ─────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    display_name  = Column(String, nullable=True)
    is_admin      = Column(Boolean, default=False, index=True)
    is_active     = Column(Boolean, default=True, index=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id            = Column(String, primary_key=True)
    user_id       = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at  = Column(DateTime(timezone=True), server_default=func.now())
    user_agent    = Column(String, nullable=True)
    ip_address    = Column(String, nullable=True)
'''


def msg(s, status='INFO'):
    colors = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m', 'SKIP': '\033[90m'}
    print(f"{colors.get(status, '')}[{status}]\033[0m {s}")


def patch_router():
    if not ROUTER_FILE.exists():
        msg("Không tìm thấy dubeditor/router.py", 'ERR'); return False
    text = ROUTER_FILE.read_text(encoding='utf-8')

    if 'auth_router' in text and 'admin_router' in text:
        msg("router.py: đã có auth/admin router — bỏ qua", 'SKIP')
        return True

    backup = ROUTER_FILE.with_suffix('.py.bak_v5')
    backup.write_text(text, encoding='utf-8')

    lines = text.split('\n')
    # Insert import sau dòng import cuối từ dubeditor.routers
    last_import_idx = -1
    for i, l in enumerate(lines):
        if re.match(r'^\s*from dubeditor\.routers\s+import', l) or \
           re.match(r'^\s*import dubeditor\.routers', l):
            last_import_idx = i
    if last_import_idx < 0:
        msg("router.py: không tìm chỗ insert import", 'ERR'); return False
    lines.insert(last_import_idx + 1, ROUTER_IMPORT)

    # Insert include_router sau dòng include_router cuối
    last_inc = -1
    for i, l in enumerate(lines):
        if 'include_router' in l:
            last_inc = i
    if last_inc < 0:
        lines.append(ROUTER_INCLUDES)
    else:
        lines.insert(last_inc + 1, ROUTER_INCLUDES)

    ROUTER_FILE.write_text('\n'.join(lines), encoding='utf-8')
    msg(f"router.py: patched (backup: {backup.name})", 'OK')
    return True


def patch_models():
    if not MODELS_FILE.exists():
        msg("Không tìm thấy dubeditor/models.py", 'ERR'); return False
    text = MODELS_FILE.read_text(encoding='utf-8')

    changed = False
    backup_done = False

    def backup_once():
        nonlocal backup_done
        if not backup_done:
            backup = MODELS_FILE.with_suffix('.py.bak_v5')
            backup.write_text(MODELS_FILE.read_text(encoding='utf-8'), encoding='utf-8')
            backup_done = True

    # 1) Thêm owner_id vào Project nếu chưa có
    if 'owner_id' not in text:
        # Insert dòng owner_id sau dòng id của Project
        new_text = re.sub(
            r'(class\s+Project\s*\(Base\)\s*:\s*\n[^\n]*__tablename__[^\n]*\n[^\n]*id\s*=\s*Column[^\n]*\n)',
            r'\1    owner_id            = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)  # v5.0\n',
            text,
            count=1,
        )
        if new_text != text:
            backup_once()
            text = new_text
            changed = True
            msg("models.py: thêm Project.owner_id", 'OK')
        else:
            msg("models.py: không tìm class Project để insert owner_id", 'WARN')
    else:
        msg("models.py: Project.owner_id đã có — bỏ qua", 'SKIP')

    # 2) Append class User + UserSession nếu chưa có
    if 'class User(' not in text or 'class UserSession(' not in text:
        backup_once()
        text = text.rstrip() + '\n' + MODELS_BLOCK + '\n'
        changed = True
        msg("models.py: append User + UserSession", 'OK')
    else:
        msg("models.py: User + UserSession đã có — bỏ qua", 'SKIP')

    if changed:
        MODELS_FILE.write_text(text, encoding='utf-8')
        msg("models.py: saved", 'OK')
    return True


def main():
    if not (ROOT / "app.py").exists():
        msg(f"Chạy trong project nano/. Hiện tại: {ROOT}", 'ERR'); sys.exit(1)
    msg(f"Patching User System v5.0 in: {ROOT}")
    print()
    ok = True
    ok &= patch_models()
    ok &= patch_router()
    print()
    if ok:
        msg("Patches OK. Bước tiếp theo:", 'OK')
        msg("  1) python migrate_users.py    (tạo bảng + admin mặc định)", 'INFO')
        msg("  2) python app.py", 'INFO')
    else:
        msg("Có lỗi — xem log trên", 'ERR'); sys.exit(2)


if __name__ == '__main__':
    main()
