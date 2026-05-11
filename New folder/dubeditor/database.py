from sqlalchemy import create_engine
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
    # Migration: thêm column shortcut_key nếu chưa có
    _migrate()


def _migrate():
    """Migration ad-hoc cho SQLite — chỉ thêm column mới, không drop."""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        # characters
        cols = [r[1] for r in cur.execute("PRAGMA table_info(characters)").fetchall()]
        if 'shortcut_key' not in cols:
            cur.execute("ALTER TABLE characters ADD COLUMN shortcut_key TEXT")
            conn.commit()
            print("[migrate] Added characters.shortcut_key")
        if 'tts_speed' not in cols:
            cur.execute("ALTER TABLE characters ADD COLUMN tts_speed REAL DEFAULT 1.0")
            conn.commit()
            print("[migrate] Added characters.tts_speed")
        # projects
        cols = [r[1] for r in cur.execute("PRAGMA table_info(projects)").fetchall()]
        if 'current_chapter_id' not in cols:
            cur.execute("ALTER TABLE projects ADD COLUMN current_chapter_id INTEGER")
            conn.commit()
            print("[migrate] Added projects.current_chapter_id")
        # subtitles
        cols = [r[1] for r in cur.execute("PRAGMA table_info(subtitles)").fetchall()]
        if 'tts_speed' not in cols:
            cur.execute("ALTER TABLE subtitles ADD COLUMN tts_speed REAL DEFAULT NULL")
            conn.commit()
            print("[migrate] Added subtitles.tts_speed")
    except Exception as e:
        print(f"[migrate] Error: {e}")
    finally:
        conn.close()
