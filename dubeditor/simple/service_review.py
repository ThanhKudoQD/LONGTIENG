"""
Service AI Review (Bước IV) — clone luồng batch dịch.

Luồng:
  1. rebuild_review_groups: chia tất cả sub đã dịch thành review batch (size riêng)
  2. mỗi group → build prompt (zh + vi + speaker + Bible + context)
  3. run_review_group (Auto) hoặc save_group_response (paste) → gọi AI
  4. AI trả CHỈ các dòng cần sửa → lưu thành SimpleReviewSuggestion (pending)
  5. apply_suggestion / apply_all → cập nhật vào subtitle + sync editor

Tab Review hiển thị suggestions (zh | vi cũ→mới | speaker A→B | reason | apply).
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import Subtitle, Character
from dubeditor.simple.models import SimpleReviewGroup, SimpleReviewSuggestion
from dubeditor.simple.schemas import SimpleConfigSchema
from dubeditor.simple.service_utils import (
    load_prompt_template, fill_placeholders, extract_active_bible,
    estimate_tokens, SPECIAL_SPEAKERS,
)
from dubeditor.simple.service_bible import get_master_bible_dict
from dubeditor.simple.llm_runner import run_llm_task
from dubeditor.simple.service_config import load_config

logger = logging.getLogger(__name__)


# ─── Rebuild review groups (chia batch) ──────────────────────────────────────

def rebuild_review_groups(db: Session, project_id: int, config: SimpleConfigSchema) -> dict:
    """Chia tất cả sub ĐÃ DỊCH thành review batch theo review_batch_size."""
    # Xóa groups + suggestions cũ
    db.query(SimpleReviewSuggestion).filter(
        SimpleReviewSuggestion.project_id == project_id
    ).delete()
    db.query(SimpleReviewGroup).filter(
        SimpleReviewGroup.project_id == project_id
    ).delete()
    db.commit()

    subs = (
        db.query(Subtitle)
        .filter(
            Subtitle.project_id == project_id,
            Subtitle.simple_text_vi.isnot(None),
            Subtitle.simple_text_vi != '',
        )
        .order_by(Subtitle.index)
        .all()
    )
    if not subs:
        return {"groups": 0, "message": "Chưa có dòng nào đã dịch để review"}

    size = max(10, config.review_batch_size)
    master = get_master_bible_dict(db, project_id)
    template = load_prompt_template('review_batch')

    # Build index → sub map cho context
    all_subs = (
        db.query(Subtitle)
        .filter(Subtitle.project_id == project_id)
        .order_by(Subtitle.index)
        .all()
    )
    idx_to_sub = {s.index: s for s in all_subs}

    groups_created = 0
    group_idx = 0
    for i in range(0, len(subs), size):
        chunk = subs[i:i + size]
        range_start = chunk[0].index
        range_end = chunk[-1].index

        prompt, est_tok = _build_review_prompt(
            template, master, chunk, idx_to_sub, config.review_context_lines
        )

        group = SimpleReviewGroup(
            project_id=project_id,
            group_index=group_idx,
            sub_mode='ai_review',
            range_start=range_start,
            range_end=range_end,
            context_size_before=config.review_context_lines,
            context_size_after=config.review_context_lines,
            issue_ids_json='[]',
            prompt=prompt,
            status='idle',
            est_tokens=est_tok,
        )
        db.add(group)
        groups_created += 1
        group_idx += 1

    db.commit()
    return {"groups": groups_created}


def _build_review_prompt(template, master, chunk, idx_to_sub, ctx_lines) -> tuple[str, int]:
    """Build prompt review cho 1 group."""
    # Active bible (nhân vật xuất hiện trong chunk)
    zh_texts = [s.original_text or '' for s in chunk]
    active_bible = extract_active_bible(master or {}, zh_texts)
    bible_text = json.dumps(active_bible, ensure_ascii=False, indent=2)

    # Review lines: [id, speaker, zh, vi]
    review_lines = []
    for s in chunk:
        spk = (s.simple_speaker_zh or '').replace('"', '\\"')
        zh = (s.original_text or '').replace('"', '\\"')
        vi = (s.simple_text_vi or '').replace('"', '\\"')
        review_lines.append(f'[{s.index}, "{spk}", "{zh}", "{vi}"]')
    review_text = '[\n  ' + ',\n  '.join(review_lines) + '\n]' if review_lines else '[]'

    # Context trước/sau
    first_idx = chunk[0].index
    last_idx = chunk[-1].index
    prev_text = _format_context(idx_to_sub, first_idx - ctx_lines, first_idx - 1)
    after_text = _format_context(idx_to_sub, last_idx + 1, last_idx + ctx_lines)

    prompt = fill_placeholders(template, {
        'MOVIE_BIBLE': bible_text,
        'PREVIOUS_CONTEXT': prev_text,
        'REVIEW_LINES': review_text,
        'AFTER_CONTEXT': after_text,
    })
    return prompt, estimate_tokens(prompt)


def _format_context(idx_to_sub, lo, hi) -> str:
    """Format [id, speaker, vi] cho context (dùng vi nếu có, fallback zh)."""
    out = []
    for idx in range(max(0, lo), hi + 1):
        s = idx_to_sub.get(idx)
        if not s:
            continue
        spk = (s.simple_speaker_zh or '').replace('"', '\\"')
        vi = (s.simple_text_vi or '').strip()
        text = vi if vi else (s.original_text or '').strip()
        text = text.replace('"', '\\"')
        out.append(f'[{idx}, "{spk}", "{text}"]')
    if not out:
        return '[]'
    return '[\n  ' + ',\n  '.join(out) + '\n]'


# ─── Run / save response ──────────────────────────────────────────────────────

async def run_review_group(db: Session, group_id: int) -> SimpleReviewGroup:
    """Auto: gọi AI cho 1 review group."""
    group = db.query(SimpleReviewGroup).filter(SimpleReviewGroup.id == group_id).first()
    if not group:
        raise ValueError(f"Review group {group_id} not found")

    config = load_config(db, group.project_id)
    task_cfg = config.tasks.get('qa') or config.tasks.get('repair')
    if not task_cfg:
        raise ValueError("Missing 'qa' task config")
    api_key = config.api_keys.model_dump().get(task_cfg.provider)
    if not api_key:
        raise ValueError(f"Missing API key for '{task_cfg.provider}'")

    group.status = 'running'
    group.error_msg = None
    db.commit()

    try:
        resp = await run_llm_task(
            task='qa',
            prompt=group.prompt,
            model=task_cfg.model,
            api_key=api_key,
            thinking=task_cfg.thinking,
        )
        _txt = resp.text or ''
        logger.info(f"[simple.review {group.group_index}] response len={len(_txt)} "
                    f"tokens_out={resp.tokens_out}")

        group.response = resp.text
        group.tokens_in = resp.tokens_in
        group.tokens_out = resp.tokens_out
        group.cost_usd = _get_cost(resp)
        group.model_used = task_cfg.model
        db.commit()

        n = _apply_review_response(db, group.project_id, group.group_index, resp.text)

        group.status = 'done'
        group.saved_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"[simple.review {group.group_index}] {n} suggestions")
        return group

    except Exception as e:
        group.status = 'error'
        group.error_msg = str(e)[:500]
        db.commit()
        raise


def save_group_response(db: Session, group_id: int, response: str) -> SimpleReviewGroup:
    """Manual: user paste response."""
    group = db.query(SimpleReviewGroup).filter(SimpleReviewGroup.id == group_id).first()
    if not group:
        raise ValueError(f"Review group {group_id} not found")

    group.response = response
    try:
        n = _apply_review_response(db, group.project_id, group.group_index, response)
    except Exception as e:
        group.status = 'error'
        group.error_msg = f"Parse lỗi: {e}"[:500]
        db.commit()
        raise ValueError(f"Parse lỗi: {e}")

    group.status = 'done'
    group.saved_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(f"[simple.review {group.group_index}] {n} suggestions (manual)")
    return group


def _normalize_text(s: str) -> str:
    """Chuẩn hóa để so sánh ngữ nghĩa: bỏ dấu câu + khoảng trắng + lowercase.

    Dùng để phát hiện 2 bản dịch chỉ khác dấu câu/spacing (vô nghĩa).
    """
    import re
    if not s:
        return ''
    # Bỏ dấu câu phổ biến + gộp khoảng trắng + lowercase
    t = re.sub(r'[\s,.!?;:…"\'""\'\-–—()]+', '', s)
    return t.lower()


def _apply_review_response(db: Session, project_id: int, group_index: int, response: str) -> int:
    """Parse response → tạo SimpleReviewSuggestion (pending). Trả số suggestion."""
    fixes = _parse_review_fixes(response)

    # Xóa suggestions cũ của group này
    db.query(SimpleReviewSuggestion).filter(
        SimpleReviewSuggestion.project_id == project_id,
        SimpleReviewSuggestion.group_index == group_index,
    ).delete()

    count = 0
    for fix in fixes:
        sub = db.query(Subtitle).filter(
            Subtitle.project_id == project_id,
            Subtitle.index == fix['id'],
        ).first()
        if not sub:
            continue

        vi_old = sub.simple_text_vi or ''
        speaker_old = sub.simple_speaker_zh or ''
        vi_new = fix.get('vi', '').strip() or vi_old
        speaker_new = fix.get('speaker', '').strip()
        # speaker_new rỗng nghĩa là giữ nguyên (trừ khi AI chủ ý đổi thành "")
        if not speaker_new:
            speaker_new = speaker_old

        # Xác định loại thay đổi
        # Bỏ qua thay đổi vi chỉ khác dấu câu / khoảng trắng (ngữ nghĩa không đổi)
        vi_changed = vi_new != vi_old and _normalize_text(vi_new) != _normalize_text(vi_old)
        spk_changed = speaker_new != speaker_old
        if not vi_changed and not spk_changed:
            continue  # không có gì đổi (hoặc chỉ khác dấu câu) → bỏ
        # Nếu vi không đổi ngữ nghĩa → giữ vi_old (không lưu thay đổi vụn)
        if not vi_changed:
            vi_new = vi_old
        change_type = 'both' if (vi_changed and spk_changed) else ('speaker' if spk_changed else 'text')

        sugg = SimpleReviewSuggestion(
            project_id=project_id,
            group_index=group_index,
            subtitle_index=fix['id'],
            zh=sub.original_text or '',
            vi_old=vi_old,
            speaker_old=speaker_old,
            vi_new=vi_new,
            speaker_new=speaker_new,
            reason=fix.get('reason', ''),
            change_type=change_type,
            status='pending',
        )
        db.add(sugg)
        count += 1

    db.commit()
    return count


def _parse_review_fixes(response: str) -> list[dict]:
    """Parse response → list of {id, speaker, vi, reason}. Linh hoạt format."""
    from dubeditor.simple.service_utils import strip_markdown_wrapper
    import re

    if not response or not response.strip():
        return []
    cleaned = strip_markdown_wrapper(response)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []

    # Tìm array fixes
    fixes = None
    if isinstance(data, dict):
        for key in ('fixes', 'corrections', 'changes', 'result', 'data', 'items'):
            if isinstance(data.get(key), list):
                fixes = data[key]
                break
        if fixes is None:
            for v in data.values():
                if isinstance(v, list):
                    fixes = v
                    break
    elif isinstance(data, list):
        fixes = data

    if not fixes:
        return []

    out = []
    for f in fixes:
        if not isinstance(f, dict):
            continue
        fid = f.get('id', f.get('index'))
        if fid is None:
            continue
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            continue
        out.append({
            'id': fid,
            'speaker': str(f.get('speaker', '')).strip(),
            'vi': str(f.get('vi', f.get('text', ''))).strip(),
            'reason': str(f.get('reason', '')).strip(),
        })
    return out


# ─── Apply suggestions ────────────────────────────────────────────────────────

def apply_suggestion(db: Session, project_id: int, suggestion_id: int) -> dict:
    """Apply 1 suggestion vào subtitle."""
    sugg = db.query(SimpleReviewSuggestion).filter(
        SimpleReviewSuggestion.id == suggestion_id,
        SimpleReviewSuggestion.project_id == project_id,
    ).first()
    if not sugg:
        raise ValueError("Suggestion not found")

    _apply_one(db, project_id, sugg)
    db.commit()
    return {"applied": 1, "subtitle_index": sugg.subtitle_index}


def apply_all_suggestions(db: Session, project_id: int, group_index: Optional[int] = None) -> dict:
    """Apply tất cả suggestion pending (toàn project hoặc 1 group)."""
    q = db.query(SimpleReviewSuggestion).filter(
        SimpleReviewSuggestion.project_id == project_id,
        SimpleReviewSuggestion.status == 'pending',
    )
    if group_index is not None:
        q = q.filter(SimpleReviewSuggestion.group_index == group_index)

    suggs = q.all()
    for sugg in suggs:
        _apply_one(db, project_id, sugg)
    db.commit()
    return {"applied": len(suggs)}


def dismiss_suggestion(db: Session, project_id: int, suggestion_id: int) -> dict:
    """Bỏ qua 1 suggestion (không apply)."""
    sugg = db.query(SimpleReviewSuggestion).filter(
        SimpleReviewSuggestion.id == suggestion_id,
        SimpleReviewSuggestion.project_id == project_id,
    ).first()
    if not sugg:
        raise ValueError("Suggestion not found")
    sugg.status = 'dismissed'
    db.commit()
    return {"dismissed": 1}


def _apply_one(db: Session, project_id: int, sugg: SimpleReviewSuggestion) -> None:
    """Cập nhật subtitle theo suggestion + sync editor."""
    sub = db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.index == sugg.subtitle_index,
    ).first()
    if not sub:
        return

    if sugg.vi_new and sugg.vi_new != sub.simple_text_vi:
        sub.simple_text_vi = sugg.vi_new
        sub.text = sugg.vi_new   # sync legacy
    if sugg.speaker_new != (sub.simple_speaker_zh or ''):
        sub.simple_speaker_zh = sugg.speaker_new
        # Map character_id
        if sugg.speaker_new and sugg.speaker_new not in SPECIAL_SPEAKERS:
            char = db.query(Character).filter(
                Character.project_id == project_id,
                Character.name_zh == sugg.speaker_new,
            ).first()
            if char:
                sub.character_id = char.id

    sub.simple_status = 'fixed'
    sugg.status = 'applied'


# ─── State ────────────────────────────────────────────────────────────────────

def get_review_state(db: Session, project_id: int) -> dict:
    """Trả state cho FE tab Review."""
    config = load_config(db, project_id)
    groups = (
        db.query(SimpleReviewGroup)
        .filter(SimpleReviewGroup.project_id == project_id)
        .order_by(SimpleReviewGroup.group_index)
        .all()
    )
    suggs = (
        db.query(SimpleReviewSuggestion)
        .filter(SimpleReviewSuggestion.project_id == project_id)
        .order_by(SimpleReviewSuggestion.subtitle_index)
        .all()
    )

    return {
        "config": {"review_batch_size": config.review_batch_size,
                   "review_context_lines": config.review_context_lines},
        "groups": [{
            "id": g.id,
            "group_index": g.group_index,
            "range_start": g.range_start,
            "range_end": g.range_end,
            "prompt": g.prompt,
            "response": g.response,
            "status": g.status,
            "error_msg": g.error_msg,
            "est_tokens": g.est_tokens,
        } for g in groups],
        "suggestions": [{
            "id": s.id,
            "group_index": s.group_index,
            "subtitle_index": s.subtitle_index,
            "zh": s.zh,
            "vi_old": s.vi_old,
            "vi_new": s.vi_new,
            "speaker_old": s.speaker_old,
            "speaker_new": s.speaker_new,
            "reason": s.reason,
            "change_type": s.change_type,
            "status": s.status,
        } for s in suggs],
        "pending_count": sum(1 for s in suggs if s.status == 'pending'),
        "applied_count": sum(1 for s in suggs if s.status == 'applied'),
    }


def _get_cost(resp) -> float:
    try:
        from dubeditor.simple.llm_runner import estimate_cost
        return estimate_cost(resp)
    except Exception:
        return 0.0
