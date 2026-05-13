"""Pipeline stages."""
from stages.stage1_bible import run_stage1_bible
from stages.stage2_scenes import run_stage2_scenes
from stages.stage3_speaker import run_stage3_speaker
from stages.stage4_translate import run_stage4_translate
from stages.stage5_polish import run_stage5_polish

__all__ = [
    "run_stage1_bible",
    "run_stage2_scenes",
    "run_stage3_speaker",
    "run_stage4_translate",
    "run_stage5_polish",
]
