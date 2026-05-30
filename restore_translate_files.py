#!/usr/bin/env python3
"""
restore_translate_files.py — Khôi phục 2 file translate đã mất.

Copy:
  _refs/dubeditor/translate_service.py    → dubeditor/translate_service.py
  _refs/dubeditor/routers/translate.py    → dubeditor/routers/translate.py

Đồng thời thêm import + include_router cho translate vào router.py nếu thiếu.
"""
import re
import sys
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
REFS = ROOT / "_refs"
TARGET = ROOT / "dubeditor"


def msg(s, status='INFO'):
    c = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m', 'SKIP': '\033[90m'}
    print(f"{c.get(status, '')}[{status}]\033[0m {s}")


def main():
    if not REFS.exists():
        msg(f"Không tìm thấy {REFS}. Hãy giải nén zip vào /home/dmin/nano/", 'ERR')
        sys.exit(1)
    if not TARGET.exists():
        msg(f"Không tìm thấy {TARGET}", 'ERR'); sys.exit(1)

    # 1) Copy 2 file
    files = [
        ('translate_service.py',          'translate_service.py'),
        ('routers/translate.py',          'routers/translate.py'),
    ]
    for rel_src, rel_dst in files:
        src = REFS / 'dubeditor' / rel_src
        dst = TARGET / rel_dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            msg(f"Source thiếu: {src}", 'ERR'); sys.exit(2)
        if dst.exists():
            backup = dst.with_suffix(dst.suffix + f'.bak_{int(time.time())}')
            shutil.copy(dst, backup)
            msg(f"Backup {dst.name} → {backup.name}", 'SKIP')
        shutil.copy(src, dst)
        msg(f"Copied: {rel_dst}", 'OK')

    # 2) Fix router.py
    router_file = TARGET / "router.py"
    if not router_file.exists():
        msg(f"Không có router.py — tạo file mới? skip", 'ERR'); sys.exit(3)
    text = router_file.read_text(encoding='utf-8')

    needs_import = 'from dubeditor.routers import translate' not in text and \
                   'from dubeditor.routers.translate import' not in text
    needs_include = 'translate.router' not in text

    if needs_import or needs_include:
        backup = router_file.with_suffix(f'.py.bak_translate_{int(time.time())}')
        backup.write_text(text, encoding='utf-8')

        if needs_import:
            # Insert sau dòng `from dubeditor.routers` cuối cùng
            lines = text.split('\n')
            last_import = 0
            for i, l in enumerate(lines):
                if re.match(r'^from dubeditor\.routers', l):
                    last_import = i
            lines.insert(last_import + 1, 'from dubeditor.routers import translate')
            text = '\n'.join(lines)
            msg("Thêm import translate vào router.py", 'OK')

        if needs_include:
            lines = text.split('\n')
            last_inc = -1
            for i, l in enumerate(lines):
                if 'include_router' in l:
                    last_inc = i
            include_line = 'router.include_router(translate.router,    prefix="/api",            tags=["dub-translate"])'
            if last_inc >= 0:
                lines.insert(last_inc + 1, include_line)
            else:
                lines.append(include_line)
            text = '\n'.join(lines)
            msg("Thêm include_router(translate.router)", 'OK')

        # Verify syntax
        try:
            import ast
            ast.parse(text)
        except SyntaxError as e:
            msg(f"SYNTAX ERROR: {e}", 'ERR')
            shutil.copy(backup, router_file)
            sys.exit(4)

        router_file.write_text(text, encoding='utf-8')
        msg(f"Đã update router.py (backup: {backup.name})", 'OK')
    else:
        msg("router.py đã có translate — bỏ qua", 'SKIP')

    # 3) Xóa pycache
    for p in TARGET.rglob("__pycache__"):
        try: shutil.rmtree(p)
        except: pass
    msg("Đã xóa __pycache__", 'OK')

    # 4) Verify
    print()
    msg("Verify import...")
    sys.path.insert(0, str(ROOT))
    for mod_name in list(sys.modules):
        if mod_name.startswith('dubeditor'):
            del sys.modules[mod_name]

    try:
        from dubeditor.routers import translate
        n_routes = len(translate.router.routes)
        msg(f"  ✓ dubeditor.routers.translate ({n_routes} routes)", 'OK')

        # Đếm endpoint quan trọng
        critical = ['retranslate-batch', 'translate/status', 'translate/start']
        for crit in critical:
            found = any(crit in getattr(r, 'path', '') for r in translate.router.routes)
            mark = '✓' if found else '✗'
            color = 'OK' if found else 'ERR'
            msg(f"  {mark} endpoint chứa '{crit}'", color)
    except Exception as e:
        msg(f"  ✗ Import fail: {e}", 'ERR')
        import traceback
        traceback.print_exc()
        sys.exit(5)

    print()
    msg("🎉 Restore xong. Restart server: python app.py", 'OK')


if __name__ == '__main__':
    main()
