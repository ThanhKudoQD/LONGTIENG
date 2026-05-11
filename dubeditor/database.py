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
    from dubeditor import models  # noqa
    Base.metadata.create_all(bind=engine)
    _migrate()

def _migrate():
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()

        # characters
        cols = [r[1] for r in cur.execute("PRAGMA table_info(characters)").fetchall()]
        if "shortcut_key" not in cols:
            cur.execute("ALTER TABLE characters ADD COLUMN shortcut_key TEXT")
            conn.commit()
        if "tts_speed" not in cols:
            cur.execute("ALTER TABLE characters ADD COLUMN tts_speed REAL DEFAULT 1.0")
            conn.commit()

        # projects
        cols = [r[1] for r in cur.execute("PRAGMA table_info(projects)").fetchall()]
        if "current_chapter_id" not in cols:
            cur.execute("ALTER TABLE projects ADD COLUMN current_chapter_id INTEGER")
            conn.commit()
        if "bible_json" not in cols:
            cur.execute("ALTER TABLE projects ADD COLUMN bible_json TEXT")
            conn.commit()
            print("[migrate] Added projects.bible_json")
        if "source_lang" not in cols:
            cur.execute("ALTER TABLE projects ADD COLUMN source_lang TEXT DEFAULT 'vi'")
            conn.commit()
            print("[migrate] Added projects.source_lang")

        # subtitles
        cols = [r[1] for r in cur.execute("PRAGMA table_info(subtitles)").fetchall()]
        if "tts_speed" not in cols:
            cur.execute("ALTER TABLE subtitles ADD COLUMN tts_speed REAL DEFAULT NULL")
            conn.commit()
        if "original_text" not in cols:
            cur.execute("ALTER TABLE subtitles ADD COLUMN original_text TEXT")
            conn.commit()
            print("[migrate] Added subtitles.original_text")

        # roles
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "roles" in tables:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(roles)").fetchall()]
            if "lora_path" not in cols:
                cur.execute("ALTER TABLE roles ADD COLUMN lora_path TEXT DEFAULT ''")
                conn.commit()

        # translate_chunks table (tạo nếu chưa có)
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "translate_chunks" not in tables:
            cur.execute("""CREATE TABLE translate_chunks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                start_line  INTEGER NOT NULL DEFAULT 0,
                end_line    INTEGER NOT NULL DEFAULT 0,
                prompt      TEXT,
                response    TEXT,
                tokens_in   INTEGER DEFAULT 0,
                tokens_out  INTEGER DEFAULT 0,
                timing_ms   INTEGER DEFAULT 0,
                model       TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()
            print("[migrate] Created translate_chunks table")

    except Exception as e:
        print(f"[migrate] Error: {e}")
    finally:
        conn.close()