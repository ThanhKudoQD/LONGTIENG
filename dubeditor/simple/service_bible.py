"""
Bible service — Bước I.

Functions:
  - get_or_create_bible_state(db, project_id)        : load state hiện tại
  - rebuild_parts(db, project_id, mode, count)       : tạo parts mới khi đổi mode
  - run_bible_part(db, part, config)                 : gọi LLM cho 1 part
  - run_bible_merge(db, project_id, config)          : gọi LLM merge
  - save_part_response(db, part, response)           : manual save
  - save_merge_response(db, project_id, response)    : manual save merge
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import Project, Subtitle
from dubeditor.simple.models import (
    SimpleBiblePart, SimpleBibleMerge,
)
from dubeditor.simple.schemas import SimpleConfigSchema
from dubeditor.simple.llm_runner import run_llm_task, get_cost
from dubeditor.simple.service_utils import (
    load_prompt_template,
    fill_placeholder,
    fill_placeholders,
    format_srt_for_bible_prompt,
    parse_bible_json,
    estimate_tokens,
)

logger = logging.getLogger(__name__)


# ─── State loading ───────────────────────────────────────────────────────────

def get_bible_state(db: Session, project_id: int) -> dict:
    """Load full Bible state cho FE. Returns dict matching BibleStateOut."""
    parts = (
        db.query(SimpleBiblePart)
        .filter(SimpleBiblePart.project_id == project_id)
        .order_by(SimpleBiblePart.part_index)
        .all()
    )

    if not parts:
        # Chưa có parts → tạo mặc định 1 part single mode (lazy init)
        rebuild_parts(db, project_id, mode='single')
        parts = (
            db.query(SimpleBiblePart)
            .filter(SimpleBiblePart.project_id == project_id)
            .order_by(SimpleBiblePart.part_index)
            .all()
        )

    total = len(parts)
    mode = 'single' if total == 1 else 'multi'

    merge = None
    if mode == 'multi':
        merge = (
            db.query(SimpleBibleMerge)
            .filter(SimpleBibleMerge.project_id == project_id)
            .first()
        )

    # Build response
    parts_out = []
    for p in parts:
        parts_out.append({
            'index': p.part_index,
            'total': total,
            'start_line': p.start_line,
            'end_line': p.end_line,
            'est_tokens': p.est_tokens or 0,
            'prompt': p.prompt or '',
            'response': p.response,
            'status': p.status,
            'saved_at': p.saved_at,
            'characters_count': p.characters_count,
            'error_msg': p.error_msg,
        })

    merge_out = None
    if merge:
        merge_out = {
            'prompt': merge.prompt or '',
            'response': merge.response,
            'status': merge.status,
            'saved_at': merge.saved_at,
            'error_msg': merge.error_msg,
        }

    # Master bible (parse JSON nếu có)
    master_json = None
    master_chars = 0
    master_glossary = 0
    if mode == 'single' and parts[0].response:
        try:
            master_json = parse_bible_json(parts[0].response)
            master_chars = len(master_json.get('c', {}))
            master_glossary = len(master_json.get('t', {}))
        except Exception as e:
            logger.warning(f"Cannot parse single Bible: {e}")
    elif mode == 'multi' and merge and merge.master_bible_json:
        try:
            master_json = json.loads(merge.master_bible_json)
            master_chars = merge.master_characters_count or 0
            master_glossary = merge.master_glossary_count or 0
        except Exception as e:
            logger.warning(f"Cannot parse master Bible: {e}")

    return {
        'mode': mode,
        'parts': parts_out,
        'merge': merge_out,
        'master_bible_json': master_json,
        'master_characters_count': master_chars,
        'master_glossary_count': master_glossary,
    }


# ─── Rebuild parts (khi đổi mode hoặc reset) ─────────────────────────────────

def rebuild_parts(
    db: Session,
    project_id: int,
    mode: str,
    multi_parts_count: Optional[int] = None,
) -> None:
    """Xóa parts + merge cũ, tạo parts mới theo mode.

    Single mode: 1 part chứa toàn bộ SRT.
    Multi mode: N parts (~1000 dòng/part, ưu tiên cắt tại gap thời gian lớn).
    """
    # Xóa cũ (cascade tự xóa merge)
    db.query(SimpleBiblePart).filter(
        SimpleBiblePart.project_id == project_id
    ).delete()
    db.query(SimpleBibleMerge).filter(
        SimpleBibleMerge.project_id == project_id
    ).delete()
    db.commit()

    # Load subtitles theo index
    subtitles = (
        db.query(Subtitle)
        .filter(Subtitle.project_id == project_id)
        .order_by(Subtitle.index)
        .all()
    )

    if not subtitles:
        raise ValueError(f"Project {project_id} has no subtitles")

    total_lines = len(subtitles)

    # Tính số parts
    if mode == 'single':
        ranges = [(subtitles[0].index, subtitles[-1].index, subtitles)]
    else:
        # Multi mode: chia thành N parts
        if multi_parts_count is None:
            multi_parts_count = max(2, round(total_lines / 1000))
        ranges = _split_into_parts(subtitles, multi_parts_count)

    # Tạo records
    template_single = load_prompt_template('bible_single')
    template_multi = load_prompt_template('bible_multi_part')

    for idx, (start_line, end_line, part_subs) in enumerate(ranges):
        srt_block = format_srt_for_bible_prompt(part_subs)

        if mode == 'single':
            prompt = fill_placeholder(template_single, 'SUBTITLE_TEXT', srt_block)
        else:
            prompt = fill_placeholders(template_multi, {
                'PART_INDEX': str(idx + 1),
                'PART_TOTAL': str(len(ranges)),
                'START_LINE': str(start_line),
                'END_LINE': str(end_line),
                'SUBTITLE_TEXT': srt_block,
            })

        est_tok = estimate_tokens(prompt)

        part = SimpleBiblePart(
            project_id=project_id,
            part_index=idx,
            start_line=start_line,
            end_line=end_line,
            est_tokens=est_tok,
            prompt=prompt,
            status='idle',
        )
        db.add(part)

    # Tạo merge record (chỉ cho multi mode)
    if mode == 'multi':
        merge = SimpleBibleMerge(
            project_id=project_id,
            prompt='',   # sẽ build sau khi tất cả parts done
            status='idle',
        )
        db.add(merge)

    db.commit()


def _split_into_parts(subtitles: list, count: int) -> list[tuple[int, int, list]]:
    """Chia subtitles thành N parts. Ưu tiên cắt tại gap thời gian lớn.

    Trả list of (start_line, end_line, subtitles_slice).
    """
    if count <= 1:
        return [(subtitles[0].index, subtitles[-1].index, subtitles)]

    total = len(subtitles)
    target_size = total / count

    # Tìm các candidate cut points (gap ≥ trung bình + lớn nhất gần boundary)
    parts = []
    cursor = 0

    for part_no in range(count):
        is_last = (part_no == count - 1)
        if is_last:
            end_idx = total
        else:
            # Target end position
            ideal_end = int((part_no + 1) * target_size)
            # Tìm gap lớn nhất trong window ±20% quanh ideal_end
            window = max(10, int(target_size * 0.2))
            lo = max(cursor + 1, ideal_end - window)
            hi = min(total - 1, ideal_end + window)

            best_cut = ideal_end
            best_gap = -1.0
            for i in range(lo, hi):
                gap = subtitles[i + 1].start_time - subtitles[i].end_time
                if gap > best_gap:
                    best_gap = gap
                    best_cut = i + 1
            end_idx = best_cut

        slice_ = subtitles[cursor:end_idx]
        if not slice_:
            continue
        parts.append((slice_[0].index, slice_[-1].index, slice_))
        cursor = end_idx

    return parts


# ─── Run LLM for a part ──────────────────────────────────────────────────────

async def run_bible_part(
    db: Session,
    part_id: int,
    config: SimpleConfigSchema,
) -> SimpleBiblePart:
    """Gọi LLM cho 1 part. Update DB. Trả part đã update."""
    part = db.query(SimpleBiblePart).filter(SimpleBiblePart.id == part_id).first()
    if not part:
        raise ValueError(f"Part {part_id} not found")

    task_cfg = config.tasks.get('bible')
    if not task_cfg:
        raise ValueError("Missing 'bible' task config")

    api_key = getattr(config.api_keys, task_cfg.provider)
    if not api_key:
        raise ValueError(f"Missing API key for provider '{task_cfg.provider}'")

    # Mark running
    part.status = 'running'
    part.error_msg = None
    db.commit()

    try:
        resp = await run_llm_task(
            task='bible',
            prompt=part.prompt,
            model=task_cfg.model,
            api_key=api_key,
            thinking=task_cfg.thinking,
        )

        # Parse + validate
        parsed = parse_bible_json(resp.text)

        part.response = resp.text
        part.status = 'done'
        part.characters_count = len(parsed.get('c', {}))
        part.tokens_in = resp.tokens_in
        part.tokens_out = resp.tokens_out
        part.cost_usd = get_cost(resp)
        part.model_used = task_cfg.model
        part.saved_at = datetime.now(timezone.utc)
        db.commit()

        # Nếu single mode (chỉ 1 part), auto cập nhật master không cần merge
        total_parts = db.query(SimpleBiblePart).filter(
            SimpleBiblePart.project_id == part.project_id
        ).count()
        if total_parts == 1:
            # Single mode — part này = master luôn.
            _trigger_rebuild_batches(db, part.project_id)

        return part

    except Exception as e:
        part.status = 'error'
        part.error_msg = str(e)[:500]
        db.commit()
        raise


# ─── Manual save (paste response) ────────────────────────────────────────────

def _trigger_rebuild_batches(db: Session, project_id: int) -> None:
    """Sau khi Bible done: (1) sync đủ Characters từ Bible, (2) rebuild batches.

    Lazy import tránh circular dependency. Nuốt exception để không fail save.
    """
    try:
        master = get_master_bible_dict(db, project_id)
        if not master:
            return

        # 1. Sync đủ nhân vật từ Bible → Editor thấy đầy đủ 11 nhân vật
        from dubeditor.simple import service_characters
        result = service_characters.sync_characters_from_bible(db, project_id)
        logger.info(f"[bible] Synced characters for project {project_id}: {result}")

        # 2. Rebuild batches để translate prompt có MOVIE_BIBLE đầy đủ
        from dubeditor.simple import service_translate, service_config
        config = service_config.load_config(db, project_id)
        service_translate.rebuild_batches(db, project_id, config)
        logger.info(f"[bible] Auto-rebuilt batches for project {project_id} after Bible save")
    except Exception as e:
        logger.warning(f"[bible] trigger rebuild/sync failed: {e}")


def save_part_response(
    db: Session,
    part_id: int,
    response: str,
) -> SimpleBiblePart:
    """User paste response vào → validate + save."""
    part = db.query(SimpleBiblePart).filter(SimpleBiblePart.id == part_id).first()
    if not part:
        raise ValueError(f"Part {part_id} not found")

    # Validate parsing
    try:
        parsed = parse_bible_json(response)
    except ValueError as e:
        part.status = 'error'
        part.error_msg = f"Parse error: {e}"
        part.response = response  # giữ raw để user thấy
        db.commit()
        raise

    part.response = response
    part.status = 'done'
    part.characters_count = len(parsed.get('c', {}))
    part.error_msg = None
    part.saved_at = datetime.now(timezone.utc)
    db.commit()

    # Single mode → auto sync characters + rebuild batches
    project_id = part.project_id
    total = db.query(SimpleBiblePart).filter(
        SimpleBiblePart.project_id == project_id
    ).count()
    if total == 1:
        _trigger_rebuild_batches(db, project_id)

    return part


# ─── Merge ───────────────────────────────────────────────────────────────────

def _build_merge_prompt(parts: list[SimpleBiblePart]) -> str:
    """Build merge prompt từ các parts đã done."""
    template = load_prompt_template('bible_merge')

    blocks = []
    for p in parts:
        if not p.response:
            continue
        blocks.append(f"--- PART {p.part_index + 1} ---\n{p.response.strip()}\n")

    partials_text = '\n'.join(blocks)

    return fill_placeholders(template, {
        'PART_TOTAL': str(len(parts)),
        'PARTIAL_BIBLES': partials_text,
    })


async def run_bible_merge(
    db: Session,
    project_id: int,
    config: SimpleConfigSchema,
) -> SimpleBibleMerge:
    """Gọi LLM merge. Cần tất cả parts đã done."""
    parts = (
        db.query(SimpleBiblePart)
        .filter(SimpleBiblePart.project_id == project_id)
        .order_by(SimpleBiblePart.part_index)
        .all()
    )
    if not parts:
        raise ValueError("No parts to merge")
    if any(p.status != 'done' for p in parts):
        raise ValueError("Cannot merge: some parts are not done yet")

    merge = (
        db.query(SimpleBibleMerge)
        .filter(SimpleBibleMerge.project_id == project_id)
        .first()
    )
    if not merge:
        merge = SimpleBibleMerge(project_id=project_id)
        db.add(merge)

    # Build prompt
    merge.prompt = _build_merge_prompt(parts)
    merge.status = 'running'
    merge.error_msg = None
    db.commit()

    task_cfg = config.tasks.get('bible')
    api_key = getattr(config.api_keys, task_cfg.provider)

    try:
        resp = await run_llm_task(
            task='bible',
            prompt=merge.prompt,
            model=task_cfg.model,
            api_key=api_key,
            thinking=task_cfg.thinking,
        )

        parsed = parse_bible_json(resp.text)

        merge.response = resp.text
        merge.status = 'done'
        merge.master_bible_json = json.dumps(parsed, ensure_ascii=False)
        merge.master_characters_count = len(parsed.get('c', {}))
        merge.master_glossary_count = len(parsed.get('t', {}))
        merge.tokens_in = resp.tokens_in
        merge.tokens_out = resp.tokens_out
        merge.cost_usd = get_cost(resp)
        merge.model_used = task_cfg.model
        merge.saved_at = datetime.now(timezone.utc)
        db.commit()

        # Auto sync characters + rebuild batches
        _trigger_rebuild_batches(db, project_id)

        return merge

    except Exception as e:
        merge.status = 'error'
        merge.error_msg = str(e)[:500]
        db.commit()
        raise


def save_merge_response(
    db: Session,
    project_id: int,
    response: str,
) -> SimpleBibleMerge:
    """Manual save merge response."""
    merge = (
        db.query(SimpleBibleMerge)
        .filter(SimpleBibleMerge.project_id == project_id)
        .first()
    )
    if not merge:
        # Tạo nếu chưa có (edge case: user paste merge mà chưa run)
        # Đảm bảo đang ở multi mode
        parts_count = db.query(SimpleBiblePart).filter(
            SimpleBiblePart.project_id == project_id
        ).count()
        if parts_count < 2:
            raise ValueError("Cannot save merge in single mode")
        merge = SimpleBibleMerge(project_id=project_id)
        db.add(merge)

    try:
        parsed = parse_bible_json(response)
    except ValueError as e:
        merge.status = 'error'
        merge.error_msg = f"Parse error: {e}"
        merge.response = response
        db.commit()
        raise

    merge.response = response
    merge.status = 'done'
    merge.master_bible_json = json.dumps(parsed, ensure_ascii=False)
    merge.master_characters_count = len(parsed.get('c', {}))
    merge.master_glossary_count = len(parsed.get('t', {}))
    merge.error_msg = None
    merge.saved_at = datetime.now(timezone.utc)
    db.commit()

    # Auto sync characters + rebuild batches
    _trigger_rebuild_batches(db, project_id)

    return merge


# ─── Helper: lấy master Bible JSON dict ──────────────────────────────────────

def get_master_bible_dict(db: Session, project_id: int) -> Optional[dict]:
    """Lấy master Bible JSON dict (đã merge nếu multi, hoặc single part).

    Returns None nếu chưa có Bible nào.
    """
    parts = (
        db.query(SimpleBiblePart)
        .filter(SimpleBiblePart.project_id == project_id)
        .order_by(SimpleBiblePart.part_index)
        .all()
    )
    if not parts:
        return None

    if len(parts) == 1:
        # Single mode
        if parts[0].status != 'done' or not parts[0].response:
            return None
        try:
            return parse_bible_json(parts[0].response)
        except Exception:
            return None

    # Multi mode
    merge = (
        db.query(SimpleBibleMerge)
        .filter(SimpleBibleMerge.project_id == project_id)
        .first()
    )
    if not merge or merge.status != 'done' or not merge.master_bible_json:
        return None
    try:
        return json.loads(merge.master_bible_json)
    except Exception:
        return None
