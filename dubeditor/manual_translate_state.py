"""
Manual Translate state service (v3.15).

Quản lý CRUD cho table manual_translate_units — lưu prompt + response của
chế độ Dịch Thủ công để user mở lại không mất data.

Lifecycle 1 unit:
  pending  → (build_prompt) → built  → (apply OK)  → applied
                                     → (apply fail) → failed (vẫn giữ response)

Có thể re-build / re-apply nhiều lần — luôn ghi đè cùng row (upsert theo
unique key: project_id + stage + unit_key).
"""
from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import ManualTranslateUnit

logger = logging.getLogger(__name__)


def _now():
    """UTC now (DB column dùng server_default func.now() khi insert, ở đây dùng cho update)."""
    return datetime.utcnow()


# ─────────────────────────────────────────────────────────────────
# Get / List
# ─────────────────────────────────────────────────────────────────

def get_unit(db: Session, project_id: int, stage: str,
             unit_key: str) -> Optional[ManualTranslateUnit]:
    """Get 1 unit theo (project, stage, unit_key). None nếu chưa có."""
    return (db.query(ManualTranslateUnit)
              .filter(ManualTranslateUnit.project_id == project_id,
                       ManualTranslateUnit.stage == stage,
                       ManualTranslateUnit.unit_key == unit_key)
              .first())


def list_units_for_stage(db: Session, project_id: int,
                          stage: str) -> list[ManualTranslateUnit]:
    """List tất cả unit của 1 stage (theo thứ tự id)."""
    return (db.query(ManualTranslateUnit)
              .filter(ManualTranslateUnit.project_id == project_id,
                       ManualTranslateUnit.stage == stage)
              .order_by(ManualTranslateUnit.id.asc())
              .all())


def list_status_map(db: Session, project_id: int,
                     stage: str) -> dict[str, dict]:
    """Trả dict unit_key → {status, has_prompt, has_response, applied_at}.

    Dùng để frontend hiển thị icon trạng thái mỗi unit trong sidebar.
    """
    rows = list_units_for_stage(db, project_id, stage)
    result = {}
    for r in rows:
        result[r.unit_key] = {
            "status": r.status or "pending",
            "has_prompt": bool(r.prompt),
            "has_response": bool(r.raw_response),
            "applied_at": r.applied_at.isoformat() if r.applied_at else None,
            "apply_summary": r.apply_summary,
        }
    return result


def stage_summary(db: Session, project_id: int, stage: str) -> dict:
    """Đếm tổng/applied/built/failed cho 1 stage (dùng cho badge ở col 1)."""
    rows = list_units_for_stage(db, project_id, stage)
    total = len(rows)
    applied = sum(1 for r in rows if r.status == "applied")
    built = sum(1 for r in rows if r.status == "built")
    failed = sum(1 for r in rows if r.status == "failed")
    return {
        "total_stored": total,
        "applied": applied,
        "built": built,
        "failed": failed,
    }


# ─────────────────────────────────────────────────────────────────
# Upsert helpers
# ─────────────────────────────────────────────────────────────────

def _get_or_create(db: Session, project_id: int, stage: str,
                    unit_key: str, label: Optional[str] = None
                    ) -> ManualTranslateUnit:
    """Tìm row hoặc tạo mới (chưa commit)."""
    row = get_unit(db, project_id, stage, unit_key)
    if row:
        if label and not row.label:
            row.label = label
        return row
    row = ManualTranslateUnit(
        project_id=project_id,
        stage=stage,
        unit_key=unit_key,
        label=label,
        status="pending",
    )
    db.add(row)
    db.flush()
    return row


def save_built_prompt(db: Session, project_id: int, stage: str, unit_key: str,
                       label: str, prompt: str, meta: dict) -> ManualTranslateUnit:
    """Save prompt sau khi build (hoặc edit). Status: pending → built.

    Nếu unit đã 'applied' rồi mà user build lại, KHÔNG hạ status xuống built
    (giữ applied để user biết đã apply rồi, nhưng update prompt mới).
    """
    row = _get_or_create(db, project_id, stage, unit_key, label=label)
    row.prompt = prompt
    row.meta_json = json.dumps(meta or {}, ensure_ascii=False)
    if row.status not in ("applied",):
        row.status = "built"
    row.built_at = _now()
    db.commit()
    db.refresh(row)
    return row


