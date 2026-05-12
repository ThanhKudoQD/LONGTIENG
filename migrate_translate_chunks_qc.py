#!/usr/bin/env python3
"""
migrate_translate_chunks_qc.py
Thêm các cột mới vào bảng translate_chunks:
  - status:       'wait' | 'done' | 'err' (mặc định 'done' cho row cũ vì đã có response)
  - error:        text — lưu thông báo lỗi gần nhất
  - qc_response:  raw JSON response từ Pass 4
  - qc_van_de:    JSON array các vấn đề (snapshot kết quả review)
  - qc_tong_ket:  JSON object — tong_ket từ Pass 4
  - qc_tokens_in / qc_tokens_out / qc_timing_ms / qc_model
  - qc_run_at:    DateTime — khi nào QC chạy

Chạy:  python migrate_translate_chunks_qc.py

An toàn: chỉ ALTER TABLE để thêm cột, không xóa cột cũ.
"""
import sqlite3, sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "data" / "dubeditor.db"

NEW_COLUMNS = [
    ("status",         "TEXT DEFAULT 'done'"),   # default 'done' cho row cũ (đã có response)
    ("error",          "TEXT"),
    ("qc_response",    "TEXT"),
    ("qc_van_de",      "TEXT"),
    ("qc_tong_ket",    "TEXT"),
    ("qc_tokens_in",   "INTEGER DEFAULT 0"),
    ("qc_tokens_out",  "INTEGER DEFAULT 0"),
    ("qc_timing_ms",   "INTEGER DEFAULT 0"),
    ("qc_model",       "TEXT"),
    ("qc_run_at",      "DATETIME"),
]


def column_exists(conn, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


def migrate():
    if not DB_PATH.exists():
        print(f"❌ DB không tồn tại: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        # Verify table exists
        t = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='translate_chunks'").fetchone()
        if not t:
            print("❌ Bảng translate_chunks không tồn tại — chạy server 1 lần để SQLAlchemy tạo bảng, rồi chạy lại migration.")
            sys.exit(1)

        added = 0
        for col, ddl in NEW_COLUMNS:
            if column_exists(conn, "translate_chunks", col):
                print(f"  ⏭  Bỏ qua {col} (đã tồn tại)")
                continue
            conn.execute(f"ALTER TABLE translate_chunks ADD COLUMN {col} {ddl}")
            print(f"  ✓  Thêm cột {col} ({ddl})")
            added += 1

        # Đảm bảo các row cũ có status='done' (vì đã có response)
        conn.execute(
            "UPDATE translate_chunks SET status='done' "
            "WHERE status IS NULL AND response IS NOT NULL AND length(response) > 0"
        )
        conn.execute(
            "UPDATE translate_chunks SET status='wait' "
            "WHERE status IS NULL"
        )

        conn.commit()
        print(f"\n✅ Xong — đã thêm {added}/{len(NEW_COLUMNS)} cột mới.")
    except Exception as e:
        conn.rollback()
        print(f"❌ Lỗi: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
