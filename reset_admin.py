#!/usr/bin/env python3
"""
reset_admin.py — Tạo admin mới hoặc đổi password admin.

Use case:
  - Tạo admin đầu tiên (nếu chưa có)
  - Quên password admin → reset
  - Tạo thêm admin

Usage:
  python reset_admin.py
  # Hỏi tương tác: username + password
"""
import sqlite3
import sys
import getpass
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DB_PATH = ROOT / "data" / "dubeditor.db"


def msg(s, status='INFO'):
    colors = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m'}
    print(f"{colors.get(status, '')}[{status}]\033[0m {s}")


def main():
    if not DB_PATH.exists():
        msg(f"Không tìm thấy DB: {DB_PATH}", 'ERR'); sys.exit(1)
    try:
        import bcrypt
    except ImportError:
        msg("bcrypt chưa cài: pip install bcrypt", 'ERR'); sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Check bảng users tồn tại
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cur.fetchone():
        msg("Bảng 'users' chưa tồn tại. Chạy migrate_users.py trước.", 'ERR')
        sys.exit(1)

    print()
    print("=== Reset / Tạo Admin ===")
    print()

    # List admin hiện tại
    cur.execute("SELECT id, username, display_name FROM users WHERE is_admin = 1 ORDER BY id")
    admins = cur.fetchall()
    if admins:
        print("Admin hiện có:")
        for a in admins:
            print(f"  - id={a[0]}  username={a[1]}  ({a[2] or ''})")
        print()

    username = input("Username (nhập admin có sẵn để reset password, hoặc tên mới để tạo): ").strip().lower()
    if not username:
        msg("Hủy", 'WARN'); sys.exit(0)

    while True:
        password = getpass.getpass("Password mới: ")
        if len(password) < 4:
            msg("Password tối thiểu 4 ký tự", 'WARN')
            continue
        confirm = getpass.getpass("Nhập lại password: ")
        if password != confirm:
            msg("Password không khớp", 'WARN')
            continue
        break

    pwd_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=10)).decode('utf-8')

    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    if row:
        # Reset existing
        user_id = row[0]
        cur.execute("""UPDATE users SET password_hash = ?, is_admin = 1, is_active = 1
                       WHERE id = ?""", (pwd_hash, user_id))
        # Xóa hết session
        cur.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        msg(f"Đã reset password cho user '{username}' (id={user_id}) + xóa tất cả session", 'OK')
    else:
        # Create new admin
        display_name = input(f"Tên hiển thị [mặc định: {username}]: ").strip() or username
        cur.execute("""INSERT INTO users (username, password_hash, display_name, is_admin, is_active)
                       VALUES (?, ?, ?, 1, 1)""",
                    (username, pwd_hash, display_name))
        msg(f"Đã tạo admin mới: '{username}'", 'OK')

    conn.commit()
    conn.close()
    print()
    msg("Xong. Login bằng credentials vừa set.", 'OK')


if __name__ == '__main__':
    main()
