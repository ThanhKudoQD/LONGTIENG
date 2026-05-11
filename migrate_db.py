#!/usr/bin/env python3
"""
migrate_db.py — Chuyển dữ liệu từ voicecast.db → dubeditor.db (DB dùng chung)

Chạy một lần duy nhất trước khi khởi động server mới:
    python migrate_db.py

Script an toàn: chỉ insert các record chưa tồn tại (dựa trên id).
"""

import sqlite3, sys
from pathlib import Path

BASE_DIR   = Path(__file__).parent
SRC_DB     = BASE_DIR / "data" / "voicecast.db"
DST_DB     = BASE_DIR / "data" / "dubeditor.db"

def migrate():
    if not SRC_DB.exists():
        print(f"[migrate] voicecast.db không tồn tại ({SRC_DB}) — bỏ qua.")
        return

    src = sqlite3.connect(str(SRC_DB))
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(str(DST_DB))
    dst.execute("PRAGMA foreign_keys=OFF")

    try:
        # ── admins ────────────────────────────────────────────────────────────
        admins = src.execute("SELECT * FROM admins").fetchall()
        existing = {r[0] for r in dst.execute("SELECT id FROM admins")}
        inserted = 0
        for r in admins:
            if r["id"] not in existing:
                dst.execute(
                    "INSERT INTO admins (id, username, password, created_at) VALUES (?,?,?,?)",
                    (r["id"], r["username"], r["password"], r["created_at"])
                )
                inserted += 1
        print(f"[migrate] admins: {inserted}/{len(admins)} inserted")

        # ── actors ────────────────────────────────────────────────────────────
        actors = src.execute("SELECT * FROM actors").fetchall()
        existing = {r[0] for r in dst.execute("SELECT id FROM actors")}
        inserted = 0
        for r in actors:
            if r["id"] not in existing:
                dst.execute(
                    "INSERT INTO actors (id, name, gender, birth_year, avatar, bio, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (r["id"], r["name"], r["gender"], r["birth_year"],
                     r["avatar"], r["bio"], r["created_at"], r["updated_at"])
                )
                inserted += 1
        print(f"[migrate] actors: {inserted}/{len(actors)} inserted")

        # ── roles ─────────────────────────────────────────────────────────────
        roles = src.execute("SELECT * FROM roles").fetchall()
        existing = {r[0] for r in dst.execute("SELECT id FROM roles")}
        inserted = 0
        for r in roles:
            if r["id"] not in existing:
                dst.execute(
                    "INSERT INTO roles (id, actor_id, character_name, show_name, type, genre, "
                    "description, audio, reference_audio_text, lora_path, sort_order, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["id"], r["actor_id"], r["character_name"], r["show_name"],
                     r["type"], r["genre"], r["description"], r["audio"],
                     r["reference_audio_text"], r["lora_path"] if "lora_path" in r.keys() else "",
                     r["sort_order"], r["created_at"])
                )
                inserted += 1
        print(f"[migrate] roles: {inserted}/{len(roles)} inserted")

        # ── role_images ───────────────────────────────────────────────────────
        imgs = src.execute("SELECT * FROM role_images").fetchall()
        existing = {r[0] for r in dst.execute("SELECT id FROM role_images")}
        inserted = 0
        for r in imgs:
            if r["id"] not in existing:
                dst.execute(
                    "INSERT INTO role_images (id, role_id, url, sort_order) VALUES (?,?,?,?)",
                    (r["id"], r["role_id"], r["url"], r["sort_order"])
                )
                inserted += 1
        print(f"[migrate] role_images: {inserted}/{len(imgs)} inserted")

        dst.commit()
        print("[migrate] ✅ Xong! Có thể xóa voicecast.db sau khi kiểm tra.")

    except Exception as e:
        dst.rollback()
        print(f"[migrate] ❌ Lỗi: {e}")
        sys.exit(1)
    finally:
        src.close()
        dst.close()

if __name__ == "__main__":
    migrate()
