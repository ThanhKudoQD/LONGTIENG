"""
Migration script — chuyển từ pipeline v3 sang pipeline Simple v4.

Chạy 1 lần sau khi đã cập nhật code:
    cd /path/to/nano_project/nano
    python -m migrations.migrate_simple_v4

⚠️ CẢNH BÁO TRƯỚC KHI CHẠY ⚠️
1. BACKUP DB TRƯỚC: cp data/dubeditor.db data/dubeditor.db.bak.$(date +%s)
2. Sẽ XÓA dữ liệu trong các bảng cũ:
     - bibles
     - story_arcs
     - chunks
     - scenes
     - polish_issues
3. Sẽ XÓA các cột cũ trên subtitles (cần recreate table — SQLite limitation):
     - speaker_zh, speaker_confidence, speaker_reason
     - text_v1, text_v2, variant_selected
     - text_draft, is_cleaned, original_raw, clean_reason
     - chunk_id, scene_id
   (Giữ lại: text, original_text, emotion, intensity, cps_value, audio_*, tts_*)

Sau khi migrate, các cột mới trên subtitles:
     - simple_speaker_zh   (TEXT)
     - simple_text_vi      (TEXT)
     - simple_status       (TEXT DEFAULT 'pending')

Và 5 bảng mới sẽ được tạo:
     - simple_bible_parts
     - simple_bible_merges
     - simple_batches
     - simple_review_groups
     - simple_issues
"""
import sys
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

# Tìm DB path từ dubeditor.database
sys.path.insert(0, str(Path(__file__).parent.parent))
from dubeditor.database import DB_PATH, engine, Base


# ─── Danh sách bảng cũ cần drop ──────────────────────────────────────────────

TABLES_TO_DROP = [
    "bibles",
    "story_arcs",
    "chunks",
    "scenes",
    "polish_issues",
]

# Các cột trên subtitles cần xóa
SUBTITLES_COLS_TO_DROP = {
    "speaker_zh", "speaker_confidence", "speaker_reason",
    "text_v1", "text_v2", "variant_selected",
    "text_draft", "is_cleaned", "original_raw", "clean_reason",
    "chunk_id", "scene_id",
    # Lưu ý: KHÔNG xóa needs_review, review_reason, is_hook, translation_version
    # vì có thể dùng trong logic khác. Confirm với user nếu cần.
}


def main():
    print(f"\n{'='*60}")
    print(f" Migration: Pipeline v3 → Simple v4")
    print(f" DB: {DB_PATH}")
    print(f"{'='*60}\n")

    if not DB_PATH.exists():
        print("DB chưa tồn tại — sẽ tạo mới với schema Simple v4.")
        # Trigger create_all via models import
        from dubeditor import models  # noqa
        from dubeditor.simple import models as simple_models  # noqa
        Base.metadata.create_all(bind=engine)
        print("✓ Tạo DB mới xong.")
        return

    # ─── Backup ─────────────────────────────────────────────────────────────
    backup_path = DB_PATH.with_suffix(f".db.bak.{int(datetime.now().timestamp())}")
    print(f"📦 Backup DB → {backup_path}")
    shutil.copy(DB_PATH, backup_path)
    print(f"✓ Backup OK\n")

    # ─── Connect ────────────────────────────────────────────────────────────
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    try:
        # Disable FK constraints để drop tables an toàn
        cur.execute("PRAGMA foreign_keys=OFF")

        # ─── Step 1: Drop bảng cũ ─────────────────────────────────────────
        print("📤 Step 1: Drop bảng pipeline cũ...")
        for table in TABLES_TO_DROP:
            exists = cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone() is not None
            if exists:
                cur.execute(f"DROP TABLE IF EXISTS {table}")
                print(f"  ✓ Dropped {table}")
            else:
                print(f"  · {table} không tồn tại, bỏ qua")
        conn.commit()

        # ─── Step 2: Recreate subtitles để xóa cột cũ ──────────────────────
        print("\n📤 Step 2: Recreate subtitles (xóa cột pipeline cũ)...")
        recreate_subtitles_drop_cols(cur, conn)
        conn.commit()

        # ─── Step 3: Thêm cột mới simple_* ────────────────────────────────
        print("\n📥 Step 3: Thêm cột simple_* vào subtitles...")
        existing_cols = [r[1] for r in cur.execute("PRAGMA table_info(subtitles)").fetchall()]
        if 'simple_speaker_zh' not in existing_cols:
            cur.execute("ALTER TABLE subtitles ADD COLUMN simple_speaker_zh TEXT")
            print(f"  ✓ Added simple_speaker_zh")
        if 'simple_text_vi' not in existing_cols:
            cur.execute("ALTER TABLE subtitles ADD COLUMN simple_text_vi TEXT")
            print(f"  ✓ Added simple_text_vi")
        if 'simple_status' not in existing_cols:
            cur.execute("ALTER TABLE subtitles ADD COLUMN simple_status TEXT DEFAULT 'pending'")
            print(f"  ✓ Added simple_status")
        conn.commit()

        # ─── Step 4: Tạo bảng mới qua SQLAlchemy ──────────────────────────
        print("\n📥 Step 4: Tạo bảng mới...")
        # Đóng sqlite3 conn trước khi SQLAlchemy connect
        cur.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        conn.close()

        # Import models để SQLAlchemy biết
        from dubeditor import models  # noqa
        from dubeditor.simple import models as simple_models  # noqa
        Base.metadata.create_all(bind=engine)
        print("  ✓ Created simple_bible_parts")
        print("  ✓ Created simple_bible_merges")
        print("  ✓ Created simple_batches")
        print("  ✓ Created simple_review_groups")
        print("  ✓ Created simple_issues")

        print(f"\n{'='*60}")
        print(f" ✅ Migration thành công!")
        print(f"  Backup: {backup_path}")
        print(f"{'='*60}\n")
        print("Bước tiếp theo:")
        print("  1. Restart server")
        print("  2. Mở project, vào tab 'Dịch' để xem UI mới")
        print()

    except Exception as e:
        print(f"\n❌ Migration FAILED: {e}")
        print(f"   Khôi phục từ backup: cp {backup_path} {DB_PATH}")
        try:
            conn.close()
        except Exception:
            pass
        raise


