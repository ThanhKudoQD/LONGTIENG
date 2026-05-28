"""
Simple Translator — Pipeline dịch SRT Trung → Việt v4.

Thay thế hoàn toàn pipeline v3 cũ (5-8 stages) bằng 4 bước rõ ràng:
  I.   Bible            (single hoặc multi-part + merge)
  II.  Translate batch  (~100 dòng/batch, ACTIVE_BIBLE subset, cached prefix)
  III. Filter errors    (code-based, không AI)
  IV.  Review / Repair  (AI sửa theo group, context adaptive)
  V.   Issues           (lịch sử lỗi)

Cấu trúc:
  models.py       — 4 bảng SQLAlchemy mới + cột bổ sung trên Subtitle
  schemas.py      — Pydantic models cho request/response
  service.py      — Business logic: build prompt, parse response, validate, group
  llm_runner.py   — Wrapper async gọi LLM (dùng srt_translator_v2/core/llm_client)
  prompts/        — Template prompts (.txt)
  routers/        — FastAPI endpoints (bible, batches, filter, review, issues)
"""
