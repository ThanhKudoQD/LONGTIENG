"""
Stage 0 — Normalize subtitles (Chuẩn hóa phụ đề).

Workflow đơn giản hóa — 1 AI call duy nhất:

1. Code scan: heuristic phát hiện dòng nghi ngờ
2. Expand: mỗi dòng nghi ngờ lấy ±N dòng context (mặc định ±2)
3. Dedup: gom các dòng overlap thành 1 list
4. 1 PROMPT duy nhất: gửi list dòng + đánh dấu * cho dòng nghi ngờ
5. AI trả về decisions cho toàn bộ dòng nghi ngờ
6. Apply vào DB
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable

import httpx

from config import PipelineConfig
from core.llm_client import LLMRequest, call_llm, parse_json_response, CostTracker
from core.srt_parser import SrtEntry
from core.suspicious_scanner import scan_suspicious, SuspiciousFlag

logger = logging.getLogger(__name__)


def load_prompt(name: str, config: PipelineConfig) -> str:
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


@dataclass
class NormalizeDecision:
    line_index: int
    action: str          # "remove" | "clean" | "keep"
    new_text: Optional[str] = None
    reason: str = ""


@dataclass
class Stage0Report:
    total_lines: int = 0
    suspicious_count: int = 0
    context_lines_sent: int = 0     # số dòng gửi AI (suspicious + context)
    removed: int = 0
    cleaned: int = 0
    kept: int = 0
    decisions: list[NormalizeDecision] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"Stage 0: scan {self.suspicious_count}/{self.total_lines} nghi ngờ, "
            f"gửi {self.context_lines_sent} dòng cho AI → "
            f"remove {self.removed}, clean {self.cleaned}, keep {self.kept}"
        )

    # Backwards compat fields
    @property
    def cluster_count(self) -> int:
        return 1 if self.suspicious_count > 0 else 0


# ─────────────────────────────────────────────────────────────────
# Expand context xung quanh từng dòng nghi ngờ
# ─────────────────────────────────────────────────────────────────

def build_data_lines(
    entries: list[SrtEntry],
    flags: list[SuspiciousFlag],
    context_window: int = 2,
) -> tuple[str, int]:
    """Tạo nội dung gửi AI: mỗi dòng nghi ngờ + ±N context xung quanh.

    Returns:
        (data_text, num_lines_sent)
    """
    if not flags:
        return "", 0

    # Tập indices cần gửi (suspicious + context xung quanh)
    indices_to_send: set[int] = set()
    suspicious_indices: set[int] = {f.line_index for f in flags}

    max_idx = max(e.index for e in entries) if entries else 0

    for f in flags:
        for offset in range(-context_window, context_window + 1):
            idx = f.line_index + offset
            if 1 <= idx <= max_idx:
                indices_to_send.add(idx)

    # Build map flag → reasons để in lý do
    flag_reasons = {f.line_index: f.reasons for f in flags}
    entries_by_idx = {e.index: e for e in entries}

    # Format từng dòng theo thứ tự
    lines = []
    sorted_indices = sorted(indices_to_send)
    prev_idx = None
    for idx in sorted_indices:
        e = entries_by_idx.get(idx)
        if not e:
            continue
        # Thêm separator "..." khi gap > 1 (cho biết có nhảy)
        if prev_idx is not None and idx - prev_idx > 1:
            lines.append("...")
        text = e.text or ""
        if idx in suspicious_indices:
            reasons_str = ", ".join(flag_reasons.get(idx, []))
            lines.append(f"* {idx} | {text}  ← {reasons_str}")
        else:
            lines.append(f"  {idx} | {text}")
        prev_idx = idx

    return "\n".join(lines), len(indices_to_send)


# ─────────────────────────────────────────────────────────────────
# Parse decisions từ AI
# ─────────────────────────────────────────────────────────────────

def parse_decisions(
    data: dict,
    suspicious_indices: set[int],
) -> list[NormalizeDecision]:
    """Parse JSON response từ AI, ensure mọi dòng nghi ngờ có decision."""
    decisions: list[NormalizeDecision] = []
    seen: set[int] = set()

    for d in data.get("decisions", []) or []:
        try:
            idx = int(d.get("i") or d.get("line_index", -1))
            if idx < 1 or idx not in suspicious_indices:
                continue
            action = str(d.get("action", "keep")).lower()
            if action not in ("remove", "clean", "keep"):
                action = "keep"
            new_text = d.get("text") if action == "clean" else None
            if action == "clean" and not new_text:
                action = "keep"
                new_text = None
            decisions.append(NormalizeDecision(
                line_index=idx,
                action=action,
                new_text=new_text,
                reason=str(d.get("reason") or "").strip(),
            ))
            seen.add(idx)
        except Exception as e:
            logger.debug(f"[Stage 0] Skip invalid decision: {e}")
            continue

    # Đảm bảo mọi dòng nghi ngờ đều có decision (mặc định keep)
    for idx in suspicious_indices:
        if idx not in seen:
            decisions.append(NormalizeDecision(
                line_index=idx,
                action="keep",
                reason="AI không trả decision — default keep",
            ))

    return decisions


# ─────────────────────────────────────────────────────────────────
# Apply decisions vào entries
# ─────────────────────────────────────────────────────────────────

def apply_decisions(
    entries: list[SrtEntry],
    decisions: list[NormalizeDecision],
) -> dict[int, dict]:
    """Apply decisions in-place vào entries.

    Returns: update_map cho DB save.
    """
    decision_by_idx = {d.line_index: d for d in decisions}
    update_map: dict[int, dict] = {}

    for e in entries:
        d = decision_by_idx.get(e.index)
        if not d:
            continue
        original = e.text
        if d.action == "remove":
            e.text = ""
            update_map[e.index] = {
                "action": "remove",
                "original_raw": original,
                "new_text": "",
                "is_noise": True,
                "reason": d.reason,
            }
        elif d.action == "clean":
            e.text = (d.new_text or "").strip()
            update_map[e.index] = {
                "action": "clean",
                "original_raw": original,
                "new_text": e.text,
                "is_noise": False,
                "reason": d.reason,
            }
        # keep: không update

    return update_map


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 0 — 1 AI CALL
# ─────────────────────────────────────────────────────────────────

async def run_stage0_normalize(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
    on_cluster_done: Optional[Callable] = None,
) -> tuple[list[SrtEntry], Stage0Report]:
    """Stage 0 — chuẩn hóa subtitles bằng 1 AI call duy nhất.

    Args:
        entries: list SrtEntry gốc
        config: PipelineConfig
        tracker: cost tracker
        on_cluster_done: callback(update_map_dict) sau khi AI xong — checkpoint DB

    Returns:
        (entries_after, report)
    """
    logger.info("=" * 60)
    logger.info("STAGE 0 — NORMALIZE (1-call mode)")
    logger.info("=" * 60)

    total = len(entries)

    # 1. Scan suspicious
    flags = scan_suspicious(entries)
    susp_count = len(flags)
    logger.info(f"[Stage 0] Scan: {susp_count}/{total} dòng khả nghi")

    if not flags:
        return entries, Stage0Report(
            total_lines=total,
            suspicious_count=0,
            context_lines_sent=0,
        )

    # 2. Build data — mỗi nghi ngờ + ±N context, dedup
    context_window = max(0, config.stage0.context_window)
    data_text, lines_sent = build_data_lines(entries, flags, context_window)
    logger.info(f"[Stage 0] Build prompt: {lines_sent} dòng gửi AI "
                f"(±{context_window} context mỗi nghi ngờ)")

    # 3. Gọi AI 1 lần
    prompt_template = load_prompt("normalize", config)
    prompt = prompt_template.replace("{DATA_LINES}", data_text)

    model = config.stage0.model or config.models.light

    req = LLMRequest(
        prompt=prompt,
        model=model,
        api_key=config.api_key,
        temperature=0.2,
        max_output=8000,
        json_mode=True,
        thinking=config.models.light_thinking,
        max_retries=config.concurrency.retry_max,
    )

    async with httpx.AsyncClient() as client:
        try:
            resp = await call_llm(req, client=client, stage_tag="0_normalize")
            tracker.add("0_normalize", resp)
            data = parse_json_response(resp.text, default={"decisions": []})
        except Exception as e:
            logger.error(f"[Stage 0] AI call failed: {e}. Default keep all.")
            decisions = [
                NormalizeDecision(line_index=f.line_index, action="keep",
                                  reason=f"AI failed: {e}")
                for f in flags
            ]
            data = None

    if data is not None:
        suspicious_indices = {f.line_index for f in flags}
        decisions = parse_decisions(data, suspicious_indices)

    # 4. Apply vào entries
    update_map = apply_decisions(entries, decisions)

    # 5. Checkpoint DB
    if on_cluster_done and update_map:
        try:
            res = on_cluster_done(update_map)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.warning(f"[Stage 0] checkpoint failed: {e}")

    # 6. Stats
    removed = sum(1 for d in decisions if d.action == "remove")
    cleaned = sum(1 for d in decisions if d.action == "clean")
    kept = sum(1 for d in decisions if d.action == "keep")

    report = Stage0Report(
        total_lines=total,
        suspicious_count=susp_count,
        context_lines_sent=lines_sent,
        removed=removed,
        cleaned=cleaned,
        kept=kept,
        decisions=decisions,
    )

    logger.info(f"[Stage 0] DONE. {report.summary} "
                f"cost: ${tracker.total_cost_usd:.4f}")
    return entries, report
