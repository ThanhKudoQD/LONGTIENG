"""
DubEditor database — SQLAlchemy + SQLite.

Migration đầy đủ chạy ở migrate_to_v2.py. File này chỉ chạy migrations
nhẹ on-startup (idempotent).
"""
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "data" / "dubeditor.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Tạo tables (idempotent) + chạy migration tự động."""
    from dubeditor import models  # noqa
    Base.metadata.create_all(bind=engine)
    _migrate_v3()


def _migrate_v3():
    """Migration on-startup: thêm cột mới + tạo tables mới nếu thiếu.

    Đây là phiên bản nhẹ, tự động chạy khi app start.
    Bao gồm cả migration v2 + v3.
    """
    import sqlite3
    if not DB_PATH.exists():
        return

    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()

        def cols(table):
            return [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]

        def has_table(name):
            return cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (name,)
            ).fetchone() is not None

        def add_col(table, col, type_def):
            if col not in cols(table):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_def}")
                conn.commit()

        # projects v2/v3 fields
        if has_table("projects"):
            add_col("projects", "current_chapter_id", "INTEGER")
            add_col("projects", "source_lang", "TEXT DEFAULT 'vi'")
            add_col("projects", "project_type", "TEXT DEFAULT 'short_drama'")
            add_col("projects", "genre_pack", "TEXT")
            add_col("projects", "translate_status", "TEXT DEFAULT 'idle'")
            add_col("projects", "translate_progress", "REAL DEFAULT 0.0")
            add_col("projects", "translate_error", "TEXT")
            add_col("projects", "use_emotion_voice", "BOOLEAN DEFAULT 0")
            add_col("projects", "tts_voice_mode", "TEXT")
            # v3.9: Editor resume state
            add_col("projects", "last_filter_chapter_ids", "TEXT")
            add_col("projects", "last_subtitle_index", "INTEGER")

        # characters v2 fields (giữ nguyên column cũ để không mất data)
        if has_table("characters"):
            add_col("characters", "shortcut_key", "TEXT")
            add_col("characters", "tts_speed", "REAL DEFAULT 1.0")
            add_col("characters", "name_zh", "TEXT")
            add_col("characters", "aliases_zh", "TEXT")
            add_col("characters", "aliases_vi", "TEXT")
            add_col("characters", "role", "TEXT DEFAULT 'phu'")
            add_col("characters", "gender", "TEXT DEFAULT '?'")
            add_col("characters", "age_group", "TEXT")
            add_col("characters", "social_status", "TEXT")
            add_col("characters", "personality", "TEXT DEFAULT ''")
            add_col("characters", "speaking_style", "TEXT DEFAULT ''")
            add_col("characters", "self_address", "TEXT")
            add_col("characters", "addresses", "TEXT")
            add_col("characters", "relationships_json", "TEXT")
            add_col("characters", "notes", "TEXT DEFAULT ''")

        # subtitles v2 + v3 fields
        if has_table("subtitles"):
            add_col("subtitles", "tts_speed", "REAL")
            add_col("subtitles", "original_text", "TEXT")
            add_col("subtitles", "scene_id", "INTEGER")
            add_col("subtitles", "speaker_zh", "TEXT")
            add_col("subtitles", "speaker_confidence", "TEXT DEFAULT 'low'")
            add_col("subtitles", "speaker_reason", "TEXT DEFAULT ''")
            add_col("subtitles", "emotion", "TEXT")
            add_col("subtitles", "intensity", "INTEGER DEFAULT 5")
            add_col("subtitles", "cps_value", "REAL")
            add_col("subtitles", "needs_review", "BOOLEAN DEFAULT 0")
            add_col("subtitles", "review_reason", "TEXT DEFAULT ''")
            add_col("subtitles", "text_draft", "TEXT")
            add_col("subtitles", "is_hook", "BOOLEAN DEFAULT 0")
            add_col("subtitles", "translation_version", "INTEGER DEFAULT 1")
            add_col("subtitles", "tts_voice_mode", "TEXT")
            add_col("subtitles", "audio_voice_mode", "TEXT")
            # v3 NEW: 2 variants
            add_col("subtitles", "text_v1", "TEXT")
            add_col("subtitles", "text_v2", "TEXT")
            add_col("subtitles", "variant_selected", "INTEGER DEFAULT 1")
            add_col("subtitles", "chunk_id", "INTEGER")
            # v3.1: noise filter (Stage 4)
            add_col("subtitles", "is_noise", "INTEGER DEFAULT 0")
            # v3.2: Stage 0 normalize
            add_col("subtitles", "is_cleaned", "INTEGER DEFAULT 0")
            add_col("subtitles", "original_raw", "TEXT")
            add_col("subtitles", "clean_reason", "TEXT")

        # scenes: thêm chunk_id FK (v3)
        if has_table("scenes"):
            add_col("scenes", "chunk_id", "INTEGER")

        # chapters: v3.3 — sync từ StoryArc (source + arc_index)
        if has_table("chapters"):
            add_col("chapters", "source", "TEXT DEFAULT 'user'")
            add_col("chapters", "arc_index", "INTEGER")

        # roles
        if has_table("roles"):
            add_col("roles", "lora_path", "TEXT DEFAULT ''")
            add_col("roles", "voice_modes", "TEXT")

        # Drop old translate_chunks if exists (deprecated)
        if has_table("translate_chunks"):
            cur.execute("DROP TABLE translate_chunks")
            conn.commit()
            print("[migrate v3] Dropped deprecated table: translate_chunks")

        # v3.9 perf: composite index cho Stage 0 reindex query.
        # "WHERE project_id=? ORDER BY index" — không có index sẽ full scan + filesort.
        # Phim 6000 dòng: reindex ~30s → ~1s sau khi có index + bulk_update_mappings.
        if has_table("subtitles"):
            try:
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS ix_subtitles_project_index "
                    "ON subtitles(project_id, \"index\")"
                )
                conn.commit()
            except Exception as e:
                print(f"[migrate v3.9] index create failed: {e}")

        # ─── Simple Translator v4 (idempotent) ─────────────────────────
        # Thêm 3 cột mới vào subtitles. Bảng simple_* được tạo qua
        # Base.metadata.create_all (chạy ở init_db). Migration nặng (drop bảng cũ,
        # drop cột cũ) ở migrations/migrate_simple_v4.py.
        if has_table("subtitles"):
            add_col("subtitles", "simple_speaker_zh", "TEXT")
            add_col("subtitles", "simple_text_vi", "TEXT")
            add_col("subtitles", "simple_status", "TEXT DEFAULT 'pending'")

        # Note: tables bibles, scenes, story_arcs, polish_issues, chunks (NEW)
        # được tạo tự động bởi Base.metadata.create_all (SQLAlchemy).

    except Exception as e:
        print(f"[migrate v3] Warning: {e}")
    finally:
        conn.close()


# Backwards compat
_migrate_v2 = _migrate_v3