"""
v3.8 — Persistence service cho LLM calls + pipeline events.

Mục đích: lưu vào DB để UI tab Logs load lại được khi F5/reload.

Rolling buffer:
- LLMCall:      tối đa 200 row / project (cũ tự xóa)
- PipelineEvent: tối đa 500 row / project

Không nặng DB: 200 × ~50KB ≈ 10MB / project. SQLite chịu được vài GB.
Cleanup CASCADE khi xóa project.
"""
from __future__ import annotations
import json
import logging
import time
from typing import Optional

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from dubeditor.models import LLMCall, PipelineEvent

logger = logging.getLogger(__name__)

# Cap số row mỗi project
MAX_LLM_CALLS_PER_PROJECT = 200
MAX_EVENTS_PER_PROJECT = 500


def save_llm_call(db: Session, project_id: int, payload: dict) -> Optional[LLMCall]:
    """Lưu 1 LLM call vào DB.

    `payload` shape: dict từ llm_client observer:
      stage_tag, model, provider, attempt, tokens_in, tokens_out, cached_tokens,
      timing_ms, temperature, json_mode, thinking, finish_reason, error,
      prompt_full, response_full (hoặc prompt_preview/response_preview)
    """
    try:
        row = LLMCall(
            project_id=project_id,
            created_at=time.time(),
            stage_tag=(payload.get("stage_tag") or "")[:64] or None,
            provider=(payload.get("provider") or "")[:32] or None,
            model=(payload.get("model") or "")[:128] or None,
            attempt=int(payload.get("attempt") or 1),
            tokens_in=int(payload.get("tokens_in") or 0),
            tokens_out=int(payload.get("tokens_out") or 0),
            cached_tokens=int(payload.get("cached_tokens") or 0),
            timing_ms=int(payload.get("timing_ms") or 0),
            temperature=float(payload.get("temperature") or 0.0),
            json_mode=bool(payload.get("json_mode") or False),
            thinking=payload.get("thinking"),
            finish_reason=(payload.get("finish_reason") or "")[:32] or None,
            error=payload.get("error"),
            prompt_full=payload.get("prompt_full") or payload.get("prompt_preview"),
            response_full=payload.get("response_full") or payload.get("response_preview"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        _trim_llm_calls(db, project_id)
        return row
    except Exception as e:
        logger.warning(f"[llm_log] save_llm_call failed pid={project_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None


def save_pipeline_event(db: Session, project_id: int, stage: str,
                          progress: float, message: str,
                          detail: Optional[dict] = None) -> Optional[PipelineEvent]:
    """Lưu 1 progress event vào DB."""
    try:
        row = PipelineEvent(
            project_id=project_id,
            created_at=time.time(),
            stage=(stage or "")[:64] or None,
            progress=float(progress or 0.0),
            message=(message or "")[:2000] or None,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        _trim_events(db, project_id)
        return row
    except Exception as e:
        logger.warning(f"[llm_log] save_pipeline_event failed pid={project_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _trim_llm_calls(db: Session, project_id: int):
    """Xóa row cũ vượt MAX_LLM_CALLS_PER_PROJECT (raw SQL — nhanh, 1 statement)."""
    try:
        db.execute(
            sql_text(
                "DELETE FROM llm_calls WHERE project_id = :pid AND id NOT IN ("
                " SELECT id FROM llm_calls WHERE project_id = :pid "
                " ORDER BY id DESC LIMIT :keep)"
            ),
            {"pid": project_id, "keep": MAX_LLM_CALLS_PER_PROJECT},
        )
        db.commit()
    except Exception as e:
        logger.debug(f"[llm_log] trim_llm_calls failed: {e}")


def _trim_events(db: Session, project_id: int):
    try:
        db.execute(
            sql_text(
                "DELETE FROM pipeline_events WHERE project_id = :pid AND id NOT IN ("
                " SELECT id FROM pipeline_events WHERE project_id = :pid "
                " ORDER BY id DESC LIMIT :keep)"
            ),
            {"pid": project_id, "keep": MAX_EVENTS_PER_PROJECT},
        )
        db.commit()
    except Exception as e:
        logger.debug(f"[llm_log] trim_events failed: {e}")


def load_llm_calls(db: Session, project_id: int, limit: int = 200) -> list[LLMCall]:
    """Trả list LLM call, từ cũ → mới (asc theo id) — UI append theo thứ tự thời gian."""
    return (db.query(LLMCall)
              .filter(LLMCall.project_id == project_id)
              .order_by(LLMCall.id.asc())
              .limit(limit)
              .all())


def load_pipeline_events(db: Session, project_id: int, limit: int = 500) -> list[PipelineEvent]:
    return (db.query(PipelineEvent)
              .filter(PipelineEvent.project_id == project_id)
              .order_by(PipelineEvent.id.asc())
              .limit(limit)
              .all())


def clear_logs(db: Session, project_id: int):
    """Xoá hết logs của project (user bấm 'Clear logs' chẳng hạn)."""
    try:
        db.execute(sql_text("DELETE FROM llm_calls WHERE project_id = :pid"),
                   {"pid": project_id})
        db.execute(sql_text("DELETE FROM pipeline_events WHERE project_id = :pid"),
                   {"pid": project_id})
        db.commit()
    except Exception as e:
        logger.warning(f"[llm_log] clear_logs failed pid={project_id}: {e}")
        db.rollback()
