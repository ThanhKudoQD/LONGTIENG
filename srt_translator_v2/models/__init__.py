"""
Models module — Pydantic models cho v3 pipeline.

Cấu trúc 3 tầng: Arc (Bible.world.arcs) → Chunk → Scene
Translation: 2 variants (v1 sát nghĩa, v2 thoát ý)
"""
from .bible import (
    Character, Cast,
    StoryArc, World,
    GlossaryTerm, Glossary,
    Bible,
)
from .scene import (
    Scene, Chunk, ChunkMap,
    EMOTIONS, normalize_emotion,
)
from .translation import (
    SubtitleLine, TranslationResult,
    ReviewIssue, PolishReport,
)

# Backwards compat aliases (cho code cũ tham chiếu)
Pronouns = None  # Removed in v3
GenrePack = None  # Removed in v3
SceneMap = ChunkMap  # Rename

__all__ = [
    # Bible
    "Character", "Cast",
    "StoryArc", "World",
    "GlossaryTerm", "Glossary",
    "Bible",
    # Scene
    "Scene", "Chunk", "ChunkMap", "SceneMap",
    "EMOTIONS", "normalize_emotion",
    # Translation
    "SubtitleLine", "TranslationResult",
    "ReviewIssue", "PolishReport",
]
