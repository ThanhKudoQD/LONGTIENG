"""
Manual translation module — v4 mega-chunk extensions.

Chế độ "Dịch Thủ công" — code sinh prompt, user copy ra ChatGPT/Claude/Gemini
web bên ngoài, paste response về → code parse và lưu DB.

v4 mega-chunk mode (khuyến nghị mới):
- bible_unified     1 paste — gộp cast+world+glossary
- chunks_full       1 paste — chia chunks+scenes toàn phim
- translate_mega    4-5 paste — dịch mega-chunk 1500 dòng (gộp speaker + translate)
- review_pass1      1 paste — consistency scan code-based + AI quyết định
- review_pass2      3-5 paste — per-arc polish cảm tính
Tổng: 10-13 paste/phim 6000 dòng (vs 60 paste của v3 cũ).

v3 stages cũ vẫn giữ để backward-compat:
- normalize, bible_cast, bible_glossary, bible_world,
  chunks, speaker, translate, polish

Public API:
- build_prompt(stage, db, project_id, config) → list[BuiltPrompt]    (v3 stages)
- apply_response(stage, db, project_id, raw, meta, config) → ApplyResult  (v3)
- build_prompt_mega(stage, db, project_id, config) → list[BuiltPrompt]  (v4 mega)
- apply_response_mega(stage, db, project_id, raw, meta, config) → ApplyResult  (v4)
- list_units(stage, db, project_id, config) → list[StageUnit]  (v3)
- list_units_mega(stage, db, project_id, config) → list[StageUnit]  (v4)
"""
from .prompt_builders import (
    build_prompt, BuiltPrompt, list_units, StageUnit,
)
from .parsers import apply_response, ApplyResult

# v4 mega-chunk mode
from .prompt_builders_mega import (
    build_prompt_mega, list_units_mega, partition_into_mega_chunks,
)
from .parsers_mega import apply_response_mega

__all__ = [
    # v3 stages
    "build_prompt",
    "apply_response",
    "list_units",
    # v4 mega stages
    "build_prompt_mega",
    "apply_response_mega",
    "list_units_mega",
    "partition_into_mega_chunks",
    # data classes
    "BuiltPrompt",
    "StageUnit",
    "ApplyResult",
]
