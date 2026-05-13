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
            max_output=16000,
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

def build_translate_batches(scenes: list, lines_per_call: int) -> list[list]:
    """Gộp scenes liền nhau CÙNG story_arc thành batch ~N dòng.

    Quy tắc:
      - Chỉ gộp scenes liền nhau (theo index)
      - Chỉ gộp scenes CÙNG story_arc (để pronoun + emotion context nhất quán)
      - Tổng dòng ≤ lines_per_call → flush batch
      - Scene có is_hook=True hoặc is_emotion_peak=True → tách riêng (giữ chất lượng)
    """
    batches: list[list] = []
    current: list = []
    current_lines = 0
    current_arc: Optional[int] = None

    for sc in scenes:
        sc_len = sc.end_line - sc.start_line + 1
        # Scene đặc biệt → tách riêng
        is_special = sc.is_hook or sc.is_emotion_peak
        # Đổi arc → flush
        arc_changed = (current_arc is not None and sc.story_arc_index != current_arc)
        # Vượt threshold → flush
        will_overflow = current and (current_lines + sc_len > lines_per_call)

        if is_special:
            # Flush current trước, scene đặc biệt 1 mình
            if current:
                batches.append(current)
                current = []
                current_lines = 0
            batches.append([sc])
            current_arc = None
            continue

        if current and (arc_changed or will_overflow):
            batches.append(current)
            current = [sc]
            current_lines = sc_len
            current_arc = sc.story_arc_index
        else:
            current.append(sc)
            current_lines += sc_len
            if current_arc is None:
                current_arc = sc.story_arc_index

    if current:
        batches.append(current)
    return batches


def format_batch_dialogue_input(
    scenes: list,
    entries_by_idx: dict[int, SrtEntry],
    speaker_map: dict[int, dict],
    bible: Bible,
) -> str:
    """Format dialogue cho 1 batch nhiều scenes, có scene boundary markers."""
    parts = []
    for sc in scenes:
        parts.append(f"=== SCENE {sc.index} — {sc.location or '?'} | "
                     f"emotion: {sc.emotion_primary} ===")
        sc_dialogue = format_dialogue_input(sc, entries_by_idx, speaker_map, bible)
        parts.append(sc_dialogue)
        parts.append("")
    return "\n".join(parts).rstrip()


