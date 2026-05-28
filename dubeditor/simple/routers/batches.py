"""
Translate batches router — Bước II.

Endpoints (prefix: /api/projects/{project_id}/simple/batches):
  GET    /                       → TranslateStateOut
  POST   /config                 → đổi config + (optional) rebuild
  POST   /rebuild                → rebuild batches từ subtitles (sau khi Bible thay đổi)
  POST   /{idx}/save             → manual save 1 batch response
  POST   /{idx}/auto             → gọi LLM dịch 1 batch
  POST   /{idx}/reset            → reset 1 batch về idle
  POST   /run-from/{idx}         → chạy N batches từ idx (normal hoặc turbo)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Project
from dubeditor.simple.models import SimpleBatch
from dubeditor.simple.schemas import (
    TranslateStateOut, BatchConfigIn, SaveResponseIn, RunFromIn, OkOut,
)
from dubeditor.simple import service_translate
from dubeditor.simple import service_config

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_project(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


@router.get("", response_model=TranslateStateOut)
def get_state(project_id: int, db: Session = Depends(get_db)):
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)

    # Lazy init batches nếu chưa có
    count = db.query(SimpleBatch).filter(
        SimpleBatch.project_id == project_id
    ).count()
    if count == 0:
        try:
            service_translate.rebuild_batches(db, project_id, config)
        except Exception as e:
            logger.warning(f"[batches/get] lazy rebuild failed: {e}")

    return service_translate.get_translate_state(db, project_id, config)


@router.post("/config", response_model=TranslateStateOut)
def update_config(
    project_id: int,
    body: BatchConfigIn,
    db: Session = Depends(get_db),
):
    """Update batch config + optionally rebuild."""
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)

    # Apply changes
    for field in [
        'batch_size_target', 'batch_size_max', 'gap_threshold_seconds',
        'concurrency_mode', 'turbo_concurrency', 'previous_context_lines',
    ]:
        new_val = getattr(body, field, None)
        if new_val is not None:
            setattr(config, field, new_val)

    service_config.save_config(db, project_id, config)

    if body.rebuild:
        try:
            service_translate.rebuild_batches(db, project_id, config)
        except Exception as e:
            raise HTTPException(500, f"Rebuild failed: {e}")

    return service_translate.get_translate_state(db, project_id, config)


@router.post("/rebuild", response_model=TranslateStateOut)
def rebuild(project_id: int, db: Session = Depends(get_db)):
    """Rebuild toàn bộ batches từ subtitles + master Bible hiện tại.

    Dùng khi: vừa update Bible / sửa subtitles / đổi config gap.
    XÓA hết bản dịch cũ trong batches (translation trên subtitles giữ nguyên).
    """
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)
    try:
        service_translate.rebuild_batches(db, project_id, config)
    except Exception as e:
        raise HTTPException(500, f"Rebuild failed: {e}")
    return service_translate.get_translate_state(db, project_id, config)


@router.post("/{idx}/save", response_model=TranslateStateOut)
def save_batch(
    project_id: int,
    idx: int,
    body: SaveResponseIn,
    db: Session = Depends(get_db),
):
    """Manual paste response cho 1 batch."""
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)

    batch = _find_batch(db, project_id, idx)

    try:
        service_translate.save_batch_response(db, batch.id, body.response)
    except ValueError as e:
        raise HTTPException(422, str(e))

    return service_translate.get_translate_state(db, project_id, config)


@router.post("/{idx}/auto", response_model=TranslateStateOut)
async def auto_run_batch(
    project_id: int,
    idx: int,
    db: Session = Depends(get_db),
):
    """Auto: gọi LLM dịch 1 batch."""
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)
    batch = _find_batch(db, project_id, idx)

    try:
        await service_translate.run_batch(db, batch.id, config)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"[batches/auto] batch={idx} project={project_id}")
        raise HTTPException(500, f"LLM error: {e}")

    return service_translate.get_translate_state(db, project_id, config)


@router.post("/{idx}/reset", response_model=TranslateStateOut)
def reset_batch(
    project_id: int,
    idx: int,
    db: Session = Depends(get_db),
):
    """Reset 1 batch về idle (xóa dịch của subtitles trong batch range)."""
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)
    batch = _find_batch(db, project_id, idx)
    service_translate.reset_batch(db, batch.id)
    return service_translate.get_translate_state(db, project_id, config)


@router.post("/run-from/{idx}", response_model=TranslateStateOut)
async def run_from(
    project_id: int,
    idx: int,
    body: RunFromIn,
    db: Session = Depends(get_db),
):
    """Run batches từ idx đến hết (normal: tuần tự / turbo: song song)."""
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)

    try:
        result = await service_translate.run_from(
            db, project_id, idx, config, only_idle=body.only_idle,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"[batches/run-from] from={idx} project={project_id}")
        raise HTTPException(500, f"Error: {e}")

    logger.info(f"[batches/run-from] {result}")
    return service_translate.get_translate_state(db, project_id, config)


# ─── Backfill: sync simple_text_vi → text legacy ─────────────────────────────

@router.post("/sync-to-editor", response_model=OkOut)
def sync_to_editor(project_id: int, db: Session = Depends(get_db)):
    """Backfill: tạo đủ Characters từ Bible + copy simple_text_vi → text +
    map simple_speaker_zh → character_id (resolve alias).

    Dùng 1 lần sau khi update code — các dòng đã dịch TRƯỚC fix sẽ được sync.
    """
    from dubeditor.models import Subtitle
    from dubeditor.simple.service_characters import (
        sync_characters_from_bible, build_alias_map,
    )
    from dubeditor.simple.service_bible import get_master_bible_dict
    from dubeditor.models import Character

    # 1. Tạo đủ nhân vật từ Bible (11 nhân vật)
    char_sync = sync_characters_from_bible(db, project_id)

    # 2. Build speaker → character_id (gồm alias)
    master = get_master_bible_dict(db, project_id)
    alias_map = build_alias_map(master)
    chars = db.query(Character).filter(
        Character.project_id == project_id,
        Character.name_zh.isnot(None),
    ).all()
    canon_to_id = {c.name_zh: c.id for c in chars}
    speaker_to_id = {}
    for key, canon in alias_map.items():
        cid = canon_to_id.get(canon)
        if cid:
            speaker_to_id[key] = cid
    for canon, cid in canon_to_id.items():
        speaker_to_id.setdefault(canon, cid)

    # 3. Sync subtitles
    subs = db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.simple_text_vi.isnot(None),
    ).all()

    text_count = 0
    char_count = 0
    for s in subs:
        if s.simple_text_vi and s.simple_text_vi != s.text:
            s.text = s.simple_text_vi
            text_count += 1
        spk = s.simple_speaker_zh
        if spk:
            cid = speaker_to_id.get(spk)
            if cid and s.character_id != cid:
                s.character_id = cid
                char_count += 1

    db.commit()
    return OkOut(
        ok=True,
        message=(
            f"Tạo {char_sync['created']} nhân vật mới ({char_sync['total']} tổng) · "
            f"sync {text_count} dòng text + {char_count} dòng speaker → Editor."
        ),
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _find_batch(db: Session, project_id: int, idx: int) -> SimpleBatch:
    batch = (
        db.query(SimpleBatch)
        .filter(
            SimpleBatch.project_id == project_id,
            SimpleBatch.batch_index == idx,
        )
        .first()
    )
    if not batch:
        raise HTTPException(404, f"Batch {idx} not found")
    return batch
