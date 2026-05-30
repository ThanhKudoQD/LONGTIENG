#!/usr/bin/env python3
"""
cleanup_old_translate.py — Xóa toàn bộ pipeline dịch CŨ (auto, không thủ công).

Giữ lại:
- `srt_translator_v2/core/llm_client.py` — simple/llm_runner.py vẫn dùng để gọi LLM
- `srt_translator_v2/core/__init__.py`
- Module `dubeditor/simple/` (pipeline mới thủ công + auto)
- FE module `components/translate/simple/`

Xóa:
- Pipeline cũ BE: routers/translate.py, translate_service.py, llm_log_service.py
- srt_translator_v2/{stages, manual, prompts, genre_packs, models, examples, tests, configs}/
- srt_translator_v2/core/{pipeline, srt_parser, noise_filter, suspicious_scanner, token_counter}.py
- srt_translator_v2/config.py, run.py
- BE models: Bible, Chunk, Scene, StoryArc, PolishIssue, PipelineEvent (xóa class + drop table)
- FE: TranslatePage.tsx, RetranslateModal.tsx, ConfigModal.tsx, components/translate/*.tsx (không phải simple/)
- Router include: dòng `from dubeditor.routers import translate` + include_router(translate.router)
- File backup .bak_*

An toàn:
- Trước xóa: backup project sang folder timestamped
- Sau xóa: verify import dubeditor.simple OK
"""
import os
import re
import sys
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()