def save_response_text(db: Session, project_id: int, stage: str, unit_key: str,
                        raw_response: str) -> ManualTranslateUnit:
    """Save response text trước khi apply (auto-save khi user gõ — debounced ở frontend).

    Không đổi status. Chỉ ghi đè raw_response.
    """
    row = _get_or_create(db, project_id, stage, unit_key)
    row.raw_response = raw_response
    db.commit()
    db.refresh(row)
    return row


def save_apply_result(db: Session, project_id: int, stage: str, unit_key: str,
                       raw_response: str, ok: bool, summary: str,
                       counts: dict, warnings: list, errors: list
                       ) -> ManualTranslateUnit:
    """Save kết quả apply. Status: → applied (nếu ok) hoặc failed."""
    row = _get_or_create(db, project_id, stage, unit_key)
    row.raw_response = raw_response
    row.status = "applied" if ok else "failed"
    row.apply_summary = summary
    row.apply_counts_json = json.dumps(counts or {}, ensure_ascii=False)
    row.apply_warnings_json = json.dumps(warnings or [], ensure_ascii=False)
    row.apply_errors_json = json.dumps(errors or [], ensure_ascii=False)
    if ok:
        row.applied_at = _now()
    db.commit()
    db.refresh(row)
    return row


def save_prompt_edit(db: Session, project_id: int, stage: str, unit_key: str,
                      prompt: str) -> ManualTranslateUnit:
    """Save khi user edit prompt trực tiếp trong textarea (debounced)."""
    row = _get_or_create(db, project_id, stage, unit_key)
    row.prompt = prompt
    db.commit()
    db.refresh(row)
    return row


def delete_unit(db: Session, project_id: int, stage: str,
                 unit_key: str) -> bool:
    """Xóa 1 unit (user reset). True nếu đã xóa."""
    row = get_unit(db, project_id, stage, unit_key)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def clear_stage(db: Session, project_id: int, stage: str) -> int:
    """Xóa hết units của 1 stage. Trả số row đã xóa."""
    n = (db.query(ManualTranslateUnit)
           .filter(ManualTranslateUnit.project_id == project_id,
                    ManualTranslateUnit.stage == stage)
           .delete())
    db.commit()
    return n


def clear_all(db: Session, project_id: int) -> int:
    """Xóa hết units của 1 project."""
    n = (db.query(ManualTranslateUnit)
           .filter(ManualTranslateUnit.project_id == project_id)
           .delete())
    db.commit()
    return n


# ─────────────────────────────────────────────────────────────────
# Serialize cho API
# ─────────────────────────────────────────────────────────────────

def serialize_unit(row: ManualTranslateUnit) -> dict:
    """Convert row → dict cho API response."""
    if not row:
        return None
    try:
        meta = json.loads(row.meta_json) if row.meta_json else {}
    except Exception:
        meta = {}
    try:
        counts = json.loads(row.apply_counts_json) if row.apply_counts_json else {}
    except Exception:
        counts = {}
    try:
        warnings = json.loads(row.apply_warnings_json) if row.apply_warnings_json else []
    except Exception:
        warnings = []
    try:
        errors = json.loads(row.apply_errors_json) if row.apply_errors_json else []
    except Exception:
        errors = []

    return {
        "stage": row.stage,
        "unit_key": row.unit_key,
        "label": row.label,
        "status": row.status or "pending",
        "prompt": row.prompt or "",
        "raw_response": row.raw_response or "",
        "meta": meta,
        "apply_summary": row.apply_summary,
        "apply_counts": counts,
        "apply_warnings": warnings,
        "apply_errors": errors,
        "built_at": row.built_at.isoformat() if row.built_at else None,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
