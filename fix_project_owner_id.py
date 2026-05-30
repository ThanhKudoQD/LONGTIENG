#!/usr/bin/env python3
"""
fix_project_owner_id.py — Chẩn đoán + fix Project.owner_id trong models.py.

Có thể patch trước đó không inject được do format dòng `id = Column(...)` khác regex.
Script này tìm class Project bằng cách parse code rồi inject `owner_id` an toàn.

Idempotent: chạy nhiều lần OK.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
MODELS_FILE = ROOT / "dubeditor" / "models.py"


def msg(s, status='INFO'):
    colors = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m', 'SKIP': '\033[90m'}
    print(f"{colors.get(status, '')}[{status}]\033[0m {s}")


def main():
    if not MODELS_FILE.exists():
        msg(f"Không tìm thấy {MODELS_FILE}", 'ERR'); sys.exit(1)

    text = MODELS_FILE.read_text(encoding='utf-8')

    # 1) Diagnose
    msg(f"Đang kiểm tra {MODELS_FILE}")
    has_owner_in_text = 'owner_id' in text
    print(f"   - 'owner_id' xuất hiện trong file: {has_owner_in_text}")

    # 2) Tìm class Project
    pattern = re.compile(
        r'^class\s+Project\s*\(Base\)\s*:\s*\n',
        re.MULTILINE
    )
    m = pattern.search(text)
    if not m:
        msg("Không tìm thấy class Project(Base) — ai sửa file khác lạ?", 'ERR')
        sys.exit(2)

    class_start = m.end()
    # Tìm hết class Project: tới class khác hoặc EOF
    next_class = re.compile(r'^class\s+\w+', re.MULTILINE).search(text, class_start)
    class_end = next_class.start() if next_class else len(text)
    class_body = text[class_start:class_end]

    msg(f"   - class Project tìm thấy: dòng {text[:class_start].count(chr(10))+1} → {text[:class_end].count(chr(10))+1}", 'INFO')

    # Kiểm tra trong class body có owner_id chưa
    if 'owner_id' in class_body:
        msg("class Project ĐÃ có 'owner_id' — không cần inject", 'SKIP')
        # Vẫn check imports ForeignKey
        if 'ForeignKey' not in text:
            msg("WARNING: ForeignKey chưa import — owner_id có thể lỗi runtime", 'WARN')
        # Verify model qua SQLAlchemy
        verify_model()
        return

    # 3) Inject owner_id ngay sau __tablename__ (an toàn nhất, không phụ thuộc format `id`)
    # Tìm dòng __tablename__ trong class Project
    tablename_match = re.search(
        r'^(\s+__tablename__\s*=\s*[\'"]projects[\'"]\s*\n)',
        class_body,
        re.MULTILINE
    )
    if not tablename_match:
        msg("Không tìm thấy __tablename__ = 'projects' trong class Project", 'ERR')
        msg("In ra 10 dòng đầu của class Project để debug:", 'WARN')
        for line in class_body.split('\n')[:15]:
            print(f"   | {line}")
        sys.exit(3)

    # Detect indent level
    indent_match = re.match(r'^(\s+)', tablename_match.group(1))
    indent = indent_match.group(1) if indent_match else '    '

    inject_line = f"{indent}owner_id            = Column(Integer, ForeignKey(\"users.id\", ondelete=\"SET NULL\"), nullable=True, index=True)  # v5.0 user system\n"

    # Tìm vị trí cuối dòng __tablename__ trong file gốc
    abs_tablename_end = class_start + tablename_match.end()
    new_text = text[:abs_tablename_end] + inject_line + text[abs_tablename_end:]

    # 4) Verify ForeignKey, Integer đã được import
    needed_imports = []
    if 'ForeignKey' not in text:
        needed_imports.append('ForeignKey')
    if 'Integer' not in text:
        needed_imports.append('Integer')

    if needed_imports:
        msg(f"Thêm import: {', '.join(needed_imports)}", 'INFO')
        # Tìm dòng `from sqlalchemy import ...`
        import_pattern = re.compile(r'^from sqlalchemy import\s+(.+?)$', re.MULTILINE)
        im = import_pattern.search(new_text)
        if im:
            existing = im.group(1)
            additions = [i for i in needed_imports if i not in existing]
            if additions:
                new_imports = existing.rstrip() + ', ' + ', '.join(additions)
                new_text = new_text[:im.start(1)] + new_imports + new_text[im.end(1):]

    # Backup + write
    backup = MODELS_FILE.with_suffix('.py.bak_fix_owner')
    backup.write_text(text, encoding='utf-8')
    MODELS_FILE.write_text(new_text, encoding='utf-8')
    msg(f"Đã inject Project.owner_id (backup: {backup.name})", 'OK')

    # 5) Xóa pycache
    import shutil
    for p in (ROOT / "dubeditor").rglob("__pycache__"):
        try:
            shutil.rmtree(p)
        except Exception:
            pass
    msg("Đã xóa __pycache__", 'OK')

    # 6) Verify
    verify_model()


def verify_model():
    """Import models.py + check Project có owner_id không."""
    msg("Verify model qua import...", 'INFO')
    # Phải clear cache + reload sạch
    import importlib, sys as _sys
    # Force reload nếu đã import trước đó
    mods_to_remove = [k for k in _sys.modules if k.startswith('dubeditor')]
    for m in mods_to_remove:
        del _sys.modules[m]

    try:
        from dubeditor.models import Project  # type: ignore
        cols = [c.name for c in Project.__table__.columns]
        if 'owner_id' in cols:
            msg(f"✓ Project.owner_id OK ({len(cols)} columns)", 'OK')
            return True
        else:
            msg(f"✗ Project KHÔNG có owner_id! Columns: {cols}", 'ERR')
            return False
    except Exception as e:
        msg(f"Import models.py failed: {e}", 'ERR')
        return False


if __name__ == '__main__':
    main()
    print()
    msg("Xong. Restart server: python app.py", 'OK')
