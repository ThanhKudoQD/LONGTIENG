"""
Issues service — Tab V.

List + filter + manage SimpleIssue records.
"""
from __future__ import annotations
import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import Subtitle
from dubeditor.simple.models import SimpleIssue

logger = logging.getLogger(__name__)


# ─── List + stats ────────────────────────────────────────────────────────────

def list_issues(
    db: Session,
    project_id: int,
    status: Optional[str] = None,
    error_type: Optional[str] = None,
    attempt: Optional[int] = None,
) -> dict:
    """List issues + stats."""
    q = db.query(SimpleIssue).filter(SimpleIssue.project_id == project_id)
    if status:
        q = q.filter(SimpleIssue.status == status)
    if attempt is not None:
        q = q.filter(SimpleIssue.fix_attempt == attempt)

    issues = q.order_by(SimpleIssue.subtitle_index).all()

    if error_type:
        # Python-side filter (JSON list lookup)
        filtered = []
        for iss in issues:
            try:
                types = json.loads(iss.error_types_json or '[]')
            except Exception:
                continue
            if error_type in types:
                filtered.append(iss)
        issues = filtered

    # Stats (luôn từ TOÀN BỘ project, không apply filter)
    all_issues = (
        db.query(SimpleIssue)
        .filter(SimpleIssue.project_id == project_id)
        .all()
    )

    stats = {
        'total': len(all_issues),
        'pending': sum(1 for i in all_issues if i.status == 'pending'),
        'fixed': sum(1 for i in all_issues if i.status == 'fixed'),
        'still_broken': sum(1 for i in all_issues if i.status == 'still_broken'),
        'manual_resolved': sum(1 for i in all_issues if i.status == 'manual_resolved'),
        'total_cost_usd': round(sum(i.cost_usd_total or 0.0 for i in all_issues), 4),
    }

    issues_out = []
    for iss in issues:
        try:
            err_types = json.loads(iss.error_types_json or '[]')
        except Exception:
            err_types = []
        try:
            attempts = json.loads(iss.attempts_json or '[]')
        except Exception:
            attempts = []

        issues_out.append({
            'id': iss.id,
            'subtitle_id': iss.subtitle_id,
            'subtitle_index': iss.subtitle_index,
            'error_types': err_types,
            'severity': iss.severity,
            'zh': iss.zh,
            'text_before': iss.text_before,
            'speaker_before': iss.speaker_before,
            'text_after': iss.text_after,
            'speaker_after': iss.speaker_after,
            'attempts': attempts,
            'fix_attempt': iss.fix_attempt,
            'status': iss.status,
            'needs_human_review': iss.needs_human_review,
            'batch_index': iss.batch_index,
            'detected_at': iss.detected_at,
            'resolved_at': iss.resolved_at,
        })

    return {
        'stats': stats,
        'issues': issues_out,
    }


# ─── Actions ─────────────────────────────────────────────────────────────────

def manual_edit_issue(
    db: Session,
    issue_id: int,
    text: str,
    speaker: Optional[str] = None,
) -> SimpleIssue:
    """User sửa tay → update subtitle + mark issue resolved."""
    iss = db.query(SimpleIssue).filter(SimpleIssue.id == issue_id).first()
    if not iss:
        raise ValueError(f"Issue {issue_id} not found")

    sub = db.query(Subtitle).filter(Subtitle.id == iss.subtitle_id).first()
    if not sub:
        raise ValueError(f"Subtitle {iss.subtitle_id} not found")

    # Apply
    sub.simple_text_vi = text
    if speaker is not None:
        sub.simple_speaker_zh = speaker
    sub.simple_status = 'fixed'
    # Sync sang cột `text` legacy + character_id để Editor cũ thấy bản dịch.
    if text:
        sub.text = text
    if speaker is not None and speaker and speaker not in (
        'UNKNOWN', 'CROWD', 'NARRATOR', 'OFF_SCREEN', 'PHONE'
    ):
        from dubeditor.models import Character
        char = db.query(Character).filter(
            Character.project_id == sub.project_id,
            Character.name_zh == speaker,
        ).first()
        if char:
            sub.character_id = char.id

    iss.text_after = text
    if speaker is not None:
        iss.speaker_after = speaker
    iss.status = 'manual_resolved'
    iss.needs_human_review = False
    iss.resolved_at = datetime.now(timezone.utc)

    db.commit()
    return iss


def mark_resolved(db: Session, issue_id: int) -> SimpleIssue:
    """User chấp nhận bản hiện tại — mark resolved mà không sửa."""
    iss = db.query(SimpleIssue).filter(SimpleIssue.id == issue_id).first()
    if not iss:
        raise ValueError(f"Issue {issue_id} not found")

    iss.status = 'manual_resolved'
    iss.needs_human_review = False
    iss.resolved_at = datetime.now(timezone.utc)

    # Subtitle status
    sub = db.query(Subtitle).filter(Subtitle.id == iss.subtitle_id).first()
    if sub:
        sub.simple_status = 'fixed'

    db.commit()
    return iss


# ─── Export CSV ──────────────────────────────────────────────────────────────

def export_csv(db: Session, project_id: int) -> str:
    """Export tất cả issues thành CSV."""
    issues = (
        db.query(SimpleIssue)
        .filter(SimpleIssue.project_id == project_id)
        .order_by(SimpleIssue.subtitle_index)
        .all()
    )

    out = io.StringIO()
    writer = csv.writer(out)

    writer.writerow([
        'subtitle_index', 'status', 'severity', 'error_types',
        'zh', 'speaker_before', 'text_before',
        'speaker_after', 'text_after',
        'fix_attempt', 'cps_value', 'batch_index',
        'detected_at', 'resolved_at',
    ])

    for iss in issues:
        try:
            err_types = json.loads(iss.error_types_json or '[]')
        except Exception:
            err_types = []
        writer.writerow([
            iss.subtitle_index,
            iss.status,
            iss.severity,
            '|'.join(err_types),
            iss.zh or '',
            iss.speaker_before or '',
            iss.text_before or '',
            iss.speaker_after or '',
            iss.text_after or '',
            iss.fix_attempt,
            iss.cps_value or '',
            iss.batch_index,
            iss.detected_at.isoformat() if iss.detected_at else '',
            iss.resolved_at.isoformat() if iss.resolved_at else '',
        ])

    return out.getvalue()
