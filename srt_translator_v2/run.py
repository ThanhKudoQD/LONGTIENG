#!/usr/bin/env python3
"""
CLI entry point — SRT Translator v3.

Sử dụng:
    # Full pipeline (mặc định):
    python run.py translate --input movie.srt --output-dir ./out --api-key KEY

    # Custom provider:
    python run.py translate --input movie.srt --provider deepseek --api-key KEY

    # Toggle variant:
    python run.py translate --input movie.srt --variant always
    python run.py translate --input movie.srt --variant off

    # Project type:
    python run.py translate --input movie.srt --project short_drama
    python run.py translate --input movie.srt --project drama_series
    python run.py translate --input movie.srt --project movie
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

# Ensure imports work when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PipelineConfig, default_config
from core.pipeline import run_full_pipeline, export_srt
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
    """Build PipelineConfig từ CLI args."""
    config = default_config()

    # Project type
    if args.project:
        config.project_type = args.project
        config.apply_project_type()

    # Provider
    if args.provider:
        config.provider = args.provider
        # Map default models per provider
        if args.provider == "gemini":
            config.models.heavy = "gemini-2.5-pro"
            config.models.medium = "gemini-2.5-flash"
            config.models.light = "gemini-2.5-flash"
        elif args.provider == "openai":
            config.models.heavy = "gpt-5"
            config.models.medium = "gpt-5-mini"
            config.models.light = "gpt-5-nano"
        elif args.provider == "deepseek":
            config.models.heavy = "deepseek-chat"
            config.models.medium = "deepseek-chat"
            config.models.light = "deepseek-chat"

    # Override models
    if args.model_heavy:
        config.models.heavy = args.model_heavy
    if args.model_medium:
        config.models.medium = args.model_medium
    if args.model_light:
        config.models.light = args.model_light

    # API key
    config.api_key = args.api_key or os.getenv("GEMINI_API_KEY") or \
                     os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or ""

    # Variant mode
    if args.variant:
        config.variant.mode = args.variant

    # Cache
    if args.no_cache:
        config.cache.enabled = False

    # Concurrency
    if args.concurrency:
        config.concurrency.translate = args.concurrency
        config.concurrency.speaker = args.concurrency
        config.concurrency.polish = args.concurrency

    return config


# ─────────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────────

async def cmd_translate(args):
    """Full pipeline."""
    config = build_config_from_args(args)
    if not config.api_key:
        print("❌ Missing API key. Use --api-key or env var.")
        return 1

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ File not found: {input_path}")
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"🎬 Translating: {input_path.name}")
    print(f"   Provider: {config.provider}")
    print(f"   Models: heavy={config.models.heavy}, medium={config.models.medium}")
    print(f"   Variant: {config.variant.mode}")
    print(f"   Output: {output_dir}")
    print()

    result = await run_full_pipeline(str(input_path), config)

    # Save Bible JSON
    bible_path = output_dir / "bible.json"
    bible_path.write_text(
        result.bible.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"💾 Bible → {bible_path}")

    # Save chunks JSON
    chunks_path = output_dir / "chunks.json"
    chunks_path.write_text(
        result.chunk_map.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"💾 Chunks → {chunks_path}")

    # Save full translation JSON
    translation_path = output_dir / "translation.json"
    translation_data = {
        "total_lines": result.translation.total_lines,
        "translated_count": result.translation.translated_count,
        "variants_count": result.translation.variants_count,
        "avg_cps": result.translation.avg_cps,
        "lines": [
            {
                "index": l.index,
                "start": l.start_time_sec,
                "end": l.end_time_sec,
                "text_zh": l.text_zh,
                "speaker_zh": l.speaker_zh,
                "speaker_vi": l.speaker_vi,
                "text_v1": l.text_v1,
                "text_v2": l.text_v2,
                "variant_selected": l.variant_selected,
                "emotion": l.emotion,
                "intensity": l.intensity,
                "cps": l.cps_value,
                "needs_review": l.needs_review,
                "review_reason": l.review_reason,
            }
            for l in result.translation.lines
        ],
    }
    translation_path.write_text(
        json.dumps(translation_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"💾 Translation → {translation_path}")

    # Export SRT (v1 + v2)
    srt_v1 = output_dir / f"{input_path.stem}_vi_v1.srt"
    export_srt(result, str(srt_v1), use_variant=1)
    print(f"📄 SRT v1 (sát nghĩa) → {srt_v1}")

    if result.translation.variants_count > 0:
        srt_v2 = output_dir / f"{input_path.stem}_vi_v2.srt"
        export_srt(result, str(srt_v2), use_variant=2)
        print(f"📄 SRT v2 (thoát ý) → {srt_v2}")

    # Save polish report
    if result.polish_report.issues:
        report_path = output_dir / "polish_report.json"
        report_path.write_text(
            result.polish_report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        print(f"⚠️  Polish report ({len(result.polish_report.issues)} issues) → {report_path}")

    print()
    print(f"✅ Done. Total cost: ${result.cost.total_cost_usd:.4f}")
    return 0


def cmd_info(args):
    """In thông tin file SRT."""
    entries = parse_srt_file(args.input)
    stats = srt_stats(entries)
    print(f"📊 {args.input}")
    for k, v in stats.items():
        print(f"   {k}: {v}")
    return 0


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="SRT Translator v3 — TQ→Việt cho lồng tiếng",
    )
    parser.add_argument("--verbose", "-v", action="store_true")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # translate
    p_tr = sub.add_parser("translate", help="Run full pipeline")
    p_tr.add_argument("--input", required=True, help="Input SRT file")
    p_tr.add_argument("--output-dir", required=True, help="Output directory")
    p_tr.add_argument("--api-key", help="API key (or env GEMINI_API_KEY/OPENAI_API_KEY/DEEPSEEK_API_KEY)")
    p_tr.add_argument("--provider", choices=["gemini", "openai", "deepseek"], default="gemini")
    p_tr.add_argument("--project", choices=["short_drama", "drama_series", "movie"],
                      default="short_drama")
    p_tr.add_argument("--variant", choices=["off", "important_only", "always"],
                      help="Variant 2 bản dịch")
    p_tr.add_argument("--no-cache", action="store_true", help="Tắt prompt caching")
    p_tr.add_argument("--concurrency", type=int, help="Override concurrency (default 5)")
    p_tr.add_argument("--model-heavy", help="Override heavy model")
    p_tr.add_argument("--model-medium", help="Override medium model")
    p_tr.add_argument("--model-light", help="Override light model")

    # info
    p_info = sub.add_parser("info", help="In thống kê SRT")
    p_info.add_argument("--input", required=True)

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.cmd == "translate":
        return asyncio.run(cmd_translate(args))
    elif args.cmd == "info":
        return cmd_info(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
