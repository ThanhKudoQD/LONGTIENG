"""
Filter service — Bước III.

Code-based validation (KHÔNG dùng AI). 8 loại lỗi:
  1. json_parse        — không parse được response (lưu ở batch.error_msg, không tạo issue)
  2. missing_id        — batch trả thiếu dòng id nào đó
  3. extra_id          — batch trả id không có trong batch (rare)
  4. invalid_speaker   — speaker không có trong Bible.c (và không phải special)
  5. chinese_remained  — vi còn ký tự Trung
  6. cps_exceeded      — characters per second vượt threshold
  7. empty             — vi rỗng
  8. unnatural_pronoun — heuristic (tạm bỏ vì cần AI để detect tốt)

Auto-fix lỗi format trước khi flag:
  - whitespace
  - dấu câu Trung → Việt
  - markdown wrapper rồi rerun parse
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import Subtitle
from dubeditor.simple.models import SimpleBatch, SimpleIssue
from dubeditor.simple.schemas import SimpleConfigSchema
from dubeditor.simple.service_utils import (
    has_chinese_chars,
    is_valid_speaker,
    calculate_cps,
    auto_fix_text,
    SPECIAL_SPEAKERS,
)
from dubeditor.simple.service_bible import get_master_bible_dict

logger = logging.getLogger(__name__)


# ─── Scan ────────────────────────────────────────────────────────────────────

def scan_all_errors(
    db: Session,
    project_id: int,
    config: SimpleConfigSchema,
    auto_fix: bool = True,
) -> dict:
    """Quét toàn bộ subtitles + batches, tìm 8 loại lỗi.

    Steps:
      1. Auto-fix dễ (whitespace, dấu câu) → update DB
      2. Re-check toàn bộ → tạo / update SimpleIssue records cho lỗi còn lại
      3. Trả stats + list errors

    Returns:
        {
          "stats": FilterStats,
          "errors": [...],
          "auto_fixed_count": N,
        }
    """
    master = get_master_bible_dict(db, project_id)

    # Load tất cả subtitles có translation
    subtitles = (
        db.query(Subtitle)
        .filter(
            Subtitle.project_id == project_id,
            Subtitle.simple_text_vi.isnot(None),
        )
        .order_by(Subtitle.index)
        .all()
    )

    # Build map: subtitle.index → batch_index (để FE filter)
    batches = (
        db.query(SimpleBatch)
        .filter(SimpleBatch.project_id == project_id)
        .all()
    )
    index_to_batch: dict[int, int] = {}
    for b in batches:
        for i in range(b.start_line, b.end_line + 1):
            index_to_batch[i] = b.batch_index

    # ─── Auto-fix ───────────────────────────────────────────────────────────
    auto_fixed_count = 0
    if auto_fix:
        for sub in subtitles:
            new_text, applied = auto_fix_text(sub.simple_text_vi or '')
            if applied:
                sub.simple_text_vi = new_text
                auto_fixed_count += 1
        db.commit()

    # ─── Detect errors ──────────────────────────────────────────────────────
    stats = {
        'json_parse': 0, 'missing_id': 0, 'extra_id': 0,
        'invalid_speaker': 0, 'chinese_remained': 0,
        'cps_exceeded': 0, 'empty': 0,
        'total': 0,
    }

    # JSON parse errors (lưu trên batch)
    for b in batches:
        if b.status == 'error' and b.error_msg and 'parse' in b.error_msg.lower():
            stats['json_parse'] += 1

    # Detect missing/extra IDs
    for b in batches:
        if b.status != 'done':
            continue
        if not b.response:
            continue
        try:
            from dubeditor.simple.service_utils import parse_translation_array
            entries = parse_translation_array(b.response)
            response_ids = {e[0] for e in entries}
        except Exception:
            continue

        expected_ids = set(range(b.start_line, b.end_line + 1))
        # Restrict to subtitles thực sự tồn tại trong batch
        actual_subs_ids = {
            s.index for s in subtitles
            if b.start_line <= s.index <= b.end_line
        }
        expected_ids = expected_ids & {s.index for s in subtitles}

        missing = expected_ids - response_ids
        extra = response_ids - expected_ids
        stats['missing_id'] += len(missing)
        stats['extra_id'] += len(extra)

        # Tạo issue cho missing IDs (empty translation)
        for mid in missing:
            sub = next((s for s in subtitles if s.index == mid), None)
            if sub:
                _upsert_issue(
                    db, sub,
                    error_types=['missing_id'],
                    severity='error',
                    batch_index=b.batch_index,
                )

    # Detect per-subtitle errors
    unknown_count = 0
    for sub in subtitles:
        errors_for_sub: list[str] = []
        severity: str = 'warning'
        cps_value: Optional[float] = None

        vi = sub.simple_text_vi or ''
        speaker = sub.simple_speaker_zh or ''

        # Empty
        if not vi.strip():
            errors_for_sub.append('empty')
            stats['empty'] += 1
            severity = 'error'

        # Chinese leak
        if has_chinese_chars(vi):
            errors_for_sub.append('chinese_remained')
            stats['chinese_remained'] += 1
            severity = 'error'

        # Invalid speaker
        if speaker == 'UNKNOWN':
            unknown_count += 1
        elif speaker and master and not is_valid_speaker(speaker, master):
            errors_for_sub.append('invalid_speaker')
            stats['invalid_speaker'] += 1
            severity = 'error'

        # CPS
        if vi:
            duration = (sub.end_time or 0) - (sub.start_time or 0)
            cps = calculate_cps(vi, duration, config.cps_max_chars_fallback)
            if cps > config.cps_max:
                cps_value = cps
                errors_for_sub.append('cps_exceeded')
                stats['cps_exceeded'] += 1
                if severity != 'error':
                    severity = 'warning'

        if errors_for_sub:
            _upsert_issue(
                db, sub,
                error_types=errors_for_sub,
                severity=severity,
                cps_value=cps_value,
                batch_index=index_to_batch.get(sub.index, 0),
            )
            # Mark subtitle
            sub.simple_status = 'has_error'
        else:
            # No error → reset status nếu trước đó là has_error
            if sub.simple_status == 'has_error':
                sub.simple_status = 'translated'

    db.commit()

    # Unknown ratio (% so với tổng đã translated)
    total_translated = len(subtitles)
    unknown_ratio = (unknown_count / total_translated * 100.0) if total_translated else 0.0

    # Tổng errors = tổng issues status=pending hoặc has_error sub
    total_errors = sum(
        v for k, v in stats.items() if k != 'total'
    )
    stats['total'] = total_errors

    # ─── Build response ─────────────────────────────────────────────────────
    issues = (
        db.query(SimpleIssue)
        .filter(
            SimpleIssue.project_id == project_id,
            SimpleIssue.status == 'pending',
        )
        .order_by(SimpleIssue.subtitle_index)
        .all()
    )

    errors_out = []
    for iss in issues:
        try:
            err_types = json.loads(iss.error_types_json or '[]')
        except Exception:
            err_types = []
        errors_out.append({
            'id': iss.id,
            'subtitle_index': iss.subtitle_index,
            'batch_index': iss.batch_index,
            'error_types': err_types,
            'severity': iss.severity,
            'zh': iss.zh,
            'current_speaker': iss.speaker_before,
            'current_vi': iss.text_before,
            'cps_value': iss.cps_value,
            'auto_fixable': False,
            'needs_ai': True,
            'detected_at': iss.detected_at,
        })

    stats_out = {
        'json_parse': stats['json_parse'],
        'missing_id': stats['missing_id'],
        'extra_id': stats['extra_id'],
        'invalid_speaker': stats['invalid_speaker'],
        'chinese_remained': stats['chinese_remained'],
        'cps_exceeded': stats['cps_exceeded'],
        'empty': stats['empty'],
        'unknown_ratio_percent': round(unknown_ratio, 1),
        'total_errors': total_errors,
        'auto_fixed': auto_fixed_count,
        'last_scan_at': datetime.now(timezone.utc),
    }

    return {
        'stats': stats_out,
        'errors': errors_out,
        'auto_fixed_count': auto_fixed_count,
    }


# ─── Helper: upsert issue ────────────────────────────────────────────────────

def _upsert_issue(
    db: Session,
    sub: Subtitle,
    *,
    error_types: list[str],
    severity: str,
    cps_value: Optional[float] = None,
    batch_index: int = 0,
) -> SimpleIssue:
    """Create hoặc update SimpleIssue (status=pending) cho subtitle này.

    Nếu issue cũ status=fixed → tạo issue mới (vì lỗi quay lại sau khi fix).
    """
    existing = (
        db.query(SimpleIssue)
        .filter(
            SimpleIssue.project_id == sub.project_id,
            SimpleIssue.subtitle_id == sub.id,
            SimpleIssue.status.in_(('pending',)),
        )
        .first()
    )

    if existing:
        existing.error_types_json = json.dumps(error_types)
        existing.severity = severity
        existing.text_before = sub.simple_text_vi
        existing.speaker_before = sub.simple_speaker_zh
        existing.cps_value = cps_value
        existing.batch_index = batch_index
        return existing

    issue = SimpleIssue(
        project_id=sub.project_id,
        subtitle_id=sub.id,
        subtitle_index=sub.index,
        batch_index=batch_index,
        error_types_json=json.dumps(error_types),
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
    return issue


# ─── Get current stats (no rescan) ───────────────────────────────────────────

def get_filter_stats(db: Session, project_id: int) -> dict:
    """Trả stats hiện tại từ DB issues (KHÔNG rescan)."""
    issues = (
        db.query(SimpleIssue)
        .filter(
            SimpleIssue.project_id == project_id,
            SimpleIssue.status == 'pending',
        )
        .all()
    )

    stats = {
        'json_parse': 0, 'missing_id': 0, 'extra_id': 0,
        'invalid_speaker': 0, 'chinese_remained': 0,
        'cps_exceeded': 0, 'empty': 0,
    }

    for iss in issues:
        try:
            types = json.loads(iss.error_types_json or '[]')
        except Exception:
            continue
        for t in types:
            if t in stats:
                stats[t] += 1

    # Unknown ratio
    total_translated = db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.simple_text_vi.isnot(None),
    ).count()
    unknown_count = db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.simple_speaker_zh == 'UNKNOWN',
    ).count()
    unknown_ratio = (unknown_count / total_translated * 100.0) if total_translated else 0.0

    errors_out = []
    for iss in issues:
        try:
            err_types = json.loads(iss.error_types_json or '[]')
        except Exception:
            err_types = []
        errors_out.append({
            'id': iss.id,
            'subtitle_index': iss.subtitle_index,
            'batch_index': iss.batch_index,
            'error_types': err_types,
            'severity': iss.severity,
            'zh': iss.zh,
            'current_speaker': iss.speaker_before,
            'current_vi': iss.text_before,
            'cps_value': iss.cps_value,
            'auto_fixable': False,
            'needs_ai': True,
            'detected_at': iss.detected_at,
        })

    return {
        'stats': {
            **stats,
            'unknown_ratio_percent': round(unknown_ratio, 1),
            'total_errors': len(issues),
            'auto_fixed': 0,
            'last_scan_at': None,
        },
        'errors': errors_out,
        'auto_fixed_count': 0,
    }


# ─── Auto-fix all (rerun chỉ phần auto-fix) ──────────────────────────────────

def auto_fix_all(db: Session, project_id: int) -> int:
    """Chạy auto-fix cho tất cả subtitles của project. Trả số dòng đã fix."""
    subtitles = (
        db.query(Subtitle)
        .filter(
            Subtitle.project_id == project_id,
            Subtitle.simple_text_vi.isnot(None),
        )
        .all()
    )
    count = 0
    for sub in subtitles:
        new_text, applied = auto_fix_text(sub.simple_text_vi or '')
        if applied:
            sub.simple_text_vi = new_text
            count += 1
    db.commit()
    return count
