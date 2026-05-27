"""
Migration v4.2: Thêm field Project.mega_target_lines

Chạy script này 1 lần sau khi update models.py để thêm column mới
vào DB hiện có (không xóa data).

Usage:
    cd /home/dmin/nano
    python3 dubeditor/migrations/add_mega_target_lines.py
"""
import sys
from pathlib import Path

# Thêm root vào sys.path
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text
from dubeditor.database import engine


def has_column(conn, table: str, column: str) -> bool:
    """Check column exists in SQLite."""
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def main():
    with engine.begin() as conn:
        if has_column(conn, "projects", "mega_target_lines"):
            print("✓ Column projects.mega_target_lines đã tồn tại, skip migration.")
            return

        print("→ Adding column projects.mega_target_lines (INTEGER, nullable)...")
        conn.execute(text(
            "ALTER TABLE projects ADD COLUMN mega_target_lines INTEGER"
        ))
        print("✓ Done. Default sẽ là 500 (qua application logic).")


if __name__ == "__main__":
    main()