async def process_batch(
    batch: list,
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
    """Dịch 1 batch (nhiều scenes cùng arc), trả về map line_index -> translation.

    Vẫn dùng prompt template cũ — chỉ aggregate context fields đúng:
      - Address matrix: hợp nhất chars present trong tất cả scenes của batch
      - Glossary: hợp nhất terms xuất hiện trong batch
      - Dialogue: nhiều scenes với marker boundary
    """
    if len(batch) == 1:
        # 1 scene → dùng path cũ (tối ưu hơn, prompt clean hơn)
        return await process_one_scene(
            batch[0], bible, genre_pack, entries_by_idx, speaker_map,
            prompt_template, config, tracker, client, semaphore,
        )

    async with semaphore:
        # Aggregate context across scenes in batch
        first = batch[0]
        last = batch[-1]
        scene_range = f"{first.index}-{last.index}"

        # Merge characters_in_scene (deduplicated)
        seen_chars = set()
        char_lines = []
        for sc in batch:
            sc_chars = format_characters_in_scene(sc, bible)
            for line in sc_chars.splitlines():
                if line and line not in seen_chars:
                    seen_chars.add(line)
                    char_lines.append(line)
        characters_in_scene = "\n".join(char_lines)

        # Address matrix dùng chars của tất cả scenes (merge characters_present)
        merged_chars_set = sorted({c for sc in batch for c in sc.characters_present})
        # Tạo synthetic scene để build address matrix
        from models import Scene as _Scene
        synthetic = _Scene(
            index=first.index,
            start_line=first.start_line,
            end_line=last.end_line,
            start_time_sec=first.start_time_sec,
            end_time_sec=last.end_time_sec,
            location=first.location,
            characters_present=merged_chars_set,
            summary=f"Batch {scene_range}",
            emotion_primary=first.emotion_primary,
            emotion_arc=last.emotion_arc or first.emotion_arc,
            purpose=first.purpose,
            story_arc_index=first.story_arc_index,
        )
        address_matrix = build_address_matrix(synthetic, bible, genre_pack)

        # Glossary: merge for all scenes
        seen_terms = set()
        gloss_lines = []
        for sc in batch:
            g = format_glossary_block(bible, sc, entries_by_idx)
            for line in g.splitlines():
                if line and line not in seen_terms:
                    seen_terms.add(line)
                    gloss_lines.append(line)
        glossary_block = "\n".join(gloss_lines)

        dialogue_input = format_batch_dialogue_input(batch, entries_by_idx, speaker_map, bible)
        hook_inst = hook_instruction(first)  # batch không nên chứa hook scenes (đã tách)

        arc_title = ""
        if first.story_arc_index is not None and first.story_arc_index < len(bible.world.story_arcs):
            arc_title = bible.world.story_arcs[first.story_arc_index].title

        # Emotion arc: kết hợp đầu-cuối
        emotion_arc_combined = (
            f"{first.emotion_arc or first.emotion_primary} → {last.emotion_arc or last.emotion_primary}"
        )

        prompt = (prompt_template
                  .replace("{GENRE_MAIN}", bible.world.genre_main)
                  .replace("{GENRE_SUB}", ", ".join(bible.world.genre_sub))
                  .replace("{SETTING}", bible.world.setting or "")
                  .replace("{TONE_OVERALL}", bible.world.tone_overall or "")
                  .replace("{PLOT_SUMMARY}", bible.world.plot_summary or "")
                  .replace("{SCENE_INDEX}", scene_range)
                  .replace("{SCENE_LOCATION}", first.location or "")
                  .replace("{SCENE_SUMMARY}",
                           f"Batch {len(batch)} cảnh liên tiếp cùng arc. " + (first.summary or ""))
                  .replace("{SCENE_PURPOSE}", first.purpose or "")
                  .replace("{SCENE_EMOTION}", first.emotion_primary)
                  .replace("{SCENE_EMOTION_ARC}", emotion_arc_combined)
                  .replace("{STORY_ARC_TITLE}", arc_title)
                  .replace("{IS_HOOK}", "không")  # batch không chứa hook (đã filter)
                  .replace("{IS_EMOTION_PEAK}", "không")
                  .replace("{CHARACTERS_IN_SCENE}", characters_in_scene)
                  .replace("{ADDRESS_MATRIX}", address_matrix)
                  .replace("{GLOSSARY_BLOCK}", glossary_block)
                  .replace("{IS_HOOK_INSTRUCTION}", hook_inst)
                  .replace("{DIALOGUE_INPUT}", dialogue_input))

        req = LLMRequest(
            prompt=prompt,
            model=config.models.heavy,
            api_key=config.api_key,
            temperature=0.4,
            max_output=16000,
            json_mode=True,
            max_retries=config.concurrency.retry_max,
        )

        try:
            resp = await call_llm(req, client=client)
            tracker.add("4_translate", resp)
            data = parse_json_response(resp.text, default={"translations": []})
        except Exception as e:
            logger.warning(f"[Stage 4] Batch {scene_range} failed: {e}")
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


async def run_stage4_translate(
    entries: list[SrtEntry],
    bible: Bible,
    scene_map: SceneMap,
    speaker_map: dict[int, dict],
    config: PipelineConfig,
    tracker: CostTracker,
    genre_pack: Optional[GenrePack] = None,
) -> dict[int, dict]:
    """Dịch toàn phim, return map line_index -> {text_vi, speaker_vi, emotion, intensity}.

    v3: gộp scenes cùng story_arc thành batches để giảm calls.
    Scenes hook hoặc emotion_peak vẫn xử lý riêng để giữ chất lượng.
    """
    logger.info("=" * 60)
    logger.info("STAGE 4 — TRANSLATE")
    logger.info("=" * 60)

    prompt_template = load_prompt("translate_scene", config)
    entries_by_idx = {e.index: e for e in entries}

    # v3: batch scenes cùng arc
    batches = build_translate_batches(
        scene_map.scenes, config.batch.translate_lines_per_call,
    )
    total_lines = sum(s.end_line - s.start_line + 1 for s in scene_map.scenes)
    avg_per_batch = total_lines / max(len(batches), 1)
    single_count = sum(1 for b in batches if len(b) == 1)
    logger.info(f"[Stage 4] {len(scene_map.scenes)} scenes → {len(batches)} batches "
                f"(~{avg_per_batch:.0f} lines/batch, {single_count} single-scene)")

    semaphore = asyncio.Semaphore(config.concurrency.translate)

    async with httpx.AsyncClient() as client:
        tasks = [
            process_batch(batch, bible, genre_pack, entries_by_idx, speaker_map,
                          prompt_template, config, tracker, client, semaphore)
            for batch in batches
        ]

        all_results = {}
        completed = 0
        total = len(tasks)

        for coro in asyncio.as_completed(tasks):
            batch_result = await coro
            all_results.update(batch_result)
            completed += 1
            if completed % 5 == 0 or completed == total:
                logger.info(f"   [Stage 4] {completed}/{total} batches translated")

    # Coverage check
    covered = len(all_results)
    expected = len(entries)
    missing = expected - covered
    if missing > 0:
        logger.warning(f"[Stage 4] {missing}/{expected} lines NOT translated. "
                       f"Will fill with placeholder.")

    logger.info(f"[Stage 4] DONE. {covered}/{expected} lines translated.")
    return all_results