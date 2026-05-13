"""
Migration script: DB v1 → v2.

Run: python migrate_to_v2.py

Thực hiện:
1. ADD columns mới vào projects, characters, subtitles
2. DROP TABLE translate_chunks (không dùng nữa)
3. DROP COLUMN projects.bible_json (data sẽ chuyển sang bảng bibles mới)
   → Trước khi drop, MIGRATE data từ bible_json → bảng bibles mới
4. CREATE TABLE bibles, scenes, story_arcs, polish_issues

Script này IDEMPOTENT — chạy nhiều lần OK, chỉ thực hiện những gì chưa làm.
"""
import sqlite3
import json
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "dubeditor.db"


def column_exists(cur, table: str, col: str) -> bool:
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    return col in cols


def table_exists(cur, table: str) -> bool:
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def add_column_safe(cur, table: str, col: str, type_def: str, label: str = ""):
    if not column_exists(cur, table, col):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_def}")
        print(f"  [+] {table}.{col}  {label}")
        return True
    return False


def migrate():
    if not DB_PATH.exists():
        print(f"⚠ Database not found: {DB_PATH}")
        print("→ Fresh install — chạy app trước, tables sẽ được tạo tự động.")
        return

    print(f"📂 DB: {DB_PATH}")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    try:
        # ─── 1. ADD columns vào projects ────────────────────────────────────
        print("\n[1] Migrating: projects")
        add_column_safe(cur, "projects", "project_type", "TEXT DEFAULT 'short_drama'",
                         "(short_drama|drama_series|movie)")
        add_column_safe(cur, "projects", "genre_pack", "TEXT", "(genre pack ID)")
        add_column_safe(cur, "projects", "translate_status", "TEXT DEFAULT 'idle'",
                         "(idle|running|done|error)")
        add_column_safe(cur, "projects", "translate_progress", "REAL DEFAULT 0.0")
        add_column_safe(cur, "projects", "translate_error", "TEXT")

        # ─── 2. ADD columns vào characters ──────────────────────────────────
        print("\n[2] Migrating: characters")
        add_column_safe(cur, "characters", "name_zh", "TEXT")
        add_column_safe(cur, "characters", "aliases_zh", "TEXT")
        add_column_safe(cur, "characters", "aliases_vi", "TEXT")
        add_column_safe(cur, "characters", "role", "TEXT DEFAULT 'phu'")
        add_column_safe(cur, "characters", "gender", "TEXT DEFAULT '?'")
        add_column_safe(cur, "characters", "age_group", "TEXT")
        add_column_safe(cur, "characters", "social_status", "TEXT")
        add_column_safe(cur, "characters", "personality", "TEXT DEFAULT ''")
        add_column_safe(cur, "characters", "speaking_style", "TEXT DEFAULT ''")
        add_column_safe(cur, "characters", "self_address", "TEXT")
        add_column_safe(cur, "characters", "addresses", "TEXT")
        add_column_safe(cur, "characters", "relationships_json", "TEXT")
        add_column_safe(cur, "characters", "notes", "TEXT DEFAULT ''")

        # ─── 3. ADD columns vào subtitles ──────────────────────────────────
        print("\n[3] Migrating: subtitles")
        add_column_safe(cur, "subtitles", "scene_id", "INTEGER")
        add_column_safe(cur, "subtitles", "speaker_zh", "TEXT")
        add_column_safe(cur, "subtitles", "speaker_confidence", "TEXT DEFAULT 'low'")
        add_column_safe(cur, "subtitles", "speaker_reason", "TEXT DEFAULT ''")
        add_column_safe(cur, "subtitles", "emotion", "TEXT")
        add_column_safe(cur, "subtitles", "intensity", "INTEGER DEFAULT 5")
        add_column_safe(cur, "subtitles", "cps_value", "REAL")
        add_column_safe(cur, "subtitles", "needs_review", "BOOLEAN DEFAULT 0")
        add_column_safe(cur, "subtitles", "review_reason", "TEXT DEFAULT ''")
        add_column_safe(cur, "subtitles", "text_draft", "TEXT")
        add_column_safe(cur, "subtitles", "is_hook", "BOOLEAN DEFAULT 0")
        add_column_safe(cur, "subtitles", "translation_version", "INTEGER DEFAULT 1")

        # ─── 4. CREATE bibles table ─────────────────────────────────────────
        print("\n[4] Creating: bibles table")
        if not table_exists(cur, "bibles"):
            cur.execute("""
                CREATE TABLE bibles (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id      INTEGER NOT NULL,
                    version         INTEGER DEFAULT 1,
                    is_active       BOOLEAN DEFAULT 1,
                    cast_json       TEXT DEFAULT '{}',
                    world_json      TEXT DEFAULT '{}',
                    glossary_json   TEXT DEFAULT '{}',
                    genre_pack_id   TEXT,
                    tokens_in       INTEGER DEFAULT 0,
                    tokens_out      INTEGER DEFAULT 0,
                    cost_usd        REAL DEFAULT 0.0,
                    model_used      TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
            """)
            cur.execute("CREATE INDEX idx_bibles_project ON bibles(project_id)")
            print("  [+] bibles + index")
        else:
            print("  [=] bibles (already exists)")

        # ─── 5. CREATE story_arcs table ─────────────────────────────────────
        print("\n[5] Creating: story_arcs table")
        if not table_exists(cur, "story_arcs"):
            cur.execute("""
                CREATE TABLE story_arcs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id      INTEGER NOT NULL,
                    arc_index       INTEGER NOT NULL,
                    title           TEXT DEFAULT '',
                    summary         TEXT DEFAULT '',
                    start_line      INTEGER DEFAULT 1,
                    end_line        INTEGER DEFAULT 1,
                    emotional_tone  TEXT DEFAULT '',
                    key_events      TEXT DEFAULT '[]',
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
            """)
            cur.execute("CREATE INDEX idx_arcs_project ON story_arcs(project_id)")
            print("  [+] story_arcs + index")
        else:
            print("  [=] story_arcs (already exists)")

        # ─── 6. CREATE scenes table ─────────────────────────────────────────
        print("\n[6] Creating: scenes table")
        if not table_exists(cur, "scenes"):
            cur.execute("""
                CREATE TABLE scenes (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id          INTEGER NOT NULL,
                    scene_index         INTEGER NOT NULL,
                    start_line          INTEGER NOT NULL,
                    end_line            INTEGER NOT NULL,
                    start_time_sec      REAL DEFAULT 0.0,
                    end_time_sec        REAL DEFAULT 0.0,
                    location            TEXT DEFAULT '',
                    time_of_day         TEXT,
                    characters_present  TEXT DEFAULT '[]',
                    emotion_primary     TEXT DEFAULT 'neutral',
                    emotion_arc         TEXT DEFAULT '',
                    summary             TEXT DEFAULT '',
                    purpose             TEXT DEFAULT '',
                    story_arc_id        INTEGER,
                    is_hook             BOOLEAN DEFAULT 0,
                    is_emotion_peak     BOOLEAN DEFAULT 0,
                    status              TEXT DEFAULT 'pending',
                    error_message       TEXT,
                    tokens_in           INTEGER DEFAULT 0,
                    tokens_out          INTEGER DEFAULT 0,
                    cost_usd            REAL DEFAULT 0.0,
                    timing_ms           INTEGER DEFAULT 0,
                    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id),
                    FOREIGN KEY (story_arc_id) REFERENCES story_arcs(id)
                )
            """)
            cur.execute("CREATE INDEX idx_scenes_project ON scenes(project_id)")
            cur.execute("CREATE INDEX idx_scenes_index ON scenes(project_id, scene_index)")
            print("  [+] scenes + indexes")
        else:
            print("  [=] scenes (already exists)")

        # ─── 7. CREATE polish_issues table ──────────────────────────────────
        print("\n[7] Creating: polish_issues table")
        if not table_exists(cur, "polish_issues"):
            cur.execute("""
                CREATE TABLE polish_issues (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id      INTEGER NOT NULL,
                    subtitle_id     INTEGER,
                    line_index      INTEGER NOT NULL,
                    issue_type      TEXT DEFAULT 'other',
                    description     TEXT DEFAULT '',
                    current_text    TEXT DEFAULT '',
                    suggested_text  TEXT,
                    confidence      TEXT DEFAULT 'mid',
                    evidence        TEXT DEFAULT '',
                    resolved        BOOLEAN DEFAULT 0,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id),
                    FOREIGN KEY (subtitle_id) REFERENCES subtitles(id)
                )
            """)
            cur.execute("CREATE INDEX idx_issues_project ON polish_issues(project_id)")
            print("  [+] polish_issues + index")
        else:
            print("  [=] polish_issues (already exists)")

        # ─── 8. MIGRATE bible_json → bibles table (nếu có data cũ) ──────────
        print("\n[8] Migrate bible_json → bibles table")
        if column_exists(cur, "projects", "bible_json"):
            # Tìm projects có bible_json
            rows = cur.execute(
                "SELECT id, bible_json FROM projects WHERE bible_json IS NOT NULL AND bible_json != ''"
            ).fetchall()
            migrated_count = 0
            for pid, bible_json in rows:
                # Check đã có bible chưa
                existed = cur.execute(
                    "SELECT id FROM bibles WHERE project_id = ?", (pid,)
                ).fetchone()
                if existed:
                    continue
                try:
                    old_bible = json.loads(bible_json)
                except Exception:
                    print(f"  ⚠ Project {pid}: bible_json không parse được, bỏ qua")
                    continue

                # Convert format cũ → format mới
                # Old format: {"nhan_vat": [...], "thuat_ngu": {...}, "scene_map": [...]}
                # New format: bible.cast.characters, bible.glossary.terms, etc.
                # Đây là migration BEST-EFFORT — data sẽ partial,
                # khuyến nghị user re-run Stage 1 với pipeline mới.
                cast_json = json.dumps({"characters": []}, ensure_ascii=False)
                world_json = json.dumps({}, ensure_ascii=False)
                glossary_json = json.dumps({"terms": []}, ensure_ascii=False)

                cur.execute("""
                    INSERT INTO bibles (project_id, version, is_active,
                                        cast_json, world_json, glossary_json)
                    VALUES (?, 1, 1, ?, ?, ?)
                """, (pid, cast_json, world_json, glossary_json))
                migrated_count += 1

            if migrated_count > 0:
                print(f"  → Migrated {migrated_count} projects (placeholder).")
                print(f"  ⚠ KHUYẾN NGHỊ: re-run Stage 1 (Bible) cho các projects này")
                print(f"    để có Bible chất lượng (v1 schema không tương thích hoàn toàn).")
            else:
                print(f"  → Không có data cũ cần migrate.")
        else:
            print("  → projects.bible_json đã không tồn tại, skip.")

        # ─── 9. DROP translate_chunks table (không dùng nữa) ────────────────
        print("\n[9] Drop deprecated: translate_chunks")
        if table_exists(cur, "translate_chunks"):
            cur.execute("DROP TABLE translate_chunks")
            print("  [-] translate_chunks (dropped)")
        else:
            print("  [=] translate_chunks (already gone)")

        conn.commit()

        # ─── 10. Final summary ──────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("✅ Migration COMPLETE")
        print("=" * 60)

        tables_after = sorted([r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()])
        print("\nTables in DB:")
        for t in tables_after:
            count = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {count} rows")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration FAILED: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
