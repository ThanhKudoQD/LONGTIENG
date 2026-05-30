#!/usr/bin/env python3
"""
restore_srt_v2.py — Khôi phục các folder thiếu trong srt_translator_v2/.

Copy:
  _refs/srt_translator_v2/stages/        → srt_translator_v2/stages/
  _refs/srt_translator_v2/prompts/       → srt_translator_v2/prompts/
  _refs/srt_translator_v2/manual/        → srt_translator_v2/manual/
  _refs/srt_translator_v2/genre_packs/   → srt_translator_v2/genre_packs/

Chỉ copy folder nào CHƯA tồn tại trong target. Không ghi đè file user đã sửa.
"""
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
REFS = ROOT / "_refs" / "srt_translator_v2"
TARGET = ROOT / "srt_translator_v2"


def msg(s, status='INFO'):
    c = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m', 'SKIP': '\033[90m'}
    print(f"{c.get(status, '')}[{status}]\033[0m {s}")


def main():
    if not REFS.exists():
        msg(f"Không tìm thấy {REFS}", 'ERR'); sys.exit(1)
    if not TARGET.exists():
        msg(f"Không tìm thấy {TARGET}", 'ERR'); sys.exit(1)

    msg(f"Refs:   {REFS}")
    msg(f"Target: {TARGET}")
    print()

    restored = []
    skipped = []

    # Duyệt từng file trong refs, copy nếu chưa có ở target
    for ref_file in REFS.rglob("*"):
        if ref_file.is_dir():
            continue
        if '__pycache__' in str(ref_file):
            continue
        rel = ref_file.relative_to(REFS)
        target_file = TARGET / rel
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if target_file.exists():
            skipped.append(str(rel))
        else:
            shutil.copy(ref_file, target_file)
            restored.append(str(rel))

    msg(f"Đã restore {len(restored)} file:", 'OK')
    for f in sorted(restored):
        print(f"   + {f}")
    if skipped:
        msg(f"Bỏ qua {len(skipped)} file đã có:", 'SKIP')
        for f in sorted(skipped)[:5]:
            print(f"   = {f}")
        if len(skipped) > 5:
            print(f"   ... và {len(skipped)-5} file khác")

    # Xóa __pycache__
    for p in TARGET.rglob("__pycache__"):
        try: shutil.rmtree(p)
        except: pass
    msg("Đã xóa __pycache__", 'OK')

    # Verify import chain
    print()
    msg("Verify import...")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(TARGET))   # cho `from stages import ...`

    for mod_name in list(sys.modules):
        if mod_name.startswith('dubeditor') or mod_name in ('stages', 'core', 'models', 'manual'):
            del sys.modules[mod_name]

    try:
        from dubeditor.routers import translate
        n_routes = len(translate.router.routes)
        msg(f"  ✓ dubeditor.routers.translate ({n_routes} routes)", 'OK')

        # Check critical endpoints
        for crit in ['retranslate-batch', 'translate/status', 'translate/start']:
            found = any(crit in getattr(r, 'path', '') for r in translate.router.routes)
            mark = '✓' if found else '✗'
            status = 'OK' if found else 'ERR'
            msg(f"  {mark} endpoint chứa '{crit}'", status)
    except Exception as e:
        msg(f"  ✗ Import fail: {e}", 'ERR')
        import traceback
        traceback.print_exc()
        msg("Có thể còn file/folder khác thiếu — báo log cho tôi", 'WARN')
        sys.exit(2)

    print()
    msg("🎉 Restore xong. Restart server: python app.py", 'OK')


if __name__ == '__main__':
    main()
