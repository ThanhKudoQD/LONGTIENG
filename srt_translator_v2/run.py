#!/usr/bin/env python3
"""
CLI entry point — SRT Translator v2.

Sử dụng:
    # Full pipeline (mặc định, khuyên dùng):
    python run.py translate --input movie.srt --output-dir ./out --api-key KEY

    # Từng stage riêng (debug):
    python run.py bible    --input movie.srt --output bible.json --api-key KEY
    python run.py scenes   --input movie.srt --bible bible.json --output scenes.json
    python run.py speaker  --input movie.srt --bible bible.json --scenes scenes.json --output speakers.json
    python run.py polish   --srt draft.srt --bible bible.json --output final.srt
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Ensure imports work when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PipelineConfig, default_config
from core.pipeline import run_full_pipeline, save_pipeline_outputs
from core.srt_parser import parse_srt_file, srt_stats


# ─────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────

def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


# ─────────────────────────────────────────────────────────────────
# CONFIG BUILDING
# ─────────────────────────────────────────────────────────────────

def build_config_from_args(args) -> PipelineConfig:
    """Build PipelineConfig từ CLI args + env."""
    cfg = default_config()

    # API key: ưu tiên CLI > env theo provider > GOOGLE_API_KEY/GEMINI_API_KEY chung
    if args.api_key:
        cfg.api_key = args.api_key
    else:
        provider = (args.provider or "gemini").lower()
        if provider == "gemini":
            cfg.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        elif provider == "openai":
            cfg.api_key = os.getenv("OPENAI_API_KEY") or ""
        elif provider == "deepseek":
            cfg.api_key = os.getenv("DEEPSEEK_API_KEY") or ""

    if args.provider:
        cfg.provider = args.provider

    # Override model nếu user truyền
    if args.model:
        cfg.models.heavy = args.model
        cfg.models.medium = args.model

    if args.project_type:
        cfg.project_type = args.project_type
        cfg.apply_project_type()

    if args.genre_pack:
        cfg.genre_pack = args.genre_pack if args.genre_pack != "auto" else None

    if args.cps_max:
        cfg.cps.max = args.cps_max

    if args.concurrency:
        cfg.concurrency.speaker = args.concurrency
        cfg.concurrency.translate = args.concurrency

    if not cfg.api_key:
        print("❌ ERROR: No API key. Set --api-key or GEMINI_API_KEY env.",
              file=sys.stderr)
        sys.exit(1)

    return cfg


# ─────────────────────────────────────────────────────────────────
# COMMAND: translate (full)
# ─────────────────────────────────────────────────────────────────

async def cmd_translate(args):
    """Full pipeline."""
    cfg = build_config_from_args(args)

    out_dir = Path(args.output_dir or "./output")
    out_dir.mkdir(parents=True, exist_ok=True)

    base_name = Path(args.input).stem

    print(f"🎬 Input: {args.input}")
    print(f"📁 Output: {out_dir}/")
    print(f"🤖 Provider: {cfg.provider}, Model: {cfg.models.heavy} (heavy) / {cfg.models.medium} (medium)")
    print(f"🎭 Genre pack: {cfg.genre_pack or 'auto-detect'}")
    print(f"⏱️ CPS max: {cfg.cps.max}")
    print()

    result = await run_full_pipeline(args.input, cfg)

    paths = save_pipeline_outputs(result, str(out_dir), base_name)

    print()
    print("✅ DONE")
    print(f"📄 SRT (VI): {paths['srt_vi']}")
    print(f"📋 Review queue: {paths['review_queue']} ({result.translation.lines_needing_review} lines)")
    print(f"💰 Total cost: ${result.cost.total_cost_usd:.4f}")


# ─────────────────────────────────────────────────────────────────
# COMMAND: bible only
# ─────────────────────────────────────────────────────────────────

async def cmd_bible(args):
    """Chỉ chạy Stage 1 — Bible."""
    from core.llm_client import CostTracker
    from stages import run_stage1_bible

    cfg = build_config_from_args(args)

    entries = parse_srt_file(args.input)
    print(f"📂 Loaded {len(entries)} lines")

    tracker = CostTracker()
    bible = await run_stage1_bible(entries, cfg, tracker)

    output = Path(args.output or "bible.json")
    output.write_text(
        bible.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    print(f"💾 Bible saved → {output}")
    print(tracker.summary())


# ─────────────────────────────────────────────────────────────────
# COMMAND: scenes only
# ─────────────────────────────────────────────────────────────────

async def cmd_scenes(args):
    """Chỉ chạy Stage 2 — Scenes."""
    from core.llm_client import CostTracker
    from models import Bible
    from stages import run_stage2_scenes

    cfg = build_config_from_args(args)

    entries = parse_srt_file(args.input)
    bible_data = json.loads(Path(args.bible).read_text(encoding="utf-8"))
    bible = Bible(**bible_data)

    print(f"📂 Loaded {len(entries)} lines + Bible")

    tracker = CostTracker()
    scene_map = await run_stage2_scenes(entries, bible, cfg, tracker)

    output = Path(args.output or "scenes.json")
    output.write_text(
        scene_map.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    print(f"💾 Scenes saved → {output} ({len(scene_map.scenes)} scenes)")
    print(tracker.summary())


# ─────────────────────────────────────────────────────────────────
# COMMAND: speaker only
# ─────────────────────────────────────────────────────────────────

async def cmd_speaker(args):
    """Chỉ chạy Stage 3 — Speaker."""
    from core.llm_client import CostTracker
    from models import Bible, SceneMap
    from stages import run_stage3_speaker

    cfg = build_config_from_args(args)

    entries = parse_srt_file(args.input)
    bible = Bible(**json.loads(Path(args.bible).read_text(encoding="utf-8")))
    scene_map = SceneMap(**json.loads(Path(args.scenes).read_text(encoding="utf-8")))

    tracker = CostTracker()
    speaker_map = await run_stage3_speaker(entries, bible, scene_map, cfg, tracker)

    output = Path(args.output or "speakers.json")
    output.write_text(json.dumps(speaker_map, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    print(f"💾 Speakers saved → {output}")
    print(tracker.summary())


# ─────────────────────────────────────────────────────────────────
# COMMAND: stats
# ─────────────────────────────────────────────────────────────────

def cmd_stats(args):
    """Hiển thị stats của 1 SRT — không cần API."""
    entries = parse_srt_file(args.input)
    stats = srt_stats(entries)
    print(f"📊 SRT Stats: {args.input}")
    for k, v in stats.items():
        print(f"   {k}: {v}")


# ─────────────────────────────────────────────────────────────────
# COMMAND: list-packs
# ─────────────────────────────────────────────────────────────────

def cmd_list_packs(args):
    """Liệt kê genre packs có sẵn."""
    from stages.stage1_bible import list_available_packs, load_genre_pack
    cfg = default_config()
    packs = list_available_packs(cfg)
    print(f"📦 Available genre packs ({len(packs)}):")
    for p_id in packs:
        pack = load_genre_pack(p_id, cfg)
        if pack:
            print(f"   · {p_id}")
            print(f"     {pack.name_vi} — {pack.description[:80]}...")


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="srt_translator_v2",
        description="Dịch SRT phim Trung Quốc → tiếng Việt cho lồng tiếng",
    )
    parser.add_argument("--verbose", "-v", action="store_true")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── translate (full) ──
    p_trans = sub.add_parser("translate", help="Full pipeline (5 stages)")
    p_trans.add_argument("--input", required=True, help="Input SRT (tiếng Trung)")
    p_trans.add_argument("--output-dir", default="./output", help="Thư mục output")
    p_trans.add_argument("--api-key", default=None, help="API key (hoặc set env)")
    p_trans.add_argument("--provider", default="gemini",
                          choices=["gemini", "openai", "deepseek"])
    p_trans.add_argument("--model", default=None,
                          help="Override model name (vd: gemini-2.5-pro)")
    p_trans.add_argument("--project-type", default="short_drama",
                          choices=["short_drama", "drama_series", "movie"])
    p_trans.add_argument("--genre-pack", default="auto",
                          help="auto / modern_ceo_romance / reborn_revenge / ...")
    p_trans.add_argument("--cps-max", type=float, default=None,
                          help="Max CPS (default 15 cho short drama)")
    p_trans.add_argument("--concurrency", type=int, default=None,
                          help="Số call song song (default 5)")

    # ── bible only ──
    p_bible = sub.add_parser("bible", help="Stage 1 only — sinh Bible")
    p_bible.add_argument("--input", required=True)
    p_bible.add_argument("--output", default="bible.json")
    p_bible.add_argument("--api-key", default=None)
    p_bible.add_argument("--provider", default="gemini")
    p_bible.add_argument("--model", default=None)
    p_bible.add_argument("--project-type", default="short_drama")
    p_bible.add_argument("--genre-pack", default="auto")
    p_bible.add_argument("--cps-max", type=float, default=None)
    p_bible.add_argument("--concurrency", type=int, default=None)

    # ── scenes only ──
    p_scenes = sub.add_parser("scenes", help="Stage 2 only — scene detection")
    p_scenes.add_argument("--input", required=True)
    p_scenes.add_argument("--bible", required=True)
    p_scenes.add_argument("--output", default="scenes.json")
    p_scenes.add_argument("--api-key", default=None)
    p_scenes.add_argument("--provider", default="gemini")
    p_scenes.add_argument("--model", default=None)
    p_scenes.add_argument("--project-type", default="short_drama")
    p_scenes.add_argument("--genre-pack", default="auto")
    p_scenes.add_argument("--cps-max", type=float, default=None)
    p_scenes.add_argument("--concurrency", type=int, default=None)

    # ── speaker only ──
    p_speak = sub.add_parser("speaker", help="Stage 3 only — speaker assignment")
    p_speak.add_argument("--input", required=True)
    p_speak.add_argument("--bible", required=True)
    p_speak.add_argument("--scenes", required=True)
    p_speak.add_argument("--output", default="speakers.json")
    p_speak.add_argument("--api-key", default=None)
    p_speak.add_argument("--provider", default="gemini")
    p_speak.add_argument("--model", default=None)
    p_speak.add_argument("--project-type", default="short_drama")
    p_speak.add_argument("--genre-pack", default="auto")
    p_speak.add_argument("--cps-max", type=float, default=None)
    p_speak.add_argument("--concurrency", type=int, default=None)

    # ── stats ──
    p_stats = sub.add_parser("stats", help="Hiển thị stats SRT (không cần API)")
    p_stats.add_argument("--input", required=True)

    # ── list packs ──
    sub.add_parser("list-packs", help="Liệt kê các genre pack có sẵn")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Sync commands
    if args.cmd == "stats":
        cmd_stats(args)
        return
    if args.cmd == "list-packs":
        cmd_list_packs(args)
        return

    # Async commands
    cmd_map = {
        "translate": cmd_translate,
        "bible": cmd_bible,
        "scenes": cmd_scenes,
        "speaker": cmd_speaker,
    }
    asyncio.run(cmd_map[args.cmd](args))


if __name__ == "__main__":
    main()
