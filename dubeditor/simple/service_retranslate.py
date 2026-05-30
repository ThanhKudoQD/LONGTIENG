"""
Retranslate batch service — dịch lại 1-5 dòng theo Simple Bible (mới).

Khác với pipeline cũ (translate.py):
- Dùng simple_bible_parts thay vì bảng `bibles` cũ.
- Tự đọc API key từ AppSetting (không cần FE gửi).
- Output cùng schema với pipeline cũ để FE re-use UI hiện tại.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import Project, Subtitle, AppSetting
from dubeditor.simple.llm_runner import run_llm_task
from dubeditor.simple.service_bible import get_master_bible_dict
from dubeditor.simple.service_utils import (
    extract_active_bible,
    format_context_previous,
    format_context_after,
    fill_placeholders,
    parse_translation_array,
)
from dubeditor.simple.service_characters import build_alias_map, resolve_speaker

logger = logging.getLogger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_api_key(db: Session, provider: str) -> str:
    """Lấy API key từ AppSetting theo provider."""
    key_name = {
        'gemini':   'api_key_gemini',
        'openai':   'api_key_openai',
        'deepseek': 'api_key_deepseek',
    }.get(provider, 'api_key_gemini')
    row = db.query(AppSetting).filter(AppSetting.key == key_name).first()
    return row.value if row and row.value else ''


def _load_prompt_template() -> str:
    """Đọc prompt translate_batch.txt (đã có sẵn cho pipeline simple)."""
    from pathlib import Path
    p = Path(__file__).parent / "prompts" / "translate_batch.txt"
    return p.read_text(encoding='utf-8')


def _format_line(s: Subtitle) -> str:
    """Format 1 subtitle line cho prompt."""
    zh = (s.original_text or '').replace('\n', ' ').strip()
    speaker = s.simple_speaker_zh or s.speaker_zh or '?'
    return f"[{s.index}] {speaker}: {zh}"


# ─── Main API ────────────────────────────────────────────────────────────────

async def retranslate_batch_simple(
    db: Session,
    project_id: int,
    subtitle_ids: list[int],
    hint: str = "",
    context_window: int = 2,
    provider: str = "gemini",
    model: str = "gemini-2.5-flash-lite",
    thinking: bool = False,
) -> dict:
    """Dịch lại 1-5 dòng dựa trên simple Bible.

    Returns:
        {
            'ok': True,
            'lines': [
                {
                    'line_index': int,        # subtitle.index
                    'subtitle_id': int,
                    'text_v1': str,           # bản dịch mới
                    'text_v2': None,          # không dùng v2 (giữ schema)
                    'emotion': None,
                    'intensity': None,
                    'current_text_v1': str,   # bản hiện tại (để FE so sánh)
                    'current_text_v2': None,
                }
            ],
            'tokens_in': int,
            'tokens_out': int,
        }
    """
    if not subtitle_ids:
        raise ValueError("subtitle_ids rỗng")
    if len(subtitle_ids) > 5:
        raise ValueError("Tối đa 5 dòng/lần (tránh prompt quá dài)")

    api_key = _load_api_key(db, provider)
    if not api_key:
        raise ValueError(
            f"Chưa cấu hình API key cho provider '{provider}'. "
            f"Vào Settings để cập nhật."
        )

    # Project + subtitles
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError(f"Project {project_id} not found")

    subs = db.query(Subtitle).filter(
        Subtitle.id.in_(subtitle_ids),
        Subtitle.project_id == project_id,
    ).order_by(Subtitle.index).all()
    if not subs:
        raise ValueError("Không tìm thấy subtitle nào")

    # Simple Bible
    master_bible = get_master_bible_dict(db, project_id)
    if not master_bible:
        raise ValueError("Project chưa có Simple Bible. Vào tab Bible để tạo.")

    # Active bible subset cho các speaker xuất hiện
    zh_texts = [s.original_text or '' for s in subs]
    active_bible = extract_active_bible(master_bible, zh_texts)
    active_bible_text = json.dumps(active_bible, ensure_ascii=False, indent=2)

    # Context window
    ctx_n = max(1, min(5, context_window or 2))
    min_idx = min(s.index for s in subs)
    max_idx = max(s.index for s in subs)

    ctx_before = db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.index < min_idx,
    ).order_by(Subtitle.index.desc()).limit(ctx_n).all()
    ctx_before = list(reversed(ctx_before))   # chronological

    ctx_after = db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.index > max_idx,
    ).order_by(Subtitle.index).limit(ctx_n).all()

    # Build prompt
    template = _load_prompt_template()
    previous_text = format_context_previous(ctx_before)
    after_text = format_context_after(ctx_after)
    current_text = "\n".join(_format_line(s) for s in subs)

    prompt = fill_placeholders(template, {
        'MOVIE_BIBLE':      active_bible_text,
        'PREVIOUS_CONTEXT': previous_text,
        'CURRENT_LINES':    current_text,
        'AFTER_CONTEXT':    after_text,
    })

    # Hint
    if hint and hint.strip():
        prompt += f"\n\nGỢI Ý TỪ USER:\n{hint.strip()}\n"

    # Call LLM
    logger.info(
        f"[retranslate-simple] project={project_id} subs={subtitle_ids} "
        f"provider={provider} model={model} prompt_len={len(prompt)}"
    )
    resp = await run_llm_task(
        task='translate',
        prompt=prompt,
        model=model,
        api_key=api_key,
        thinking=thinking,
        cached_prefix=active_bible_text,   # cache bible block
        timeout=180.0,
        max_retries=2,
    )

    # Parse response → list of (sub_idx, speaker, vi)
    try:
        entries = parse_translation_array(resp.text)
    except Exception as e:
        logger.error(f"[retranslate-simple] Parse failed: {e}\nRaw: {resp.text[:500]}")
        raise ValueError(f"Parse response lỗi: {e}")

    # Map sub_idx → entry
    entry_map = {sub_idx: (speaker, vi) for sub_idx, speaker, vi in entries}

    # Build response lines
    alias_map = build_alias_map(master_bible)
    out_lines = []
    for s in subs:
        if s.index in entry_map:
            speaker_zh, vi = entry_map[s.index]
        else:
            # LLM bỏ qua dòng này → giữ nguyên
            speaker_zh = s.simple_speaker_zh or s.speaker_zh or ''
            vi = s.simple_text_vi or s.text or ''
            logger.warning(
                f"[retranslate-simple] LLM bỏ qua sub_idx={s.index} "
                f"(không có trong response)"
            )

        out_lines.append({
            'line_index':       s.index,
            'subtitle_id':      s.id,
            'text_v1':          vi,
            'text_v2':          None,
            'emotion':          None,
            'intensity':        None,
            'current_text_v1':  s.text or '',
            'current_text_v2':  None,
            'speaker_zh':       speaker_zh,    # FE có thể dùng để hiển thị
        })

    return {
        'ok':         True,
        'lines':      out_lines,
        'tokens_in':  resp.tokens_in,
        'tokens_out': resp.tokens_out,
    }


def apply_retranslate_result(
    db: Session,
    project_id: int,
    subtitle_id: int,
    new_text: str,
    speaker_zh: Optional[str] = None,
) -> bool:
    """User chọn variant nào → apply vào DB.

    Update CẢ 2 cột:
    - subtitle.text (legacy — Editor cũ + TTS dùng)
    - subtitle.simple_text_vi (Simple pipeline)
    """
    sub = db.query(Subtitle).filter(
        Subtitle.id == subtitle_id,
        Subtitle.project_id == project_id,
    ).first()
    if not sub:
        return False

    sub.text = new_text
    sub.simple_text_vi = new_text
    sub.simple_status = 'translated'
    if speaker_zh:
        sub.simple_speaker_zh = speaker_zh
    db.commit()
    return True
