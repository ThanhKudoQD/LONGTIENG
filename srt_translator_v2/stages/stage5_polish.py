"""
Stage 5 — Polish.

3 sub-stages:
- 5A. CPS Condense: rút gọn dòng vượt CPS, batch 10 dòng/call.
- 5B. Consistency Check: per-character review xuyên phim.
- 5C. Glossary Enforcement: quét tên/thuật ngữ sai.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional

import httpx

from config import PipelineConfig
from core.llm_client import LLMRequest, call_llm, parse_json_response, CostTracker
from core.srt_parser import SrtEntry, calculate_cps, max_chars_for_duration
from models import Bible, Character, SubtitleLine, ReviewIssue, PolishReport

logger = logging.getLogger(__name__)


def load_prompt(name: str, config: PipelineConfig) -> str:
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# 5A. CPS CONDENSE
# ─────────────────────────────────────────────────────────────────

async def stage5a_cps_condense(
    lines: list[SubtitleLine],
    config: PipelineConfig,
    tracker: CostTracker,
) -> list[SubtitleLine]:
    """Rút gọn các dòng vượt CPS — sử dụng cluster-based logic.

    Logic mới (không rút từng dòng riêng):
    1. Tính CPS cho từng dòng
    2. Nhóm các dòng liền kề CÙNG speaker thành cluster (gap ≤ 0.5s)
    3. Tính CPS toàn cluster (tổng text / tổng duration)
    4. Chỉ rút gọn khi CLUSTER CPS > condense_threshold (mặc định 22 cho TTS)
    5. Trong khi rút, prompt cũng nhận thông tin cluster để bù trừ

    → Tránh case "câu A 0.7s dài quá → cắt thành cộc lốc" khi cluster vẫn OK.
    """
    logger.info("[Stage 5A] CPS condensation (cluster-based)...")

    threshold = getattr(config.cps, "condense_threshold", config.cps.max)

    # Tính CPS cho từng dòng (chỉ để hiển thị / lưu DB)
    for line in lines:
        duration = line.end_time_sec - line.start_time_sec
        if duration <= 0 or not line.text_vi:
            line.cps_value = 0.0
            continue
        line.cps_value = calculate_cps(line.text_vi, duration)

    # Build cluster: dòng liền kề + cùng speaker + gap ≤ 0.5s
    clusters: list[list[SubtitleLine]] = []
    current: list[SubtitleLine] = []
    GAP_MAX = 0.5
    for line in lines:
        if not line.text_vi:
            if current:
                clusters.append(current)
                current = []
            continue
        if not current:
            current = [line]
            continue
        prev = current[-1]
        same_speaker = (line.speaker_vi == prev.speaker_vi)
        gap = line.start_time_sec - prev.end_time_sec
        if same_speaker and gap <= GAP_MAX:
            current.append(line)
        else:
            clusters.append(current)
            current = [line]
    if current:
        clusters.append(current)

    # Tìm clusters vượt CPS
    over_cps: list[SubtitleLine] = []  # các dòng trong cluster vượt
    cluster_info: dict[int, list[SubtitleLine]] = {}  # line.index → cluster của nó

    for cluster in clusters:
        total_chars = sum(len(l.text_vi) for l in cluster)
        total_dur = sum(l.end_time_sec - l.start_time_sec for l in cluster)
        if total_dur <= 0:
            continue
        cluster_cps = total_chars / total_dur

        if cluster_cps > threshold:
            for l in cluster:
                l.needs_condense = True
                over_cps.append(l)
                cluster_info[l.index] = cluster

    if not over_cps:
        logger.info(f"[Stage 5A] No clusters exceed CPS threshold {threshold}. Skip.")
        return lines

    logger.info(f"[Stage 5A] {len(over_cps)} lines need condensation "
                f"(cluster CPS > {threshold})")

    prompt_template = load_prompt("cps_condense", config)

    # Batch 10 dòng/call (giữ nguyên dòng trong cùng cluster gần nhau)
    BATCH = 10
    batches = [over_cps[i:i + BATCH] for i in range(0, len(over_cps), BATCH)]

    async with httpx.AsyncClient() as client:
        sem = asyncio.Semaphore(config.concurrency.polish)

        async def process_batch(batch: list[SubtitleLine]) -> dict[int, str]:
            async with sem:
                # Build input — max_chars tính theo CLUSTER:
                # cluster có 3 dòng tổng 5s → max_chars cả cluster = 5*22 = 110
                # → từng dòng được vay/cho mượn ký tự với dòng khác trong cluster
                input_lines = []
                seen_clusters = set()
                for line in batch:
                    cluster = cluster_info.get(line.index, [line])
                    cluster_id = id(cluster)
                    duration = line.end_time_sec - line.start_time_sec
                    # max_chars cho dòng này = giới hạn riêng (loose)
                    max_chars = max_chars_for_duration(duration, threshold)

                    # Thông tin cluster để LLM biết tổng quota
                    if cluster_id not in seen_clusters and len(cluster) > 1:
                        seen_clusters.add(cluster_id)
                        cluster_total_dur = sum(
                            l.end_time_sec - l.start_time_sec for l in cluster
                        )
                        cluster_total_max = max_chars_for_duration(
                            cluster_total_dur, threshold
                        )
                        cluster_total_now = sum(len(l.text_vi) for l in cluster)
                        # Thêm marker cluster header
                        idx_list = ",".join(str(l.index) for l in cluster)
                        input_lines.append(
                            f"# CLUSTER [{idx_list}] tổng {cluster_total_dur:.1f}s "
                            f"= {cluster_total_max} ký tự max (hiện tại {cluster_total_now})"
                        )

                    input_lines.append(
                        f"{line.index} | {line.speaker_vi or '?'} | "
                        f"{line.emotion or 'neutral'} | "
                        f"{max_chars} | {line.text_vi}"
                    )

                prompt = prompt_template.replace("{LINES_TO_CONDENSE}",
                                                  "\n".join(input_lines))

                req = LLMRequest(
                    prompt=prompt,
                    model=config.models.light,
                    api_key=config.api_key,
                    temperature=0.3,
                    max_output=4000,
                    json_mode=True,
                )

                try:
                    resp = await call_llm(req, client=client)
                    tracker.add("5a_condense", resp)
                    data = parse_json_response(resp.text, default={"condensed": []})
                except Exception as e:
                    logger.warning(f"[Stage 5A] Batch failed: {e}")
                    return {}

                result = {}
                for c in data.get("condensed", []) or []:
                    try:
                        idx = int(c.get("line_index", -1))
                        text = c.get("text_vi", "")
                        if idx > 0 and text:
                            result[idx] = text
                    except Exception:
                        continue
                return result

        results_per_batch = await asyncio.gather(*[process_batch(b) for b in batches])

    # Merge và apply
    condensed_map = {}
    for r in results_per_batch:
        condensed_map.update(r)

    applied = 0
    for line in lines:
        if line.index in condensed_map:
            line.condensed_from = line.text_vi
            line.text_vi = condensed_map[line.index]
            # Recompute CPS
            duration = line.end_time_sec - line.start_time_sec
            line.cps_value = calculate_cps(line.text_vi, duration)
            # Mark cần review nếu vẫn vượt emergency
            if line.cps_value > config.cps.emergency_max:
                line.needs_review = True
                line.review_reason = f"CPS={line.cps_value:.1f} > emergency {config.cps.emergency_max}"
            applied += 1

    logger.info(f"[Stage 5A] DONE. Condensed {applied}/{len(over_cps)} lines.")
    return lines


# ─────────────────────────────────────────────────────────────────
# 5B. CONSISTENCY (per-character)
# ─────────────────────────────────────────────────────────────────

async def stage5b_consistency(
    lines: list[SubtitleLine],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
) -> list[ReviewIssue]:
    """Quét consistency cho từng nhân vật chính.

    Chỉ chạy cho nam_chinh, nu_chinh, nam_phu, nu_phu, phan_dien để tiết kiệm cost.
    """
    logger.info("[Stage 5B] Consistency check (per main character)...")

    MAIN_ROLES = {"nam_chinh", "nu_chinh", "nam_phu", "nu_phu", "phan_dien"}
    main_chars = [c for c in bible.cast.characters if c.role in MAIN_ROLES]

    if not main_chars:
        logger.info("[Stage 5B] No main characters identified. Skip.")
        return []

    prompt_template = load_prompt("polish_consistency", config)

    # Group lines theo speaker
    by_speaker = {}
    for line in lines:
        if not line.speaker_vi:
            continue
        by_speaker.setdefault(line.speaker_vi, []).append(line)

    async with httpx.AsyncClient() as client:
        sem = asyncio.Semaphore(config.concurrency.polish)

        async def check_character(char: Character) -> list[ReviewIssue]:
            char_lines = by_speaker.get(char.vi, [])
            if len(char_lines) < 5:  # ít dòng quá → skip
                return []

            async with sem:
                profile = char.model_dump_json(indent=2, exclude_none=True)

                lines_text = "\n".join(
                    f"{l.index} | scene {l.scene_index or '?'} | {l.text_vi}"
                    for l in char_lines
                )

                address_ref = json.dumps([
                    {"vi": c.vi, "zh": c.zh, "role": c.role}
                    for c in bible.cast.characters
                ], ensure_ascii=False)

                prompt = (prompt_template
                          .replace("{CHARACTER_PROFILE}", profile)
                          .replace("{CHARACTER_LINES}", lines_text)
                          .replace("{ADDRESS_REFERENCE}", address_ref))

                req = LLMRequest(
                    prompt=prompt,
                    model=config.models.medium,
                    api_key=config.api_key,
                    temperature=0.2,
                    max_output=8000,
                    json_mode=True,
                )

                try:
                    resp = await call_llm(req, client=client)
                    tracker.add("5b_consistency", resp)
                    data = parse_json_response(resp.text, default={"issues": []})
                except Exception as e:
                    logger.warning(f"[Stage 5B] Failed for {char.vi}: {e}")
                    return []

                issues = []
                for i_data in data.get("issues", []) or []:
                    try:
                        issues.append(ReviewIssue(
                            line_index=int(i_data.get("line_index", 0)),
                            issue_type=i_data.get("issue_type", "consistency"),
                            description=i_data.get("description", "") or "",
                            current_text=i_data.get("current_text", "") or "",
                            suggested_text=i_data.get("suggested_text"),
                            confidence=i_data.get("confidence", "mid"),
                            evidence=i_data.get("evidence", "") or "",
                        ))
                    except Exception:
                        continue
                return issues

        results = await asyncio.gather(*[check_character(c) for c in main_chars])

    all_issues = [iss for sub in results for iss in sub]
    logger.info(f"[Stage 5B] DONE. {len(all_issues)} consistency issues flagged.")
    return all_issues


# ─────────────────────────────────────────────────────────────────
# 5C. GLOSSARY ENFORCEMENT
# ─────────────────────────────────────────────────────────────────

async def stage5c_glossary(
    lines: list[SubtitleLine],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
) -> list[ReviewIssue]:
    """Quét toàn phim, kiểm tra glossary có nhất quán."""
    logger.info("[Stage 5C] Glossary enforcement scan...")

    if not bible.glossary.terms and not bible.cast.characters:
        logger.info("[Stage 5C] Empty glossary + cast. Skip.")
        return []

    prompt_template = load_prompt("polish_glossary", config)

    glossary_json = bible.glossary.model_dump_json(indent=2)
    cast_names = json.dumps([
        {"zh": c.zh, "vi": c.vi,
         "aliases_zh": c.aliases_zh, "aliases_vi": c.aliases_vi}
        for c in bible.cast.characters
    ], ensure_ascii=False, indent=2)

    all_translations = "\n".join(
        f"{l.index} | {l.text_vi}" for l in lines if l.text_vi
    )

    # Nếu translation quá dài → chia chunk (mỗi chunk ~500 lines)
    CHUNK_SIZE = 500
    line_chunks = [lines[i:i + CHUNK_SIZE] for i in range(0, len(lines), CHUNK_SIZE)]

    async with httpx.AsyncClient() as client:
        sem = asyncio.Semaphore(config.concurrency.polish)

        async def scan_chunk(chunk: list[SubtitleLine]) -> list[ReviewIssue]:
            async with sem:
                chunk_text = "\n".join(f"{l.index} | {l.text_vi}"
                                        for l in chunk if l.text_vi)
                prompt = (prompt_template
                          .replace("{GLOSSARY_JSON}", glossary_json)
                          .replace("{CAST_NAMES}", cast_names)
                          .replace("{ALL_TRANSLATIONS}", chunk_text))

                req = LLMRequest(
                    prompt=prompt,
                    model=config.models.medium,
                    api_key=config.api_key,
                    temperature=0.1,
                    max_output=8000,
                    json_mode=True,
                )

                try:
                    resp = await call_llm(req, client=client)
                    tracker.add("5c_glossary", resp)
                    data = parse_json_response(resp.text, default={"issues": []})
                except Exception as e:
                    logger.warning(f"[Stage 5C] Chunk failed: {e}")
                    return []

                issues = []
                for i_data in data.get("issues", []) or []:
                    try:
                        issues.append(ReviewIssue(
                            line_index=int(i_data.get("line_index", 0)),
                            issue_type="glossary",
                            description=i_data.get("description", "") or "",
                            current_text=i_data.get("current_text", "") or "",
                            suggested_text=i_data.get("suggested_text"),
                            confidence=i_data.get("confidence", "mid"),
                            evidence=i_data.get("evidence", "") or "",
                        ))
                    except Exception:
                        continue
                return issues

        chunk_results = await asyncio.gather(*[scan_chunk(c) for c in line_chunks])

    all_issues = [iss for sub in chunk_results for iss in sub]
    logger.info(f"[Stage 5C] DONE. {len(all_issues)} glossary issues flagged.")
    return all_issues


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 5 ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────

async def run_stage5_polish(
    lines: list[SubtitleLine],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
) -> tuple[list[SubtitleLine], PolishReport]:
    """Chạy Stage 5 đầy đủ."""
    logger.info("=" * 60)
    logger.info("STAGE 5 — POLISH")
    logger.info("=" * 60)

    # 5A. CPS Condense
    lines = await stage5a_cps_condense(lines, config, tracker)

    # 5B + 5C song song
    consistency_task = stage5b_consistency(lines, bible, config, tracker)
    glossary_task = stage5c_glossary(lines, bible, config, tracker)
    consistency_issues, glossary_issues = await asyncio.gather(
        consistency_task, glossary_task
    )

    all_issues = consistency_issues + glossary_issues

    # Mark needs_review cho dòng có issue high confidence
    issue_map = {}
    for iss in all_issues:
        if iss.confidence == "high":
            issue_map.setdefault(iss.line_index, []).append(iss)

    for line in lines:
        if line.index in issue_map:
            line.needs_review = True
            issues = issue_map[line.index]
            line.review_reason = "; ".join(
                f"[{i.issue_type}] {i.description[:60]}"
                for i in issues[:2]
            )

    # Summary
    summary = {}
    for iss in all_issues:
        summary[iss.issue_type] = summary.get(iss.issue_type, 0) + 1

    total_issues = len(all_issues)
    if total_issues == 0:
        rating = "excellent"
    elif total_issues < 10:
        rating = "good"
    elif total_issues < 30:
        rating = "needs_minor_fix"
    else:
        rating = "needs_major_fix"

    report = PolishReport(
        issues=all_issues,
        summary=summary,
        overall_rating=rating,
    )

    review_lines = sum(1 for l in lines if l.needs_review)
    logger.info(f"[Stage 5] DONE. Rating: {rating}. "
                f"Issues: {total_issues}. Lines needing review: {review_lines}")

    return lines, report