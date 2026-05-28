"""
Reset toàn bộ batches cho 1 project (hoặc tất cả) và rebuild với template + Bible
hiện tại trong DB.

Dùng khi:
  - Bạn đã copy template prompt mới (translate_batch.txt) vào prompts/
  - Bible đã save (single hoặc merge done)
  - Nhưng batches trong DB vẫn lưu prompt cũ (build từ trước khi có template mới)

Cách dùng:

  # Reset cho 1 project (vd project_id = 14)
  python -m migrations.reset_batches 14

  # Reset cho TẤT CẢ projects
  python -m migrations.reset_batches all

⚠️ Sẽ XÓA bản dịch trong simple_batches.response của project chỉ định.
   KHÔNG xóa subtitles.simple_text_vi (bản dịch đã apply vào subtitle).
   Sau khi rebuild, các batch sẽ ở status='idle' với prompt MỚI sẵn sàng để Auto.
"""
import sys
from pathlib import Path

# Setup sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dubeditor.database import SessionLocal
from dubeditor.simple.models import SimpleBatch
from dubeditor.simple import service_translate, service_config


def reset_one_project(project_id: int) -> dict:
    """Reset + rebuild batches cho 1 project."""
    db = SessionLocal()
    try:
        old_count = db.query(SimpleBatch).filter(
            SimpleBatch.project_id == project_id
        ).count()

        # Xóa tất cả batches cũ
        db.query(SimpleBatch).filter(
            SimpleBatch.project_id == project_id
        ).delete()
        db.commit()

        # Load config
        config = service_config.load_config(db, project_id)

        # Rebuild
        service_translate.rebuild_batches(db, project_id, config)

        new_count = db.query(SimpleBatch).filter(
            SimpleBatch.project_id == project_id
        ).count()

        return {
            "project_id": project_id,
            "old_count": old_count,
            "new_count": new_count,
            "status": "ok",
        }
    except Exception as e:
        return {
            "project_id": project_id,
            "status": "error",
            "error": str(e),
        }
    finally:
        db.close()


def reset_all_projects() -> list:
    """Reset cho tất cả projects."""
    from dubeditor.models import Project
    db = SessionLocal()
    try:
        projects = db.query(Project).all()
        project_ids = [p.id for p in projects]
    finally:
        db.close()

    results = []
    for pid in project_ids:
        r = reset_one_project(pid)
        results.append(r)
        print(f"  Project {pid}: {r}")
    return results


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = sys.argv[1]

    print(f"\n{'='*60}")
    print(f" Reset batches — pipeline Simple v4")
    print(f"{'='*60}\n")

    if target == "all":
        print("Reset batches cho TẤT CẢ projects...\n")
        results = reset_all_projects()
        ok = sum(1 for r in results if r.get("status") == "ok")
        print(f"\n✓ Done. {ok}/{len(results)} OK.")
    else:
        try:
            pid = int(target)
        except ValueError:
            print(f"❌ Invalid project_id: {target}")
            sys.exit(1)

        print(f"Reset batches cho project {pid}...\n")
        result = reset_one_project(pid)
        if result["status"] == "ok":
            print(f"✓ OK")
            print(f"  Old batches: {result['old_count']}")
            print(f"  New batches: {result['new_count']}")
        else:
            print(f"❌ Error: {result['error']}")
            sys.exit(1)

    print()
    print("Bước tiếp theo:")
    print("  1. F5 trang FE")
    print("  2. Vào tab 'Dịch batch'")
    print("  3. Check prompt của batch đầu tiên")
    print()
    print("  Prompt phải có:")
    print("    - 'MOVIE BIBLE' section (KHÔNG còn '[ACTIVE_BIBLE]')")
    print("    - JSON Bible đầy đủ với nhân vật (KHÔNG còn '{}' rỗng)")
    print("    - 'CURRENT SUBTITLE LINES' section")


if __name__ == "__main__":
    main()
