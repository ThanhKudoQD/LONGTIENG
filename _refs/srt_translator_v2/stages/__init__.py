"""
Stages module — 5 stages của pipeline v3.
"""
from .stage1_bible import run_stage1_bible
from .stage2_scenes import run_stage2_chunks, run_stage2_scenes
from .stage3_speaker import run_stage3_speaker
from .stage4_translate import run_stage4_translate
from .stage5_polish import run_stage5_polish

__all__ = [
    "run_stage1_bible",
    "run_stage2_chunks",
    "run_stage2_scenes",  # alias
    "run_stage3_speaker",
    "run_stage4_translate",
    "run_stage5_polish",
]