def recreate_subtitles_drop_cols(cur, conn):
    """SQLite không support DROP COLUMN trực tiếp → recreate table.

    Steps:
      1. Lấy schema mới (chỉ các cột giữ lại)
      2. Tạo bảng tạm subtitles_new
      3. INSERT data từ subtitles cũ
      4. DROP subtitles cũ
      5. RENAME subtitles_new → subtitles
      6. Recreate indexes
    """
    # SQLite reserved keywords — phải quote bằng "..." nếu dùng làm column name
    SQLITE_RESERVED = {
        'index', 'order', 'group', 'select', 'from', 'where', 'table',
        'as', 'by', 'in', 'is', 'not', 'null', 'and', 'or', 'limit',
        'offset', 'union', 'join', 'on', 'using', 'with', 'when', 'case',
        'then', 'else', 'end', 'default', 'unique', 'primary', 'foreign',
        'references', 'check', 'constraint', 'collate', 'desc', 'asc',
    }

    def qcol(name: str) -> str:
        """Quote column name nếu là reserved keyword."""
        return f'"{name}"' if name.lower() in SQLITE_RESERVED else name

    # Lấy thông tin cột hiện tại
    cols_info = cur.execute("PRAGMA table_info(subtitles)").fetchall()
    # cols_info: list of (cid, name, type, notnull, dflt, pk)
    existing = {row[1]: row for row in cols_info}

    # Cột giữ lại = không phải pipeline cũ
    keep_cols = [c for c in existing.keys() if c not in SUBTITLES_COLS_TO_DROP]

    # Build CREATE TABLE statement (giữ kiểu y nguyên)
    col_defs = []
    for name in keep_cols:
        cid, nm, ty, notnull, dflt, pk = existing[name]
        # Quote tên cột nếu reserved
        parts = [qcol(name), ty or "TEXT"]
        if pk:
            parts.append("PRIMARY KEY")
        if notnull and not pk:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_defs.append(" ".join(parts))

    create_sql = "CREATE TABLE subtitles_new (\n  " + ",\n  ".join(col_defs) + "\n)"
    cur.execute("DROP TABLE IF EXISTS subtitles_new")
    cur.execute(create_sql)

    # Copy data — cũng phải quote keyword columns trong INSERT/SELECT
    quoted_cols = ", ".join(qcol(c) for c in keep_cols)
    cur.execute(
        f"INSERT INTO subtitles_new ({quoted_cols}) "
        f"SELECT {quoted_cols} FROM subtitles"
    )

    # Replace
    cur.execute("DROP TABLE subtitles")
    cur.execute("ALTER TABLE subtitles_new RENAME TO subtitles")

    # Recreate index (composite index cho query "WHERE project_id=? ORDER BY index")
    cur.execute(
        'CREATE INDEX IF NOT EXISTS ix_subtitles_project_index '
        'ON subtitles (project_id, "index")'
    )

    dropped = sorted(c for c in existing.keys() if c in SUBTITLES_COLS_TO_DROP)
    print(f"  ✓ Recreated subtitles ({len(keep_cols)} cột giữ, {len(dropped)} cột xóa)")
    if dropped:
        print(f"    Xóa: {', '.join(dropped)}")


if __name__ == "__main__":
    main()
