"""
Test cơ bản — KHÔNG cần API key.
Kiểm tra: parse SRT, models, genre pack loading, config.
"""
import sys
from pathlib import Path

# Add parent dir to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_srt_parser():
    from core.srt_parser import parse_srt_file, srt_stats, parse_time, format_time

    sample = Path(__file__).parent.parent / "examples" / "sample.srt"
    entries = parse_srt_file(str(sample))
    assert len(entries) == 20, f"Expected 20 entries, got {len(entries)}"

    # Time parsing
    assert parse_time("00:00:01,000") == 1.0
    assert parse_time("00:01:23,456") == 83.456
    assert format_time(83.456) == "00:01:23,456"

    # Stats
    stats = srt_stats(entries)
    assert stats["total_lines"] == 20
    print("✅ SRT parser OK")
    print(f"   {stats}")


def test_models():
    from models import Bible, Cast, World, Glossary, Character, Pronouns, StoryArc

    # Build a minimal bible
    cast = Cast(characters=[
        Character(
            zh="顾沉舟", vi="Cố Trầm Châu",
            role="nam_chinh", gender="nam",
            self_address=Pronouns(default="tôi", when_intimate="anh"),
            addresses={"苏念": "em"},
        ),
        Character(
            zh="苏念", vi="Tô Niệm",
            role="nu_chinh", gender="nu",
            self_address=Pronouns(default="em"),
            addresses={"顾沉舟": "anh"},
        ),
    ])

    assert cast.get_by_zh("顾沉舟").vi == "Cố Trầm Châu"
    assert cast.get_by_vi("Tô Niệm").zh == "苏念"

    world = World(
        genre_main="do_thi",
        genre_sub=["tong_tai", "ngon_tinh"],
        plot_summary="Test plot",
        story_arcs=[
            StoryArc(index=0, title="Test Arc", summary="...",
                     start_line=1, end_line=10, emotional_tone="tense"),
        ],
    )

    bible = Bible(cast=cast, world=world, glossary=Glossary())
    json_str = bible.model_dump_json(indent=2, exclude_none=True)
    assert "Cố Trầm Châu" in json_str
    print("✅ Models OK")


def test_genre_packs():
    from config import default_config
    from stages.stage1_bible import list_available_packs, load_genre_pack

    cfg = default_config()
    packs = list_available_packs(cfg)
    expected = ["modern_ceo_romance", "reborn_revenge", "war_god_return",
                "mafia_lord", "ancient_palace"]
    for e in expected:
        assert e in packs, f"Missing pack: {e}"

    # Load one
    pack = load_genre_pack("modern_ceo_romance", cfg)
    assert pack is not None
    assert pack.name_vi == "Tổng tài đô thị"
    assert len(pack.common_terms) > 0
    assert len(pack.common_cliches) > 0
    assert len(pack.translation_examples) > 0
    print(f"✅ Genre packs OK ({len(packs)} packs)")
    print(f"   modern_ceo_romance: {len(pack.common_terms)} terms, "
          f"{len(pack.common_cliches)} cliches, "
          f"{len(pack.translation_examples)} examples")


def test_config():
    from config import default_config, PROJECT_TYPES
    cfg = default_config()
    assert cfg.project_type == "short_drama"
    assert cfg.cps.max == 15.0
    assert "short_drama" in PROJECT_TYPES
    print("✅ Config OK")


def test_prompts_exist():
    from config import default_config
    cfg = default_config()
    expected = [
        "bible_cast", "bible_world", "bible_glossary",
        "scene_detect", "speaker", "translate_scene",
        "cps_condense", "polish_consistency", "polish_glossary",
    ]
    for name in expected:
        path = cfg.prompts_dir / f"{name}.txt"
        assert path.exists(), f"Missing prompt: {name}.txt"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 100, f"Prompt {name} seems too short"
    print(f"✅ Prompts OK ({len(expected)} files)")


def test_json_parser():
    from core.llm_client import parse_json_response

    # Direct JSON
    assert parse_json_response('{"a": 1}') == {"a": 1}

    # JSON with markdown
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}

    # JSON with trailing comma
    assert parse_json_response('{"a": 1,}') == {"a": 1}

    # Extract from text
    assert parse_json_response('Here is: {"a": 1} ok') == {"a": 1}

    print("✅ JSON parser OK")


def test_cps_helpers():
    from core.srt_parser import calculate_cps, max_chars_for_duration
    assert calculate_cps("hello world", 1.0) == 11.0
    assert max_chars_for_duration(2.0, 15.0) == 30
    print("✅ CPS helpers OK")


def main():
    print("=" * 60)
    print("Running basic tests (no API needed)")
    print("=" * 60)

    test_srt_parser()
    test_models()
    test_genre_packs()
    test_config()
    test_prompts_exist()
    test_json_parser()
    test_cps_helpers()

    print()
    print("✅ ALL BASIC TESTS PASSED")


if __name__ == "__main__":
    main()