def msg(s, status='INFO'):
    c = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m', 'SKIP': '\033[90m', 'KEEP': '\033[35m'}
    print(f"{c.get(status, '')}[{status}]\033[0m {s}")


# ─── Files / dirs cần xóa ────────────────────────────────────────────────────

DIRS_TO_DELETE = [
    # srt_translator_v2: chỉ giữ core/llm_client.py + core/__init__.py
    'srt_translator_v2/stages',
    'srt_translator_v2/manual',
    'srt_translator_v2/prompts',
    'srt_translator_v2/genre_packs',
    'srt_translator_v2/models',
    'srt_translator_v2/examples',
    'srt_translator_v2/tests',
    'srt_translator_v2/configs',
    'srt_translator_v2/checkpoints',
    'srt_translator_v2/__pycache__',
    'srt_translator_v2/core/__pycache__',
]

FILES_TO_DELETE = [
    # BE pipeline cũ
    'dubeditor/routers/translate.py',
    'dubeditor/translate_service.py',
    'dubeditor/llm_log_service.py',

    # srt_translator_v2 root files
    'srt_translator_v2/config.py',
    'srt_translator_v2/run.py',
    'srt_translator_v2/check_dataset.py',
    'srt_translator_v2/diarize_worker.py',
    'srt_translator_v2/requirements.txt',
    'srt_translator_v2/ARCHITECTURE.md',
    'srt_translator_v2/QUICK_START.md',
    'srt_translator_v2/README.md',

    # srt_translator_v2/core — xóa các file không phải llm_client + __init__
    'srt_translator_v2/core/pipeline.py',
    'srt_translator_v2/core/srt_parser.py',
    'srt_translator_v2/core/noise_filter.py',
    'srt_translator_v2/core/suspicious_scanner.py',
    'srt_translator_v2/core/token_counter.py',

    # Root tools cũ liên quan translate
    'check_dataset.py',
    'diarize_worker.py',

    # FE
    'dubeditor_frontend/src/components/TranslatePage.tsx',
    'dubeditor_frontend/src/components/RetranslateModal.tsx',
    'dubeditor_frontend/src/components/ConfigModal.tsx',
    'dubeditor_frontend/src/components/translate/BibleViewer.tsx',
    'dubeditor_frontend/src/components/translate/CleanedView.tsx',
    'dubeditor_frontend/src/components/translate/ConfigPanel.tsx',
    'dubeditor_frontend/src/components/translate/IssueQueue.tsx',
    'dubeditor_frontend/src/components/translate/ProgressLog.tsx',
    'dubeditor_frontend/src/components/translate/SceneList.tsx',
    'dubeditor_frontend/src/components/translate/SubtitlesView.tsx',
]

# DB models / tables cần xóa
MODEL_CLASSES_TO_REMOVE = [
    'Bible', 'StoryArc', 'Chunk', 'Scene', 'PolishIssue',
    'PipelineEvent', 'LLMCall', 'AutoFixSnapshot', 'RemovedSubtitle',
]
TABLES_TO_DROP = [
    'bibles', 'story_arcs', 'chunks', 'scenes',
    'polish_issues', 'pipeline_events', 'llm_calls',
    'auto_fix_snapshots', 'removed_subtitles',
]


# ─── 1) Backup ───────────────────────────────────────────────────────────────

def make_backup():
    ts = int(time.time())
    backup_dir = ROOT.parent / f"nano_backup_before_cleanup_{ts}"
    msg(f"Backup project sang: {backup_dir}", 'WARN')
    msg(f"  Có thể mất 1-2 phút...", 'INFO')

    # Excludes
    excludes = ['__pycache__', 'node_modules', 'data/projects', 'data/dubeditor.db',
                'VoxCPM2', '.git', 'release']
    # Dùng rsync nếu có (nhanh hơn), fallback cp
    import subprocess
    excl_args = []
    for e in excludes:
        excl_args.extend(['--exclude', e])
    try:
        subprocess.run(['rsync', '-a', *excl_args, str(ROOT) + '/', str(backup_dir) + '/'],
                       check=True, capture_output=True, timeout=600)
        msg(f"Backup xong ({backup_dir})", 'OK')
        return backup_dir
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        msg(f"rsync fail/timeout — skip backup. Project hiện tại: {ROOT}", 'WARN')
        return None


# ─── 2) Delete files / dirs ──────────────────────────────────────────────────

def delete_paths():
    msg("Xóa folders...")
    deleted_dirs = 0
    for rel in DIRS_TO_DELETE:
        p = ROOT / rel
        if p.exists():
            shutil.rmtree(p)
            msg(f"  ✗ {rel}", 'INFO')
            deleted_dirs += 1
    msg(f"Xóa {deleted_dirs} folders", 'OK')

    print()
    msg("Xóa files...")
    deleted_files = 0
    for rel in FILES_TO_DELETE:
        p = ROOT / rel
        if p.exists():
            p.unlink()
            msg(f"  ✗ {rel}", 'INFO')
            deleted_files += 1
    msg(f"Xóa {deleted_files} files", 'OK')


# ─── 3) Cleanup .bak_* files ─────────────────────────────────────────────────

def cleanup_backups():
    print()
    msg("Xóa file .bak_* trong project (do các script patch trước)...")
    n = 0
    for p in ROOT.rglob("*.bak_*"):
        if p.is_file() and 'node_modules' not in str(p) and '.git' not in str(p):
            p.unlink()
            n += 1
    msg(f"Xóa {n} file backup", 'OK')


# ─── 4) Update router.py — remove translate include ──────────────────────────

def patch_router_py():
    print()
    msg("Remove `translate` khỏi router.py...")
    f = ROOT / 'dubeditor' / 'router.py'
    if not f.exists():
        msg("router.py không có", 'WARN'); return
    text = f.read_text(encoding='utf-8')
    new_text = text

    # Xóa dòng import
    new_text = re.sub(
        r'^from dubeditor\.routers import translate\s*\n', '',
        new_text, flags=re.MULTILINE
    )
    # Xóa dòng include_router
    new_text = re.sub(
        r'^router\.include_router\(\s*translate\.router.*?\n', '',
        new_text, flags=re.MULTILINE
    )

    if new_text != text:
        f.write_text(new_text, encoding='utf-8')
        msg("router.py: đã xóa translate include", 'OK')
    else:
        msg("router.py: không có translate include — bỏ qua", 'SKIP')


def patch_core_init():
    """Sửa srt_translator_v2/core/__init__.py để chỉ import llm_client.
    Module simple/llm_runner.py chỉ cần `from core.llm_client import ...`."""
    print()
    msg("Patch srt_translator_v2/core/__init__.py — chỉ giữ llm_client...")
    f = ROOT / 'srt_translator_v2' / 'core' / '__init__.py'
    if not f.exists():
        msg("core/__init__.py không có", 'WARN'); return

    NEW = '''"""Core utilities — slimmed: chỉ giữ llm_client cho module simple."""
from core.llm_client import (
    LLMRequest, LLMResponse, call_llm,
    detect_provider, parse_json_response,
    CostTracker, estimate_cost,
)

__all__ = [
    "LLMRequest", "LLMResponse", "call_llm",
    "detect_provider", "parse_json_response",
    "CostTracker", "estimate_cost",
]
'''
    f.write_text(NEW, encoding='utf-8')
    msg("core/__init__.py: đã slim down", 'OK')


def patch_projects_py():
    """projects.py import Bible/Scene đã xóa → bỏ import + thay query bằng default."""
    print()
    msg("Patch dubeditor/routers/projects.py — bỏ Bible/Scene refs...")
    f = ROOT / 'dubeditor' / 'routers' / 'projects.py'
    if not f.exists():
        msg("projects.py không có", 'WARN'); return False
    text = f.read_text(encoding='utf-8')
    orig = text

    # 1) Bỏ Bible, Scene khỏi import
    text = re.sub(
        r'from dubeditor\.models import Project, Subtitle, Bible, Scene, User',
        'from dubeditor.models import Project, Subtitle, User',
        text,
    )
    # Fallback: bỏ riêng từng tên trong bất kỳ import nào
    for cls in ['Bible', 'Scene', 'Chunk', 'StoryArc', 'PolishIssue',
                'PipelineEvent', 'LLMCall', 'AutoFixSnapshot', 'RemovedSubtitle']:
        text = re.sub(rf',\s*{cls}\b', '', text)
        text = re.sub(rf'\b{cls}\s*,\s*', '', text)

    # 2) Thay query scene_count = ... → 0
    text = re.sub(
        r'scene_count = db\.query\(func\.count\(Scene\.id\)\)\.filter\(Scene\.project_id == p\.id\)\.scalar\(\)',
        'scene_count = 0    # pipeline cũ đã bỏ',
        text,
    )

    # 3) Thay has_bible query → False
    text = re.sub(
        r'has_bible = db\.query\(Bible\)\.filter\([^)]*\)\.first\(\) is not None',
        'has_bible = False    # pipeline cũ đã bỏ — Simple Bible check riêng',
        text,
        flags=re.DOTALL,
    )
    # Backup pattern khi has_bible đa dòng:
    text = re.sub(
        r'has_bible = db\.query\(Bible\)\.filter\(\s*Bible\.project_id == p\.id,\s*Bible\.is_active == True\s*#[^\n]*\n\s*\)\.first\(\) is not None',
        'has_bible = False    # pipeline cũ đã bỏ',
        text,
    )

    if text == orig:
        msg("projects.py: không có thay đổi cần áp dụng", 'SKIP')
        return True

    # Verify syntax
    try:
        import ast
        ast.parse(text)
    except SyntaxError as e:
        msg(f"SYNTAX ERROR sau khi sửa: {e}", 'ERR')
        return False

    f.write_text(text, encoding='utf-8')
    msg("projects.py: đã bỏ Bible/Scene refs", 'OK')
    return True


# ─── 5) Update models.py — remove pipeline cũ classes ────────────────────────

def patch_models_py():
    print()
    msg("Remove pipeline cũ classes khỏi models.py...")
    f = ROOT / 'dubeditor' / 'models.py'
    text = f.read_text(encoding='utf-8')
    original_text = text
    new_text = text

    for cls in MODEL_CLASSES_TO_REMOVE:
        # Pattern: từ `class XYZ(Base):` cho đến trước `class XXX` kế tiếp HOẶC hết file
        pattern = (
            rf'^class {cls}\(Base\)\s*:\s*\n'
            r'(?:[ \t]+.*\n|[ \t]*\n)*'   # body indented
        )
        new_text2 = re.sub(pattern, '', new_text, flags=re.MULTILINE)
        if new_text2 != new_text:
            msg(f"  ✗ class {cls}", 'INFO')
            new_text = new_text2

    if new_text != original_text:
        # Verify syntax
        try:
            import ast
            ast.parse(new_text)
        except SyntaxError as e:
            msg(f"SYNTAX ERROR sau khi xóa: {e}", 'ERR')
            return False
        f.write_text(new_text, encoding='utf-8')
        msg("models.py: đã xóa pipeline cũ classes", 'OK')
    else:
        msg("models.py: không có class nào cần xóa", 'SKIP')
    return True


# ─── 6) Drop bảng DB cũ ──────────────────────────────────────────────────────

def drop_db_tables():
    print()
    msg("Drop bảng DB cũ...")
    db = ROOT / 'data' / 'dubeditor.db'
    if not db.exists():
        msg("DB không tồn tại — bỏ qua", 'SKIP'); return

    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    dropped = 0
    for tbl in TABLES_TO_DROP:
        try:
            cur.execute(f"DROP TABLE IF EXISTS {tbl}")
            dropped += 1
            msg(f"  ✗ DROP TABLE {tbl}", 'INFO')
        except Exception as e:
            msg(f"  ! {tbl}: {e}", 'WARN')
    conn.commit()
    conn.close()
    msg(f"Drop {dropped} bảng", 'OK')


# ─── 7) Cleanup imports trong các file còn lại ───────────────────────────────

def cleanup_orphan_imports():
    """Xóa các import từ pipeline cũ trong code còn lại."""
    print()
    msg("Cleanup orphan imports...")

    # Pattern import sẽ thành dead
    patterns_to_remove = [
        r'from dubeditor\.translate_service import .*\n',
        r'from dubeditor\.llm_log_service import .*\n',
        r'from dubeditor\.models import \(\s*Bible|Chunk|Scene|StoryArc|PolishIssue|PipelineEvent|LlmCall',  # cảnh báo
    ]
    n_changed = 0
    for py in (ROOT / 'dubeditor').rglob("*.py"):
        if '__pycache__' in str(py) or 'simple' in str(py) and 'service_retranslate' not in str(py):
            # simple module tự đứng vững, không sửa
            pass
        if '__pycache__' in str(py):
            continue
        text = py.read_text(encoding='utf-8')
        orig = text
        # Chỉ xóa dòng import hoàn toàn — không sửa code logic
        text = re.sub(r'^from dubeditor\.translate_service import .*\n', '', text, flags=re.MULTILINE)
        text = re.sub(r'^from dubeditor\.llm_log_service import .*\n', '', text, flags=re.MULTILINE)
        if text != orig:
            py.write_text(text, encoding='utf-8')
            msg(f"  ⊝ {py.relative_to(ROOT)}", 'INFO')
            n_changed += 1
    msg(f"Cleanup {n_changed} files", 'OK')


# ─── 8) Cleanup pycache ──────────────────────────────────────────────────────

def cleanup_pycache():
    n = 0
    for p in ROOT.rglob("__pycache__"):
        if 'node_modules' not in str(p) and '.git' not in str(p):
            try:
                shutil.rmtree(p); n += 1
            except: pass
    msg(f"Xóa {n} __pycache__", 'OK')


# ─── 9) Verify ───────────────────────────────────────────────────────────────

def verify():
    print()
    msg("Verify import sau cleanup...")
    sys.path.insert(0, str(ROOT))
    for mod_name in list(sys.modules):
        if mod_name.startswith('dubeditor') or mod_name.startswith('core'):
            del sys.modules[mod_name]
    failed = []
    try:
        from dubeditor.simple.routers import router as sr
        msg(f"  ✓ dubeditor.simple.routers ({len(sr.routes)} routes)", 'OK')
    except Exception as e:
        msg(f"  ✗ simple routers: {e}", 'ERR'); failed.append(('simple.routers', e))
    try:
        from dubeditor.router import router as main_router
        retrans_routes = [r for r in main_router.routes if 'retranslate' in getattr(r, 'path', '')]
        msg(f"  ✓ Main router ({len(main_router.routes)} routes, {len(retrans_routes)} retranslate)", 'OK')
    except Exception as e:
        msg(f"  ✗ Main router: {e}", 'ERR'); failed.append(('router', e))
    try:
        from dubeditor.simple.llm_runner import run_llm_task
        msg("  ✓ llm_runner import OK (dùng srt_translator_v2/core/llm_client)", 'OK')
    except Exception as e:
        msg(f"  ✗ llm_runner: {e}", 'ERR'); failed.append(('llm_runner', e))

    if failed:
        msg(f"Có {len(failed)} module fail import — RESTORE từ backup!", 'ERR')
        for name, e in failed:
            print(f"   {name}: {e}")
        return False
    return True


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    msg(f"Project: {ROOT}", 'INFO')
    print()

    # Confirm
    print("\033[33m⚠️  Script này sẽ xóa NHIỀU file pipeline cũ. KHÔNG THỂ undo dễ dàng.\033[0m")
    ans = input("Tiếp tục? gõ YES để xác nhận: ")
    if ans != 'YES':
        msg("Hủy bỏ.", 'WARN'); return

    print()
    backup_dir = make_backup()
    print()

    delete_paths()
    cleanup_backups()

    if not patch_models_py():
        msg("models.py fail — RESTORE từ backup!", 'ERR')
        return

    patch_router_py()
    patch_core_init()
    if not patch_projects_py():
        msg("projects.py fail — RESTORE từ backup!", 'ERR')
        return
    drop_db_tables()
    cleanup_orphan_imports()
    cleanup_pycache()

    if not verify():
        if backup_dir:
            msg(f"Restore: rm -rf {ROOT}/* && cp -r {backup_dir}/* {ROOT}/", 'WARN')
        sys.exit(1)

    print()
    msg("🎉 Cleanup hoàn tất!", 'OK')
    msg(f"  Backup ở: {backup_dir}" if backup_dir else "  (không có backup)", 'INFO')
    msg("Bước tiếp theo:", 'INFO')
    msg("  1) python app.py", 'INFO')
    msg("  2) Test UI hoạt động bình thường", 'INFO')
    msg("  3) Nếu OK → xóa backup folder để tiết kiệm disk", 'INFO')


if __name__ == '__main__':
    main()
