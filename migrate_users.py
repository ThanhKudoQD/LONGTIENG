#!/usr/bin/env python3
"""
migrate_users.py — Migration cho User System v5.0

Thay đổi DB:
  1. Tạo bảng `users`
  2. Tạo bảng `user_sessions`
  3. Thêm cột `projects.owner_id`
  4. Tạo admin user mặc định (nếu chưa có)
  5. Gán mọi project hiện có chưa có owner → admin

Idempotent: chạy nhiều lần OK.

Usage:
  cd /home/dmin/nano
  python migrate_users.py
  # Tạo admin mặc định với password 'admin123' (đổi ngay sau lần login đầu!)
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DB_PATH = ROOT / "data" / "dubeditor.db"

DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_PASSWORD = 'admin123'


def msg(s, status='INFO'):
    colors = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m', 'SKIP': '\033[90m'}
    print(f"{colors.get(status, '')}[{status}]\033[0m {s}")


def column_exists(cur, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in cur.fetchall())


def table_exists(cur, table: str) -> bool:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def main():
    if not DB_PATH.exists():
        msg(f"Không tìm thấy DB: {DB_PATH}", 'ERR')
        msg("Khởi động app.py 1 lần để tạo DB trước", 'INFO')
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # ── 1) Bảng users ──
    if table_exists(cur, 'users'):
        msg("Bảng 'users' đã tồn tại — bỏ qua", 'SKIP')
    else:
        cur.execute("""
            CREATE TABLE users (
                id            INTEGER PRIMARY KEY,
                username      VARCHAR NOT NULL UNIQUE,
                password_hash VARCHAR NOT NULL,
                display_name  VARCHAR,
                is_admin      BOOLEAN DEFAULT 0,
                is_active     BOOLEAN DEFAULT 1,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login_at DATETIME
            )
        """)
        cur.execute("CREATE INDEX ix_users_username ON users(username)")
        cur.execute("CREATE INDEX ix_users_is_admin ON users(is_admin)")
        cur.execute("CREATE INDEX ix_users_is_active ON users(is_active)")
        msg("Đã tạo bảng 'users'", 'OK')

    # ── 2) Bảng user_sessions ──
    if table_exists(cur, 'user_sessions'):
        msg("Bảng 'user_sessions' đã tồn tại — bỏ qua", 'SKIP')
    else:
        cur.execute("""
            CREATE TABLE user_sessions (
                id            VARCHAR PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_agent    VARCHAR,
                ip_address    VARCHAR,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        cur.execute("CREATE INDEX ix_user_sessions_user_id ON user_sessions(user_id)")
        msg("Đã tạo bảng 'user_sessions'", 'OK')

    # ── 3) Cột projects.owner_id ──
    if column_exists(cur, 'projects', 'owner_id'):
        msg("Cột 'projects.owner_id' đã tồn tại — bỏ qua", 'SKIP')
    else:
        cur.execute("ALTER TABLE projects ADD COLUMN owner_id INTEGER")
        cur.execute("CREATE INDEX ix_projects_owner_id ON projects(owner_id)")
        msg("Đã thêm cột 'projects.owner_id'", 'OK')

    # ── 4) Tạo admin mặc định ──
    cur.execute("SELECT id, username FROM users WHERE is_admin = 1 LIMIT 1")
    admin_row = cur.fetchone()
    if admin_row:
        msg(f"Admin đã tồn tại: id={admin_row[0]} username={admin_row[1]}", 'SKIP')
        admin_id = admin_row[0]
    else:
        # Cần bcrypt
        try:
            import bcrypt
        except ImportError:
            msg("bcrypt chưa cài. Chạy: pip install bcrypt", 'ERR')
            conn.close()
            sys.exit(2)

        pwd_hash = bcrypt.hashpw(DEFAULT_ADMIN_PASSWORD.encode('utf-8'), bcrypt.gensalt(rounds=10)).decode('utf-8')
        cur.execute("""
            INSERT INTO users (username, password_hash, display_name, is_admin, is_active)
            VALUES (?, ?, ?, 1, 1)
        """, (DEFAULT_ADMIN_USERNAME, pwd_hash, 'Administrator'))
        admin_id = cur.lastrowid
        msg(f"Đã tạo admin mặc định: '{DEFAULT_ADMIN_USERNAME}' / '{DEFAULT_ADMIN_PASSWORD}'", 'OK')
        msg("⚠️  HÃY ĐỔI PASSWORD NGAY SAU LẦN LOGIN ĐẦU TIÊN!", 'WARN')

    # ── 5) Gán project chưa có owner → admin ──
    cur.execute("SELECT COUNT(*) FROM projects WHERE owner_id IS NULL")
    n_orphan = cur.fetchone()[0]
    if n_orphan > 0:
        cur.execute("UPDATE projects SET owner_id = ? WHERE owner_id IS NULL", (admin_id,))
        msg(f"Đã gán {n_orphan} project chưa có owner → admin (id={admin_id})", 'OK')
    else:
        msg("Tất cả project đã có owner — bỏ qua", 'SKIP')

    conn.commit()
    conn.close()

    print()
    msg("Migration xong!", 'OK')
    msg("Restart server: python app.py", 'INFO')


if __name__ == '__main__':
    main()
