"""
Translate batch service — Bước II.

Functions:
  - rebuild_batches(db, project_id, config)         : chia SRT thành batches
  - get_translate_state(db, project_id, config)     : load state cho FE
  - run_batch(db, batch_id, config)                 : gọi LLM dịch 1 batch
  - save_batch_response(db, batch_id, response)     : manual save
  - run_from(db, project_id, from_idx, config)      : chạy nhiều batch (normal hoặc turbo)
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import Subtitle
from dubeditor.simple.models import SimpleBatch
from dubeditor.simple.schemas import SimpleConfigSchema
from dubeditor.simple.llm_runner import run_llm_task, get_cost
from dubeditor.simple.service_utils import (
    load_prompt_template,
    fill_placeholders,
    format_lines_for_translate_prompt,
    format_context_previous,
    format_context_after,
    parse_translation_array,
    extract_active_bible,
    estimate_tokens,
    SPECIAL_SPEAKERS,
)
from dubeditor.simple.service_bible import get_master_bible_dict

logger = logging.getLogger(__name__)


# ─── Rebuild batches ─────────────────────────────────────────────────────────

def rebuild_batches(
    db: Session,
    project_id: int,
    config: SimpleConfigSchema,
) -> None:
    """Xóa batches cũ, chia lại SRT thành batches theo config.

    Algorithm:
      - Lướt qua subtitles theo index
      - Mỗi khi đạt batch_size_target dòng, tìm gap ≥ gap_threshold_seconds
        trong khoảng next 20 dòng để cắt
      - Nếu không tìm được trong window, hard cut tại batch_size_max
    """
    # Xóa cũ
    db.query(SimpleBatch).filter(SimpleBatch.project_id == project_id).delete()
    db.commit()

    subtitles = (
        db.query(Subtitle)
        .filter(Subtitle.project_id == project_id)
        .order_by(Subtitle.index)
        .all()
    )
    if not subtitles:
        return

    target = config.batch_size_target
    hard_max = config.batch_size_max
    gap_thresh = config.gap_threshold_seconds

    # Cắt batches
    batches_idx_ranges: list[tuple[int, int]] = []   # (cursor_start, cursor_end) — index trong list
    cursor = 0
    n = len(subtitles)

    while cursor < n:
        # Lý tưởng: cursor + target
        ideal_end = cursor + target
        if ideal_end >= n:
            # Last batch
            batches_idx_ranges.append((cursor, n))
            cursor = n
            break

        # Tìm gap trong window [cursor + target, cursor + hard_max]
        window_end = min(n - 1, cursor + hard_max)
        cut = None
        for i in range(ideal_end, window_end):
            gap = subtitles[i + 1].start_time - subtitles[i].end_time
            if gap >= gap_thresh:
                cut = i + 1
                break

        if cut is None:
            cut = min(n, cursor + hard_max)

        batches_idx_ranges.append((cursor, cut))
        cursor = cut

    # Build prompt template cached
    template = load_prompt_template('translate_batch')

    # Load master Bible để dùng ngay
    master = get_master_bible_dict(db, project_id)

    # Tạo batches records (prompt sẽ build lazy khi run hoặc khi FE GET)
    for batch_idx, (lo, hi) in enumerate(batches_idx_ranges):
        slice_ = subtitles[lo:hi]
        line_count = len(slice_)
        start_line = slice_[0].index
        end_line = slice_[-1].index

        # Build prompt
        prompt, cached_tok, var_tok, chars_in_batch = _build_batch_prompt(
            template=template,
            master_bible=master,
            current_subs=slice_,
            previous_subs=_get_previous_context(
                subtitles, lo, config.previous_context_lines
            ),
            after_subs=_get_after_context(
                subtitles, hi, config.previous_context_lines
            ),
            genre=master.get('genre', 'phim Trung Quốc') if master else 'phim Trung Quốc',
        )

        b = SimpleBatch(
            project_id=project_id,
            batch_index=batch_idx,
            start_line=start_line,
            end_line=end_line,
            line_count=line_count,
            characters_in_batch=chars_in_batch,
            est_tokens_cached=cached_tok,
            est_tokens_variable=var_tok,
            prompt=prompt,
            status='idle',
        )
        db.add(b)

    db.commit()


def _get_previous_context(
    all_subs: list,
    current_lo: int,
    context_lines: int,
) -> list:
    """Lấy N dòng cuối của batch trước (để giữ continuity).

    Trả về tất cả dòng trong khoảng (không filter theo đã dịch hay chưa).
    format_context_previous() sẽ tự fallback: dùng vi nếu có, không thì zh.
    """
    if current_lo == 0 or context_lines <= 0:
        return []
    start = max(0, current_lo - context_lines)
    return list(all_subs[start:current_lo])


def _get_after_context(
    all_subs: list,
    current_hi: int,
    context_lines: int,
) -> list:
    """Lấy N dòng đầu của batch sau (context tương lai, để hiểu hội thoại tiếp).

    Dùng zh (chưa dịch). Giúp LLM hiểu câu hiện tại dẫn tới đâu.
    """
    if context_lines <= 0 or current_hi >= len(all_subs):
        return []
    end = min(len(all_subs), current_hi + context_lines)
    return list(all_subs[current_hi:end])


def _build_batch_prompt(
    template: str,
    master_bible: Optional[dict],
    current_subs: list,
    previous_subs: list,
    genre: str,
    after_subs: Optional[list] = None,
) -> tuple[str, int, int, int]:
    """Build batch prompt. Trả (prompt, cached_tokens, variable_tokens, chars_in_batch).

    Cached layer = MOVIE_BIBLE subset (giống nhau qua các batch nếu Bible không đổi
    + nhiều nhân vật chung). Variable layer = previous_context + current_lines + after_context.
    """
    # Detect chars in batch
    zh_texts = [s.original_text or '' for s in current_subs]
    active_bible = extract_active_bible(master_bible or {}, zh_texts)
    chars_in_batch = len(active_bible.get('c', {}))

    active_bible_text = json.dumps(active_bible, ensure_ascii=False, indent=2)
    previous_text = format_context_previous(previous_subs)
    current_text = format_lines_for_translate_prompt(current_subs)
    after_text = format_context_after(after_subs or [])

    # Prompt dùng các placeholder: MOVIE_BIBLE, PREVIOUS_CONTEXT, CURRENT_LINES, AFTER_CONTEXT.
    # fill_placeholders accept cả {KEY} và {{KEY}}.
    prompt = fill_placeholders(template, {
        'MOVIE_BIBLE': active_bible_text,
        'PREVIOUS_CONTEXT': previous_text,
        'CURRENT_LINES': current_text,
        'AFTER_CONTEXT': after_text,
    })

    # Estimate tokens (cached = MOVIE_BIBLE; variable = rest)
    cached_tok = estimate_tokens(active_bible_text)
    var_tok = estimate_tokens(prompt) - cached_tok

    return prompt, cached_tok, max(0, var_tok), chars_in_batch


# ─── Get state ───────────────────────────────────────────────────────────────

def get_translate_state(
    db: Session,
    project_id: int,
    config: SimpleConfigSchema,
) -> dict:
    """Load full state cho FE."""
    batches = (
        db.query(SimpleBatch)
        .filter(SimpleBatch.project_id == project_id)
        .order_by(SimpleBatch.batch_index)
        .all()
    )

    batches_out = []
    cost_total = 0.0
    translated_count = 0
    pending_count = 0

    for b in batches:
        batches_out.append({
            'index': b.batch_index,
            'total': len(batches),
            'start_line': b.start_line,
            'end_line': b.end_line,
            'line_count': b.line_count,
            'characters_in_batch': b.characters_in_batch,
            'est_tokens_cached': b.est_tokens_cached,
            'est_tokens_variable': b.est_tokens_variable,
            'prompt': b.prompt or '',
            'response': b.response,
            'status': b.status,
            'saved_at': b.saved_at,
            'error_msg': b.error_msg,
            'unknown_ratio': b.unknown_ratio_percent,
        })
        cost_total += b.cost_usd or 0.0

    # Đếm translated / pending từ subtitles
    total_subs = db.query(Subtitle).filter(Subtitle.project_id == project_id).count()
    translated_count = db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.simple_text_vi.isnot(None),
        Subtitle.simple_text_vi != '',
    ).count()
    pending_count = total_subs - translated_count

    return {
        'config': {
            'batch_size_target': config.batch_size_target,
            'batch_size_max': config.batch_size_max,
            'gap_threshold_seconds': config.gap_threshold_seconds,
            'concurrency_mode': config.concurrency_mode,
            'turbo_concurrency': config.turbo_concurrency,
            'previous_context_lines': config.previous_context_lines,
        },
        'batches': batches_out,
        'active_batch_index': 0,   # FE tự quản lý, BE không lưu
        'total_translated': translated_count,
        'total_pending': pending_count,
        'cost_so_far_usd': round(cost_total, 4),
    }


# ─── Run a batch ─────────────────────────────────────────────────────────────

async def run_batch(
    db: Session,
    batch_id: int,
    config: SimpleConfigSchema,
) -> SimpleBatch:
    """Gọi LLM dịch 1 batch. Update Subtitle + Batch trong DB."""
    batch = db.query(SimpleBatch).filter(SimpleBatch.id == batch_id).first()
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    task_cfg = config.tasks.get('translate')
    if not task_cfg:
        raise ValueError("Missing 'translate' task config")

    api_key = getattr(config.api_keys, task_cfg.provider)
    if not api_key:
        raise ValueError(f"Missing API key for '{task_cfg.provider}'")

    batch.status = 'running'
    batch.error_msg = None
    db.commit()

    try:
        resp = await run_llm_task(
            task='translate',
            prompt=batch.prompt,
            model=task_cfg.model,
            api_key=api_key,
            thinking=task_cfg.thinking,
        )

        # Log response để debug (500 ký tự đầu + cuối)
        _txt = resp.text or ''
        logger.info(
            f"[simple.batch {batch.batch_index}] LLM response "
            f"len={len(_txt)} tokens_out={resp.tokens_out}\n"
            f"  HEAD: {_txt[:500]!r}\n"
            f"  TAIL: {_txt[-300:]!r}"
        )

        # Luôn lưu raw response TRƯỚC khi parse (để xem được trên FE kể cả khi parse lỗi)
        batch.response = resp.text
        batch.tokens_in = resp.tokens_in
        batch.tokens_out = resp.tokens_out
        batch.cached_tokens = resp.cached_tokens
        batch.cost_usd = get_cost(resp)
        batch.model_used = task_cfg.model
        db.commit()

        # Parse + apply to subtitles
        try:
            applied, unknown_ratio = _apply_translation_response(
                db, batch.project_id, resp.text
            )
        except Exception as parse_err:
            logger.error(
                f"[simple.batch {batch.batch_index}] PARSE FAILED: {parse_err}\n"
                f"  Full response: {_txt!r}"
            )
            batch.status = 'error'
            batch.error_msg = f"Parse lỗi: {parse_err}"[:500]
            db.commit()
            raise ValueError(f"Parse response lỗi: {parse_err}")

        batch.status = 'done'
        batch.unknown_ratio_percent = unknown_ratio
        batch.saved_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            f"[simple.batch {batch.batch_index}] Applied {applied} lines, "
            f"unknown {unknown_ratio:.1f}%"
        )

        return batch

    except Exception as e:
        batch.status = 'error'
        batch.error_msg = str(e)[:500]
        db.commit()
        raise


def save_batch_response(
    db: Session,
    batch_id: int,
    response: str,
) -> SimpleBatch:
    """Manual save batch response (user paste)."""
    batch = db.query(SimpleBatch).filter(SimpleBatch.id == batch_id).first()
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    try:
        applied, unknown_ratio = _apply_translation_response(
            db, batch.project_id, response
        )
    except ValueError as e:
        batch.status = 'error'
        batch.error_msg = f"Parse error: {e}"
        batch.response = response
        db.commit()
        raise

    batch.response = response
    batch.status = 'done'
    batch.unknown_ratio_percent = unknown_ratio
    batch.error_msg = None
    batch.saved_at = datetime.now(timezone.utc)
    db.commit()
    return batch


def _build_speaker_to_charid(db: Session, project_id: int, master_bible) -> dict[str, int]:
    """Build map: speaker_zh (tên chính HOẶC alias) → character_id.

    1. Sync đủ nhân vật từ Bible (tạo nếu chưa có)
    2. Build alias_map từ Bible
    3. Map cả tên chính + alias → character_id của nhân vật đó
    """
    from dubeditor.models import Character
    from dubeditor.simple.service_characters import (
        sync_characters_from_bible, build_alias_map,
    )

    # Đảm bảo đủ nhân vật trong DB
    sync_characters_from_bible(db, project_id)

    # name_zh → character_id
    chars = db.query(Character).filter(
        Character.project_id == project_id,
        Character.name_zh.isnot(None),
    ).all()
    canon_to_id = {c.name_zh: c.id for c in chars}

    # alias → canonical name_zh
    alias_map = build_alias_map(master_bible)

    # Build full map: mọi key (tên chính + alias) → character_id
    speaker_to_id: dict[str, int] = {}
    for key, canon in alias_map.items():
        cid = canon_to_id.get(canon)
        if cid:
            speaker_to_id[key] = cid
    # Đảm bảo tên chính cũng có
    for canon, cid in canon_to_id.items():
        speaker_to_id.setdefault(canon, cid)

    return speaker_to_id


def _apply_translation_response(
    db: Session,
    project_id: int,
    response: str,
) -> tuple[int, float]:
    """Parse response + apply vào subtitles. Trả (applied_count, unknown_ratio_%)."""
    entries = parse_translation_array(response)

    applied = 0
    unknown_count = 0

    # Build speaker → character_id map (resolve alias)
    master = get_master_bible_dict(db, project_id)
    speaker_to_id = _build_speaker_to_charid(db, project_id, master)
    # alias → canonical để lưu speaker_zh chuẩn
    from dubeditor.simple.service_characters import build_alias_map, resolve_speaker
    alias_map = build_alias_map(master)

    for sub_id, speaker_zh, vi in entries:
        sub = db.query(Subtitle).filter(
            Subtitle.project_id == project_id,
            Subtitle.index == sub_id,
        ).first()
        if not sub:
            logger.warning(f"Subtitle index={sub_id} not found in project {project_id}")
            continue

        # Speaker: nếu là UNKNOWN hoặc rỗng → lưu "" (rỗng) theo yêu cầu.
        # Special speakers khác (CROWD/NARRATOR...) giữ nguyên.
        is_unknown = (not speaker_zh) or speaker_zh == 'UNKNOWN'
        is_special = speaker_zh in ('CROWD', 'NARRATOR', 'OFF_SCREEN', 'PHONE')

        if is_unknown:
            stored_speaker = ''
        elif is_special:
            stored_speaker = speaker_zh
        else:
            # Resolve alias → tên chính (vd 小寒 → 颜寒)
            stored_speaker = resolve_speaker(speaker_zh, alias_map)

        sub.simple_speaker_zh = stored_speaker
        sub.simple_text_vi = vi
        sub.simple_status = 'translated'
        # Sync sang cột `text` legacy để Editor cũ + TTS pipeline đọc được.
        if vi:
            sub.text = vi
        # Map character_id qua speaker_to_id (đã resolve alias + sync Bible)
        if stored_speaker and not is_special:
            # thử cả speaker gốc (LLM trả) và stored (đã resolve)
            cid = speaker_to_id.get(speaker_zh) or speaker_to_id.get(stored_speaker)
            if cid:
                sub.character_id = cid
        applied += 1

        if is_unknown:
            unknown_count += 1

    db.commit()

    unknown_ratio = (unknown_count / applied * 100.0) if applied else 0.0
    return applied, unknown_ratio


# ─── Run multiple batches ────────────────────────────────────────────────────

async def run_from(
    db: Session,
    project_id: int,
    from_batch_idx: int,
    config: SimpleConfigSchema,
    only_idle: bool = True,
) -> dict:
    """Chạy nhiều batches từ batch from_batch_idx đến hết.

    - concurrency_mode=normal: tuần tự (dùng context VI đã dịch)
    - concurrency_mode=turbo: song song N batches (dùng context ZH, không cần đợi)

    Returns: {"ran": N, "ok": K, "errors": [...]}.
    """
    batches = (
        db.query(SimpleBatch)
        .filter(
            SimpleBatch.project_id == project_id,
            SimpleBatch.batch_index >= from_batch_idx,
        )
        .order_by(SimpleBatch.batch_index)
        .all()
    )

    if only_idle:
        batches = [b for b in batches if b.status == 'idle']

    if not batches:
        return {"ran": 0, "ok": 0, "errors": []}

    ok = 0
    errors = []

    if config.concurrency_mode == 'turbo':
        # Song song với concurrency limit
        sem = asyncio.Semaphore(config.turbo_concurrency)

        async def _one(batch):
            async with sem:
                try:
                    await run_batch(db, batch.id, config)
                    return None
                except Exception as e:
                    return (batch.batch_index, str(e))

        results = await asyncio.gather(*[_one(b) for b in batches])
        for r in results:
            if r is None:
                ok += 1
            else:
                errors.append({"batch_index": r[0], "error": r[1]})
    else:
        # Tuần tự — sau mỗi batch, rebuild prompt next vì previous_context thay đổi
        for batch in batches:
            try:
                # Rebuild prompt với context mới
                await _rebuild_batch_prompt(db, batch.id, config)
                await run_batch(db, batch.id, config)
                ok += 1
            except Exception as e:
                errors.append({"batch_index": batch.batch_index, "error": str(e)})
                # Continue dù lỗi 1 batch

    return {"ran": len(batches), "ok": ok, "errors": errors}


async def _rebuild_batch_prompt(
    db: Session,
    batch_id: int,
    config: SimpleConfigSchema,
) -> None:
    """Rebuild prompt 1 batch với context VI mới nhất.

    Dùng cho Normal mode khi chạy tuần tự.
    """
    batch = db.query(SimpleBatch).filter(SimpleBatch.id == batch_id).first()
    if not batch:
        return

    subtitles = (
        db.query(Subtitle)
        .filter(Subtitle.project_id == batch.project_id)
        .order_by(Subtitle.index)
        .all()
    )
    # Find lo / hi
    lo = next((i for i, s in enumerate(subtitles) if s.index == batch.start_line), None)
    hi = next((i + 1 for i, s in enumerate(subtitles) if s.index == batch.end_line), None)
    if lo is None or hi is None:
        return

    master = get_master_bible_dict(db, batch.project_id)
    template = load_prompt_template('translate_batch')

    prompt, cached_tok, var_tok, chars_in_batch = _build_batch_prompt(
        template=template,
        master_bible=master,
        current_subs=subtitles[lo:hi],
        previous_subs=_get_previous_context(subtitles, lo, config.previous_context_lines),
        after_subs=_get_after_context(subtitles, hi, config.previous_context_lines),
        genre=master.get('genre', 'phim Trung Quốc') if master else 'phim Trung Quốc',
    )

    batch.prompt = prompt
    batch.characters_in_batch = chars_in_batch
    batch.est_tokens_cached = cached_tok
    batch.est_tokens_variable = var_tok
    db.commit()


def reset_batch(db: Session, batch_id: int) -> None:
    """Reset batch về idle (xóa response, clear translated subtitles)."""
    batch = db.query(SimpleBatch).filter(SimpleBatch.id == batch_id).first()
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    # Clear translation cho subtitles trong batch range
    db.query(Subtitle).filter(
        Subtitle.project_id == batch.project_id,
        Subtitle.index >= batch.start_line,
        Subtitle.index <= batch.end_line,
    ).update({
        'simple_speaker_zh': None,
        'simple_text_vi': None,
        'simple_status': 'pending',
    })

    batch.response = None
    batch.status = 'idle'
    batch.error_msg = None
    batch.tokens_in = 0
    batch.tokens_out = 0
    batch.cached_tokens = 0
    batch.cost_usd = 0.0
    batch.saved_at = None
    batch.unknown_ratio_percent = 0.0
    db.commit()
