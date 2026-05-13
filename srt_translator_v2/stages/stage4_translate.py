"""
Stage 4 — Translate per scene.

Đây là TRÁI TIM của pipeline.
Dịch từng phân cảnh một, có:
- Bible toàn phim làm context
- Genre Pack styling
- Scene context cụ thể
- Address matrix dựng động
- Output JSON có speaker_vi, emotion, intensity
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional

import httpx

from config import PipelineConfig
from core.llm_client import LLMRequest, call_llm, parse_json_response, CostTracker
from core.srt_parser import SrtEntry
from models import Bible, GenrePack, Scene, SceneMap

logger = logging.getLogger(__name__)


def load_prompt(name: str, config: PipelineConfig) -> str:
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# ADDRESS MATRIX
# ─────────────────────────────────────────────────────────────────

def build_address_matrix(
    scene: Scene,
    bible: Bible,
    genre_pack: Optional[GenrePack],
) -> str:
    """Dựng ma trận xưng hô cho các nhân vật trong cảnh.

    Logic:
    1. Ưu tiên `speaker.addresses[listener_zh]` từ Bible (do Stage 1A xác định).
    2. Nếu thiếu, suy luận theo gender + role + relationship.
    3. KHÔNG bao giờ tự ý đưa cặp huyết thống nếu Bible không có relationship rõ.

    Trả về string dạng:
      Cố Trầm Châu (nam_chinh, nam) → Tô Niệm (nu_chinh, nu): "anh - em" [Bible]
      Tô Niệm → Cố Trầm Châu: "em - anh" [suy luận] [QH: vợ chưa cưới]
    """
    present = [zh for zh in scene.characters_present
               if not zh.startswith(("phu_", "khach_", "?"))]

    lines = []
    for speaker_zh in present:
        speaker = bible.cast.get_by_zh(speaker_zh)
        if not speaker:
            continue

        for listener_zh in present:
            if listener_zh == speaker_zh:
                continue
            listener = bible.cast.get_by_zh(listener_zh)
            if not listener:
                continue

            # Cách speaker tự xưng (default từ Bible)
            self_pn = speaker.self_address.default or "tôi"

            # Cách speaker gọi listener: ưu tiên Bible.addresses, sau đó suy luận
            other_pn = speaker.addresses.get(listener_zh, "")
            source = "[Bible]"

            if not other_pn:
                source = "[suy luận]"
                relation = (speaker.relationships or {}).get(listener_zh, "").lower()

                # Heuristic theo relationship trước
                if any(k in relation for k in ("mẹ", "má ruột")):
                    other_pn, self_pn = "mẹ", "con"
                elif any(k in relation for k in ("bố", "cha", "ba ruột")):
                    other_pn, self_pn = "bố", "con"
                elif any(k in relation for k in ("con trai", "con gái", "con ruột")):
                    other_pn = "con"
                elif "anh trai" in relation or "anh ruột" in relation:
                    other_pn = "anh"
                    self_pn = "em"
                elif "em trai" in relation or "em gái" in relation:
                    other_pn = "em"
                    self_pn = "anh" if speaker.gender == "nam" else "chị"
                elif "chị" in relation:
                    other_pn, self_pn = "chị", "em"
                elif any(k in relation for k in ("vợ", "chồng", "người yêu", "vợ chưa cưới", "yêu nhau", "hôn nhân")):
                    if speaker.gender == "nam":
                        self_pn, other_pn = "anh", "em"
                    else:
                        self_pn, other_pn = "em", "anh"
                elif "bạn thân" in relation or "bạn bè" in relation or relation == "bạn":
                    # NỮ-NỮ bạn thân: "tớ-cậu", NAM-NAM: "tôi-cậu"
                    if speaker.gender == "nu" and listener.gender == "nu":
                        self_pn, other_pn = "tớ", "cậu"
                    elif speaker.gender == "nam" and listener.gender == "nam":
                        self_pn, other_pn = "tôi", "cậu"
                    else:
                        other_pn = "cậu"
                # Fallback theo gender (KHÔNG dùng huyết thống)
                elif listener.gender == "nu":
                    other_pn = "em" if speaker.gender == "nam" else "cô"
                elif listener.gender == "nam":
                    other_pn = "anh" if speaker.gender == "nu" else "cậu"
                else:
                    other_pn = "cậu"

            relation_text = (speaker.relationships or {}).get(listener_zh, "")
            relation_suffix = f" [QH: {relation_text}]" if relation_text else ""

            lines.append(
                f"  {speaker.vi} ({speaker.role}, {speaker.gender}) → "
                f"{listener.vi} ({listener.role}, {listener.gender}): "
                f"\"{self_pn} - {other_pn}\" {source}{relation_suffix}"
            )

    if not lines:
        return "  (Không có cặp nhân vật rõ ràng trong cảnh)"

    # Thêm thông tin cảm xúc cảnh để hint chuyển xưng hô
    emotion_hint = ""
    if scene.emotion_primary in ("angry", "cold"):
        emotion_hint = "\n  ⚠️ Cảnh giận/lạnh: có thể chuyển sang 'tôi-cô' hoặc 'tao-mày' nếu cao trào."
    elif scene.emotion_primary == "intimate":
        emotion_hint = "\n  ❤️ Cảnh thân mật: dùng 'anh-em' nếu là cặp yêu, 'mẹ-con' nếu gia đình."
    elif scene.emotion_primary == "sarcastic":
        emotion_hint = "\n  🎭 Cảnh mỉa mai: giữ xưng hô lịch sự, ý thì cay."

    return "\n".join(lines) + emotion_hint


# ─────────────────────────────────────────────────────────────────
# CHARACTERS IN SCENE (formatted)
# ─────────────────────────────────────────────────────────────────

def format_characters_in_scene(scene: Scene, bible: Bible) -> str:
    """Mô tả nhân vật trong cảnh + style."""
    lines = []
    for zh in scene.characters_present:
        ch = bible.cast.get_by_zh(zh)
        if ch:
            lines.append(
                f"  · {ch.vi} ({ch.zh}) — {ch.role}, {ch.gender}\n"
                f"    Kiểu nói: {ch.speaking_style or '(chưa rõ)'}\n"
                f"    Tự xưng: {ch.self_address.default}"
            )
        else:
            lines.append(f"  · {zh} (không rõ trong Cast)")
    return "\n".join(lines) if lines else "  (Không xác định)"


# ─────────────────────────────────────────────────────────────────
# GLOSSARY BLOCK (chỉ phần liên quan)
# ─────────────────────────────────────────────────────────────────

def format_glossary_block(bible: Bible, scene: Scene,
                          entries_by_idx: dict[int, SrtEntry]) -> str:
    """Chỉ liệt kê glossary terms XUẤT HIỆN trong scene này."""
    scene_text = ""
    for i in range(scene.start_line, scene.end_line + 1):
        e = entries_by_idx.get(i)
        if e:
            scene_text += e.text + " "

    relevant = []
    for term in bible.glossary.terms:
        if term.zh in scene_text:
            relevant.append(f"  · {term.zh} → \"{term.vi}\""
                            + (f"  ({term.notes})" if term.notes else ""))

    if not relevant:
        return "  (Không có thuật ngữ đặc biệt trong cảnh này)"
    return "\n".join(relevant)


# ─────────────────────────────────────────────────────────────────
# DIALOGUE FORMATTING
# ─────────────────────────────────────────────────────────────────

def format_dialogue_input(
    scene: Scene,
    entries_by_idx: dict[int, SrtEntry],
    speaker_map: dict[int, dict],
    bible: Bible,
) -> str:
    """Format thoại cho prompt — bao gồm speaker_zh + duration."""
    lines = []
    for i in range(scene.start_line, scene.end_line + 1):
        e = entries_by_idx.get(i)
        if not e:
            continue

        speaker_info = speaker_map.get(i, {})
        speaker_zh = speaker_info.get("speaker_zh", "?")

        duration = e.end_sec - e.start_sec
        lines.append(f"{e.index} | {speaker_zh} | {e.text} | {duration:.1f}s")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# HOOK INSTRUCTION
# ─────────────────────────────────────────────────────────────────

def hook_instruction(scene: Scene) -> str:
    if scene.is_hook:
        return ("⚠️ Cảnh này có HOOK LINE (cliffhanger): dòng cuối thường là câu sốc, "
                "đe dọa, twist. Dịch MẠNH, có thể thêm 'thôi/đó/này' để nhấn mạnh. "
                "Giữ kịch tính.")
    if scene.is_emotion_peak:
        return ("🎯 Cảnh ĐỈNH CẢM XÚC: dịch chính xác cường độ, không làm dịu. "
                "Câu nào cay thì giữ cay, câu nào đau thì giữ đau.")
    return "(Cảnh thường, dịch tự nhiên)"


# ─────────────────────────────────────────────────────────────────
# PROCESS ONE SCENE
# ─────────────────────────────────────────────────────────────────

async def process_one_scene(
    scene: Scene,
    bible: Bible,
    genre_pack: Optional[GenrePack],
    entries_by_idx: dict[int, SrtEntry],
    speaker_map: dict[int, dict],
    prompt_template: str,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> dict[int, dict]:
    """Dịch 1 phân cảnh, return map line_index -> {text_vi, speaker_vi, emotion, intensity}."""
    async with semaphore:
        # Build context blocks
        characters_in_scene = format_characters_in_scene(scene, bible)
        address_matrix = build_address_matrix(scene, bible, genre_pack)
        glossary_block = format_glossary_block(bible, scene, entries_by_idx)
        dialogue_input = format_dialogue_input(scene, entries_by_idx, speaker_map, bible)
        hook_inst = hook_instruction(scene)

        # Story arc title
        arc_title = ""
        if scene.story_arc_index is not None and scene.story_arc_index < len(bible.world.story_arcs):
            arc_title = bible.world.story_arcs[scene.story_arc_index].title

        prompt = (prompt_template
                  .replace("{GENRE_MAIN}", bible.world.genre_main)
                  .replace("{GENRE_SUB}", ", ".join(bible.world.genre_sub))
                  .replace("{SETTING}", bible.world.setting or "")
                  .replace("{TONE_OVERALL}", bible.world.tone_overall or "")
                  .replace("{PLOT_SUMMARY}", bible.world.plot_summary or "")
                  .replace("{SCENE_INDEX}", str(scene.index))
                  .replace("{SCENE_LOCATION}", scene.location or "")
                  .replace("{SCENE_SUMMARY}", scene.summary or "")
                  .replace("{SCENE_PURPOSE}", scene.purpose or "")
                  .replace("{SCENE_EMOTION}", scene.emotion_primary)
                  .replace("{SCENE_EMOTION_ARC}", scene.emotion_arc or "")
                  .replace("{STORY_ARC_TITLE}", arc_title)
                  .replace("{IS_HOOK}", "có" if scene.is_hook else "không")
                  .replace("{IS_EMOTION_PEAK}", "có" if scene.is_emotion_peak else "không")
                  .replace("{CHARACTERS_IN_SCENE}", characters_in_scene)
                  .replace("{ADDRESS_MATRIX}", address_matrix)
                  .replace("{GLOSSARY_BLOCK}", glossary_block)
                  .replace("{IS_HOOK_INSTRUCTION}", hook_inst)
                  .replace("{DIALOGUE_INPUT}", dialogue_input))

        req = LLMRequest(
            prompt=prompt,
            model=config.models.heavy,
            api_key=config.api_key,
            temperature=0.4,  # cao hơn — cần creativity cho dịch
            max_output=8000,
            json_mode=True,
            max_retries=config.concurrency.retry_max,
        )

        try:
            resp = await call_llm(req, client=client)
            tracker.add("4_translate", resp)
            data = parse_json_response(resp.text, default={"translations": []})
        except Exception as e:
            logger.warning(f"[Stage 4] Scene {scene.index} failed: {e}")
            return {}

        result = {}
        for t_data in data.get("translations", []) or []:
            try:
                line_idx = int(t_data.get("line_index", -1))
                if line_idx < 1:
                    continue
                result[line_idx] = {
                    "text_vi": t_data.get("text_vi", "") or "",
                    "speaker_vi": t_data.get("speaker_vi", "") or "",
                    "emotion": t_data.get("emotion", "neutral"),
                    "intensity": int(t_data.get("intensity", 5)),
                }
            except Exception:
                continue

        return result


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 4
# ─────────────────────────────────────────────────────────────────

async def run_stage4_translate(
    entries: list[SrtEntry],
    bible: Bible,
    scene_map: SceneMap,
    speaker_map: dict[int, dict],
    config: PipelineConfig,
    tracker: CostTracker,
    genre_pack: Optional[GenrePack] = None,
) -> dict[int, dict]:
    """Dịch toàn phim, return map line_index -> {text_vi, speaker_vi, emotion, intensity}."""
    logger.info("=" * 60)
    logger.info("STAGE 4 — TRANSLATE")
    logger.info("=" * 60)

    prompt_template = load_prompt("translate_scene", config)
    entries_by_idx = {e.index: e for e in entries}

    semaphore = asyncio.Semaphore(config.concurrency.translate)

    async with httpx.AsyncClient() as client:
        tasks = [
            process_one_scene(s, bible, genre_pack, entries_by_idx, speaker_map,
                              prompt_template, config, tracker, client, semaphore)
            for s in scene_map.scenes
        ]

        all_results = {}
        completed = 0
        total = len(tasks)

        for coro in asyncio.as_completed(tasks):
            scene_result = await coro
            all_results.update(scene_result)
            completed += 1
            if completed % 10 == 0 or completed == total:
                logger.info(f"   [Stage 4] {completed}/{total} scenes translated")

    # Coverage check
    covered = len(all_results)
    expected = len(entries)
    missing = expected - covered
    if missing > 0:
        logger.warning(f"[Stage 4] {missing}/{expected} lines NOT translated. "
                       f"Will fill with placeholder.")

    logger.info(f"[Stage 4] DONE. {covered}/{expected} lines translated.")
    return all_results