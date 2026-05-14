#!/usr/bin/env python3
"""
Migration script v2 → v3 cho DubEditor DB.

Chạy:
    python migrate_to_v3.py [--db /path/to/dubeditor.db] [--dry-run]

Việc làm:
1. Thêm cột v3 vào bảng subtitles (text_v1, text_v2, variant_selected, chunk_id)
2. Thêm cột chunk_id vào bảng scenes
3. Tạo bảng chunks (nếu chưa có)
4. Backfill: cho mỗi Subtitle có text non-empty và không phải original_text
   → copy text vào text_v1, set variant_selected=1
5. Sau Stage 2 v3 đầu tiên: chunks sẽ được tự tạo và cập nhật scenes.chunk_id

Có chế độ --dry-run để xem thay đổi mà không commit.
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
from pathlib import Path


# Schema migration spec
SCHEMA_CHANGES: list[dict] = [
    # subtitles
    {"table": "subtitles", "col": "text_v1", "type": "TEXT", "nullable": True},
    {"table": "subtitles", "col": "text_v2", "type": "TEXT", "nullable": True},
    {"table": "subtitles", "col": "variant_selected", "type": "INTEGER", "default": 1},
    {"table": "subtitles", "col": "chunk_id", "type": "INTEGER", "nullable": True},
    # scenes
    {"table": "scenes", "col": "chunk_id", "type": "INTEGER", "nullable": True},
]


def get_columns(cur, table: str) -> list[str]:
    return [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]


def has_table(cur, name: str) -> bool:
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,)
    ).fetchone() is not None


def ensure_column(cur, conn, change: dict, dry_run: bool) -> bool:
    """Returns True if added."""
    table = change["table"]
    col = change["col"]
    if not has_table(cur, table):
        print(f"  ⏭  Bảng {table} không tồn tại, bỏ qua")
        return False
    cols = get_columns(cur, table)
    if col in cols:
        print(f"  ✓  {table}.{col} đã có")
        return False

    type_def = change["type"]
    if "default" in change:
        type_def += f" DEFAULT {change['default']}"
    sql = f"ALTER TABLE {table} ADD COLUMN {col} {type_def}"
    print(f"  +  {sql}")
    if not dry_run:
        cur.execute(sql)
        conn.commit()
    return True


def ensure_chunks_table(cur, conn, dry_run: bool) -> bool:
    """Tạo bảng chunks nếu chưa có."""
    if has_table(cur, "chunks"):
        print("  ✓  Bảng chunks đã có")
        return False
    sql = """
    CREATE TABLE chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        arc_index INTEGER NOT NULL,
        chunk_index INTEGER NOT NULL,
        title TEXT DEFAULT '',
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )
    """
    print("  +  CREATE TABLE chunks")
    if not dry_run:
        cur.execute(sql)
        cur.execute("CREATE INDEX idx_chunks_project ON chunks(project_id)")
        conn.commit()
    return True


def backfill_text_v1(cur, conn, dry_run: bool) -> int:
    """Backfill text_v1 cho subtitles có text non-empty.

    Logic:
    - Nếu text_v1 IS NULL VÀ text non-empty VÀ text khác original_text
      → set text_v1 = text, variant_selected = 1
    """
    rows = cur.execute("""
        SELECT id, text, original_text
        FROM subtitles
        WHERE text_v1 IS NULL
          AND text IS NOT NULL
          AND TRIM(text) != ''
    """).fetchall()

    count = 0
    for row_id, text, original in rows:
        if text == original:
            continue  # text = original = chưa dịch, skip
        if not dry_run:
            cur.execute(
                "UPDATE subtitles SET text_v1 = ?, variant_selected = 1 WHERE id = ?",
                (text, row_id),
            )
        count += 1

    if not dry_run and count > 0:
        conn.commit()
    print(f"  📋 Backfill text_v1: {count} dòng")
    return count


def drop_deprecated_translate_chunks(cur, conn, dry_run: bool):
    """Xóa bảng cũ translate_chunks nếu có (từ v1)."""
    if has_table(cur, "translate_chunks"):
        print("  -  DROP TABLE translate_chunks (deprecated v1)")
        if not dry_run:
            cur.execute("DROP TABLE translate_chunks")
            conn.commit()


def report_status(cur):
    """In thống kê DB."""
    print()
    print("📊 Thống kê hiện tại:")

    if has_table(cur, "projects"):
        n = cur.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        print(f"  · {n} projects")

    if has_table(cur, "subtitles"):
        total = cur.execute("SELECT COUNT(*) FROM subtitles").fetchone()[0]
        with_v1 = cur.execute(
            "SELECT COUNT(*) FROM subtitles WHERE text_v1 IS NOT NULL AND text_v1 != ''"
        ).fetchone()[0]
        with_v2 = cur.execute(
            "SELECT COUNT(*) FROM subtitles WHERE text_v2 IS NOT NULL AND text_v2 != ''"
        ).fetchone()[0]
        print(f"  · {total} subtitles ({with_v1} có v1, {with_v2} có v2)")

    if has_table(cur, "bibles"):
        n = cur.execute("SELECT COUNT(*) FROM bibles").fetchone()[0]
        n_active = cur.execute(
            "SELECT COUNT(*) FROM bibles WHERE is_active = 1"
        ).fetchone()[0]
        print(f"  · {n} bibles ({n_active} active)")

    if has_table(cur, "chunks"):
        n = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        print(f"  · {n} chunks")

    if has_table(cur, "scenes"):
        n = cur.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
        with_chunk = cur.execute(
            "SELECT COUNT(*) FROM scenes WHERE chunk_id IS NOT NULL"
        ).fetchone()[0]
        print(f"  · {n} scenes ({with_chunk} đã có chunk_id)")


def main():
    parser = argparse.ArgumentParser(description="Migrate DubEditor DB to v3")
    parser.add_argument("--db", type=Path, default=Path("data/dubeditor.db"),
                        help="Đường dẫn SQLite DB")
    parser.add_argument("--dry-run", action="store_true",
                        help="Chỉ in changes, KHÔNG commit")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"❌ DB không tồn tại: {args.db}")
        sys.exit(1)

    if args.dry_run:
        print("🧪 DRY-RUN mode — không commit thay đổi")
    print(f"📂 Migrating: {args.db}")
    print()

    conn = sqlite3.connect(str(args.db))
    cur = conn.cursor()

    try:
        print("━━━ 1. Schema changes ━━━")
        for change in SCHEMA_CHANGES:
            ensure_column(cur, conn, change, args.dry_run)
        ensure_chunks_table(cur, conn, args.dry_run)

        print()
        print("━━━ 2. Cleanup deprecated ━━━")
        drop_deprecated_translate_chunks(cur, conn, args.dry_run)

        print()
        print("━━━ 3. Backfill data ━━━")
        backfill_text_v1(cur, conn, args.dry_run)

        report_status(cur)

        print()
        if args.dry_run:
            print("🧪 Dry-run hoàn tất. KHÔNG có thay đổi nào được commit.")
            print("   Chạy lại không có --dry-run để áp dụng.")
        else:
            print("✅ Migration hoàn tất.")
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
