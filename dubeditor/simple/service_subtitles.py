"""
Service cho tab Phụ đề (Simple pipeline).

Functions:
  - list_subtitles_with_notes(db, project_id)   : list subtitles + error notes
  - patch_subtitle(db, project_id, index, ...)  : sửa speaker + vi 1 dòng, sync legacy
  - scan_errors_for_view(db, project_id, config): quét lỗi → gắn notes vào subtitle

Notes (ghi chú) = error_types từ SimpleIssue (status pending/still_broken) của dòng đó.
Chỉ refresh khi user bấm "Quét lỗi" (không tự động).
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import Subtitle, Character
from dubeditor.simple.models import SimpleIssue, SimpleBatch
from dubeditor.simple.schemas import SimpleConfigSchema
from dubeditor.simple.service_utils import (
    has_chinese_chars, is_valid_speaker, calculate_cps, SPECIAL_SPEAKERS,
)
from dubeditor.simple.service_bible import get_master_bible_dict

logger = logging.getLogger(__name__)


# Mapping error type → label tiếng Việt (cho cột ghi chú)
ERROR_LABELS = {
    'json_parse':        'JSON lỗi',
    'missing_id':        'Thiếu dòng',
    'extra_id':          'Dòng thừa',
    'invalid_speaker':   'Speaker sai',
    'chinese_remained':  'Còn tiếng Trung',
    'cps_exceeded':      'Quá dài (CPS)',
    'empty':             'Rỗng',
    'unnatural_pronoun': 'Xưng hô lạ',
}


def list_subtitles_with_notes(db: Session, project_id: int) -> list[dict]:
    """List tất cả subtitles kèm error notes (từ SimpleIssue chưa resolved).

    notes = list các {type, label, severity} cho dòng đó.
    """
    subs = (
        db.query(Subtitle)
        .filter(Subtitle.project_id == project_id)
        .order_by(Subtitle.index)
        .all()
    )

    # Build map subtitle_index → list error types (từ issue pending/still_broken)
    issues = (
        db.query(SimpleIssue)
        .filter(
            SimpleIssue.project_id == project_id,
            SimpleIssue.status.in_(('pending', 'still_broken')),
        )
        .all()
    )
    idx_to_notes: dict[int, list] = {}
    for iss in issues:
        try:
            types = json.loads(iss.error_types_json or '[]')
        except Exception:
            types = []
        notes = [
            {'type': t, 'label': ERROR_LABELS.get(t, t), 'severity': iss.severity}
            for t in types
        ]
        idx_to_notes.setdefault(iss.subtitle_index, []).extend(notes)

    # Build map index → batch_index
    batches = db.query(SimpleBatch).filter(
        SimpleBatch.project_id == project_id
    ).all()
    idx_to_batch: dict[int, int] = {}
    for b in batches:
        for i in range(b.start_line, b.end_line + 1):
            idx_to_batch[i] = b.batch_index

    out = []
    for s in subs:
        notes = idx_to_notes.get(s.index, [])
        out.append({
            'id': s.id,
            'index': s.index,
            'start_time': s.start_time,
            'end_time': s.end_time,
            'original_text': s.original_text or '',
            # CHỈ trả vi nếu thực sự đã dịch (simple_text_vi), KHÔNG fallback text legacy
            'simple_text_vi': s.simple_text_vi,
            'simple_speaker_zh': s.simple_speaker_zh,
            'simple_status': s.simple_status or 'pending',
            'batch_index': idx_to_batch.get(s.index),
            'notes': notes,
            'has_issue': len(notes) > 0,
        })
    return out


def patch_subtitle(
    db: Session,
    project_id: int,
    index: int,
    *,
    simple_text_vi: Optional[str] = None,
    simple_speaker_zh: Optional[str] = None,
) -> dict:
    """Sửa 1 dòng phụ đề. Sync sang text legacy + character_id.

    Trả về dict subtitle đã update.
    """
    sub = (
        db.query(Subtitle)
        .filter(
            Subtitle.project_id == project_id,
            Subtitle.index == index,
        )
        .first()
    )
    if not sub:
        raise ValueError(f"Subtitle index={index} not found")

    if simple_text_vi is not None:
        sub.simple_text_vi = simple_text_vi
        # Sync sang text legacy cho Editor cũ
        sub.text = simple_text_vi
        # Recompute CPS
        duration = max(0.01, (sub.end_time or 0) - (sub.start_time or 0))
        sub.cps_value = len(simple_text_vi.strip()) / duration if simple_text_vi else None

    if simple_speaker_zh is not None:
        sub.simple_speaker_zh = simple_speaker_zh
        # Map speaker → character_id
        if simple_speaker_zh and simple_speaker_zh not in SPECIAL_SPEAKERS:
            char = db.query(Character).filter(
                Character.project_id == project_id,
                Character.name_zh == simple_speaker_zh,
            ).first()
            if char:
                sub.character_id = char.id

    # Nếu dòng đã có vi → mark translated (nếu đang pending)
    if sub.simple_text_vi and sub.simple_status == 'pending':
        sub.simple_status = 'translated'

    db.commit()

    return {
        'id': sub.id,
        'index': sub.index,
        'simple_text_vi': sub.simple_text_vi,
        'simple_speaker_zh': sub.simple_speaker_zh,
        'simple_status': sub.simple_status,
    }


def scan_errors_for_view(
    db: Session,
    project_id: int,
    config: SimpleConfigSchema,
) -> dict:
    """Quét lỗi code-based cho TẤT CẢ dòng đã dịch → tạo/update SimpleIssue.

    Khác với filter.scan_all_errors: hàm này tập trung cho tab Phụ đề,
    chỉ quét per-line errors (không check missing/extra id giữa batch).

    Trả về {scanned, errors_found, by_type}.
    """
    master = get_master_bible_dict(db, project_id)

    subs = (
        db.query(Subtitle)
        .filter(
            Subtitle.project_id == project_id,
            Subtitle.simple_text_vi.isnot(None),
            Subtitle.simple_text_vi != '',
        )
        .all()
    )

    # Build index → batch
    batches = db.query(SimpleBatch).filter(
        SimpleBatch.project_id == project_id
    ).all()
    idx_to_batch: dict[int, int] = {}
    for b in batches:
        for i in range(b.start_line, b.end_line + 1):
            idx_to_batch[i] = b.batch_index

    by_type = {
        'invalid_speaker': 0, 'chinese_remained': 0,
        'cps_exceeded': 0, 'empty': 0,
    }
    errors_found = 0

    # Xóa các pending issue cũ (chỉ những loại per-line) để refresh
    db.query(SimpleIssue).filter(
        SimpleIssue.project_id == project_id,
        SimpleIssue.status == 'pending',
    ).delete()
    db.commit()

    for sub in subs:
        vi = sub.simple_text_vi or ''
        speaker = sub.simple_speaker_zh or ''
        errors_for_sub: list[str] = []
        severity = 'warning'
        cps_value = None

        if not vi.strip():
            errors_for_sub.append('empty')
            by_type['empty'] += 1
            severity = 'error'

        if has_chinese_chars(vi):
            errors_for_sub.append('chinese_remained')
            by_type['chinese_remained'] += 1
            severity = 'error'

        if speaker and speaker not in SPECIAL_SPEAKERS and master:
            if not is_valid_speaker(speaker, master):
                errors_for_sub.append('invalid_speaker')
                by_type['invalid_speaker'] += 1
                severity = 'error'

        if vi:
            duration = (sub.end_time or 0) - (sub.start_time or 0)
            cps = calculate_cps(vi, duration, config.cps_max_chars_fallback)
            if cps > config.cps_max:
                cps_value = cps
                errors_for_sub.append('cps_exceeded')
                by_type['cps_exceeded'] += 1

        if errors_for_sub:
            errors_found += 1
            issue = SimpleIssue(
                project_id=project_id,
                subtitle_id=sub.id,
                subtitle_index=sub.index,
                batch_index=idx_to_batch.get(sub.index, 0),
                error_types_json=json.dumps(errors_for_sub),
                severity=severity,
                zh=sub.original_text or '',
                text_before=sub.simple_text_vi,
                speaker_before=sub.simple_speaker_zh,
                cps_value=cps_value,
                attempts_json='[]',
                fix_attempt=0,
                status='pending',
            )
            db.add(issue)
            sub.simple_status = 'has_error'
        else:
            if sub.simple_status == 'has_error':
                sub.simple_status = 'translated'

    db.commit()

    return {
        'scanned': len(subs),
        'errors_found': errors_found,
        'by_type': by_type,
    }
