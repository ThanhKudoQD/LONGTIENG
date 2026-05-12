"""
Translation pipeline — 3 bước:
  Pass 1: Phân tích phim → Bible + scene_map (có tom_tat từng đoạn)
  Pass 3: Dịch từng chunk với context tối ưu (không gửi thừa)
  Pass 4: QC review — kiểm tra xưng hô, tên, thuật ngữ, cường độ, literal

Provider support: Gemini / OpenAI / DeepSeek
"""
from __future__ import annotations
import json, re, time, asyncio, logging
from pathlib import Path
from typing import Optional

import httpx

PROMPTS_DIR = Path(__file__).parent / "prompts"
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# SRT HELPERS
# ─────────────────────────────────────────────

def parse_srt(raw: str) -> list[dict]:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = []
    for m in re.finditer(
        r"(\d+)\s*\n([\d:,]+)\s*-->\s*([\d:,]+)\s*\n((?:[^\n]+\n?)+)",
        raw.strip(), re.MULTILINE,
    ):
        idx, start, end, text = m.groups()
        blocks.append({
            "index": int(idx),
            "start": start.strip(),
            "end":   end.strip(),
            "text":  text.strip(),
        })
    return blocks


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ─────────────────────────────────────────────
# PROVIDER DETECTION
# ─────────────────────────────────────────────

def detect_provider(model: str) -> str:
    """
    Xác định provider từ tên model.
    Returns: 'gemini' | 'openai' | 'deepseek'
    """
    m = model.lower()
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("deepseek"):
        return "deepseek"
    # gpt-4.x, gpt-5, gpt-5-nano, o1, o3, o4...
    if any(m.startswith(p) for p in ("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    if "/" in m:
        return "openai"
    return "gemini"


def get_api_key(provider: str, cfg: dict) -> str:
    """Lấy đúng API key theo provider từ config dict."""
    if provider == "openai":
        return cfg.get("openai_api_key", "") or cfg.get("api_key", "")
    if provider == "deepseek":
        return cfg.get("deepseek_api_key", "") or cfg.get("api_key", "")
    return cfg.get("api_key", "")


# ─────────────────────────────────────────────
# UNIFIED API CALL — tự detect provider
# ─────────────────────────────────────────────

def _cap_max_output(max_output: int, model: str) -> int:
    """Giới hạn max_output theo từng model để tránh lỗi 400."""
    m = model.lower()
    # OpenAI limits
    if "gpt-4o-mini" in m:                      return min(max_output, 16384)
    if "gpt-4o" in m:                           return min(max_output, 16384)
    if "gpt-4-turbo" in m or "gpt-4-1106" in m: return min(max_output, 4096)
    if "gpt-4" in m:                            return min(max_output, 8192)
    if "gpt-3.5" in m:                          return min(max_output, 4096)
    if m.startswith("o1") or m.startswith("o3") or m.startswith("o4"):
        return min(max_output, 32768)
    # DeepSeek limits
    if "deepseek" in m:                         return min(max_output, 8192)
    # Gemini — rất cao, giữ nguyên
    return max_output


async def _call_api(
    prompt: str,
    api_key: str,
    model: str,
    temperature: float = 0.3,
    response_json: bool = False,
    max_output: int = 8192,
    on_retry=None,
    thinking_budget: int = 0,  # 0=tắt thinking, -1=model tự quyết, N=giới hạn N token
) -> dict:
    """
    Unified call — tự detect provider từ tên model.
    Trả về dict chuẩn: {text, tokens_in, tokens_out, timing_ms, finish_reason}
    """
    max_output = _cap_max_output(max_output, model)
    provider = detect_provider(model)
    if provider == "gemini":
        return await _call_gemini(prompt, api_key, model, temperature, response_json, max_output, on_retry, thinking_budget)
    elif provider == "deepseek":
        return await _call_openai_compat(
            prompt, api_key, model, temperature, response_json, max_output, on_retry,
            base_url="https://api.deepseek.com",
            provider_name="DeepSeek",
        )
    else:  # openai
        return await _call_openai_compat(
            prompt, api_key, model, temperature, response_json, max_output, on_retry,
            base_url="https://api.openai.com/v1",
            provider_name="OpenAI",
        )


# ─────────────────────────────────────────────
# GEMINI HTTP CALL
# ─────────────────────────────────────────────

async def _call_gemini(
    prompt: str,
    api_key: str,
    model: str,
    temperature: float = 0.3,
    response_json: bool = False,
    max_output: int = 8192,
    on_retry=None,
    thinking_budget: int = 0,  # 0 = tắt thinking (nhanh hơn); -1 = để model tự quyết
) -> dict:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model}:generateContent?key={api_key}"
    )
    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output,
        },
    }
    if response_json:
        body["generationConfig"]["responseMimeType"] = "application/json"

    # Gemini 2.5 Flash/Pro mặc định bật thinking → tốn thêm 8k-24k token & 30-90s.
    # thinking_budget=0  → tắt hoàn toàn (Pass 3, Pass 4)
    # thinking_budget=-1 → không set thinkingConfig gì cả, model tự quyết (Pass 1)
    # thinking_budget=N  → giới hạn N token thinking
    #
    # Lưu ý:
    # - gemini-2.5-pro KHÔNG hỗ trợ budget=0 (lỗi 400), minimum là 128
    # - Khi có thinking (budget>0), temperature phải là 1.0 (API requirement)
    # - Model cũ (1.5-pro, 1.5-flash) không có thinkingConfig → không set
    m = model.lower()
    is_flash25  = "2.5" in m and "flash" in m and "thinking" not in m
    is_pro25    = "2.5" in m and "pro" in m
    is_thinking_model = is_flash25 or is_pro25 or "flash-thinking" in m

    if is_thinking_model and thinking_budget >= 0:
        if is_pro25 and thinking_budget == 0:
            # gemini-2.5-pro không cho tắt thinking → set minimum 128
            effective_budget = 128
        else:
            effective_budget = thinking_budget
        body["generationConfig"]["thinkingConfig"] = {
            "thinkingBudget": effective_budget
        }
        # Khi thinking bật (budget > 0), temperature phải là 1.0
        if effective_budget > 0 and "temperature" in body["generationConfig"]:
            body["generationConfig"]["temperature"] = 1.0

    RETRYABLE = {429, 500, 503}
    last_err = ""
    t0 = time.monotonic()
    resp = None
    MAX_RETRY = 8

    for attempt in range(MAX_RETRY):
        if attempt > 0:
            wait = min(15 * attempt, 120)
            logger.warning(f"Gemini {last_err} — retry {attempt}/{MAX_RETRY-1}, chờ {wait}s...")
            if on_retry:
                await on_retry(attempt, MAX_RETRY - 1, wait, last_err)
            await asyncio.sleep(wait)

        # Timeout 600s (10 phút) — phù hợp khi Pass 1 phân tích phim dài
        # hoặc Pass 3 dịch chunk lớn, model có thể trả response chậm.
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(url, json=body)

        if resp.status_code == 200:
            break

        try:
            last_err = resp.json().get("error", {}).get("message", "")
        except Exception:
            last_err = ""
        last_err = last_err or f"HTTP {resp.status_code}"

        if resp.status_code not in RETRYABLE:
            raise RuntimeError(last_err)
    else:
        raise RuntimeError(f"Gemini API lỗi sau {MAX_RETRY} lần thử: {last_err}")

    timing_ms = int((time.monotonic() - t0) * 1000)
    data = resp.json()
    candidate = data["candidates"][0]
    finish_reason = candidate.get("finishReason", "")
    parts = candidate.get("content", {}).get("parts", [])
    text = parts[0]["text"] if parts and "text" in parts[0] else ""
    usage = data.get("usageMetadata", {})
    return {
        "text":          text,
        "tokens_in":     usage.get("promptTokenCount")     or estimate_tokens(prompt),
        "tokens_out":    usage.get("candidatesTokenCount") or estimate_tokens(text),
        "timing_ms":     timing_ms,
        "finish_reason": finish_reason,
        "raw":           data,
    }


# ─────────────────────────────────────────────
# OPENAI-COMPATIBLE HTTP CALL (OpenAI + DeepSeek)
# ─────────────────────────────────────────────

async def _call_openai_compat(
    prompt: str,
    api_key: str,
    model: str,
    temperature: float = 0.3,
    response_json: bool = False,
    max_output: int = 8192,
    on_retry=None,
    base_url: str = "https://api.openai.com/v1",
    provider_name: str = "OpenAI",
) -> dict:
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": max_output,
    }
    # Một số model OpenAI (gpt-5*, o1, o3, o4) không hỗ trợ custom temperature
    _no_temp = ("gpt-5", "o1", "o3", "o4")
    if not any(model.lower().startswith(p) for p in _no_temp):
        body["temperature"] = temperature
    if response_json:
        body["response_format"] = {"type": "json_object"}

    RETRYABLE = {429, 500, 502, 503, 529}
    last_err = ""
    t0 = time.monotonic()
    resp = None
    MAX_RETRY = 8

    for attempt in range(MAX_RETRY):
        if attempt > 0:
            wait = min(15 * attempt, 120)
            logger.warning(f"{provider_name} {last_err} — retry {attempt}/{MAX_RETRY-1}, chờ {wait}s...")
            if on_retry:
                await on_retry(attempt, MAX_RETRY - 1, wait, last_err)
            await asyncio.sleep(wait)

        # Timeout 600s (10 phút) — đủ thoáng cho các model chậm (o1, gpt-5...).
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(url, json=body, headers=headers)

        if resp.status_code == 200:
            break

        try:
            err_data = resp.json()
            last_err = (err_data.get("error", {}).get("message", "")
                        or err_data.get("message", ""))
        except Exception:
            last_err = ""
        last_err = last_err or f"HTTP {resp.status_code}"

        if resp.status_code not in RETRYABLE:
            raise RuntimeError(f"{provider_name}: {last_err}")
    else:
        raise RuntimeError(f"{provider_name} API lỗi sau {MAX_RETRY} lần thử: {last_err}")

    timing_ms = int((time.monotonic() - t0) * 1000)
    data = resp.json()

    choice = data["choices"][0]
    text = choice.get("message", {}).get("content", "") or ""
    finish_reason = choice.get("finish_reason", "")

    usage = data.get("usage", {})
    tokens_in  = usage.get("prompt_tokens")     or estimate_tokens(prompt)
    tokens_out = usage.get("completion_tokens") or estimate_tokens(text)

    # Normalize finish_reason về dạng Gemini-like để code sau xử lý chung
    if finish_reason == "length":
        finish_reason = "MAX_TOKENS"
    elif finish_reason == "stop":
        finish_reason = "STOP"

    return {
        "text":          text,
        "tokens_in":     tokens_in,
        "tokens_out":    tokens_out,
        "timing_ms":     timing_ms,
        "finish_reason": finish_reason,
        "raw":           data,
    }


# ─────────────────────────────────────────────
# PASS 1 — PHÂN TÍCH PHIM (2 sub-pass: 1A nhân vật, 1B scene_map)
# ─────────────────────────────────────────────

def _parse_json_with_fallback(text: str, pass_name: str, finish_reason: str = "",
                                tokens_out: int = 0) -> dict:
    """Parse JSON, fallback bóc markdown code fence nếu cần."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        raise RuntimeError(
            f"{pass_name} không trả JSON hợp lệ: {e}\n"
            f"finish_reason={finish_reason}, tokens_out={tokens_out}\n"
            f"Đầu response:\n{text[:500]}\n...\nCuối response:\n{text[-500:]}"
        )


async def pass1a_analyze(
    srt_blocks: list[dict],
    api_key: str,
    model: str,
    on_retry=None,
) -> tuple[dict, dict]:
    """
    Pass 1A — Phân tích NHÂN VẬT + XƯNG HÔ + THUẬT NGỮ + THỂ LOẠI.

    Input srt_blocks có thể có field "speaker" (SPEAKER_XX từ Diarization).
    Nếu có → render format: index|SPEAKER_XX|text
    Nếu không → render format cũ: index|text (backward compat)

    AI sẽ map mỗi nhân vật với 1+ SPEAKER_XX phù hợp.

    Trả về (data, api_result).
    """
    # Render SRT input — có speaker nếu có
    lines = []
    has_any_speaker = any(b.get("speaker") for b in srt_blocks)
    for b in srt_blocks:
        if has_any_speaker:
            spk = b.get("speaker") or "?"
            lines.append(f"{b['index']}|{spk}|{b['text']}")
        else:
            lines.append(f"{b['index']}|{b['text']}")
    srt_compact = "\n".join(lines)

    prompt_tpl  = (PROMPTS_DIR / "pass1a_characters.txt").read_text(encoding="utf-8")
    prompt      = prompt_tpl.replace("{SRT_INPUT}", srt_compact)

    # max_output cao vì Gemini 2.5 dùng thinking tokens TÍNH VÀO max_output.
    result = await _call_api(
        prompt, api_key, model,
        temperature=0.2,
        response_json=True,
        max_output=32768,
        on_retry=on_retry,
        thinking_budget=8192,
    )

    text = result["text"]
    finish_reason = result.get("finish_reason", "")

    if finish_reason == "MAX_TOKENS":
        raise RuntimeError(
            f"Pass 1A bị cắt token. tokens_out={result['tokens_out']}, "
            f"max_output=32768. Có thể model dùng quá nhiều thinking tokens.\n"
            f"Text trả về:\n{text[:2000]}\n"
            f"... (còn {max(0, len(text)-2000)} ký tự nữa)"
        )
    if finish_reason and finish_reason not in ("STOP", "MODEL_LENGTH", ""):
        raise RuntimeError(
            f"Pass 1A dừng bất thường (finishReason={finish_reason}). "
            f"Có thể do safety filter.\nText trả về:\n{text[:2000]}"
        )

    data = _parse_json_with_fallback(text, "Pass 1A", finish_reason, result["tokens_out"])
    result["prompt"] = prompt
    return data, result


async def pass1b_analyze(
    srt_blocks: list[dict],
    pass1a_data: dict,
    api_key: str,
    model: str,
    on_retry=None,
) -> tuple[dict, dict]:
    """
    Pass 1B — Phân tích CỐT TRUYỆN + TURNING POINTS + SCENE MAP.

    Input: SRT + kết quả Pass 1A làm context.
    Output (~5-6k token): story_arc + turning_points + scene_map đầy đủ.

    AI dùng danh sách nhân vật từ 1A để gán scene.nhan_vat chính xác,
    không bịa tên mới.

    Trả về (data, api_result).
    """
    srt_compact = "\n".join(f"{b['index']}|{b['text']}" for b in srt_blocks)
    prompt_tpl  = (PROMPTS_DIR / "pass1b_storymap.txt").read_text(encoding="utf-8")

    # Render Pass 1A result để inject làm context cho 1B.
    # Compact 1A: chỉ giữ phần cần thiết, bỏ kieu_noi_examples (dài, không cần cho 1B).
    pass1a_compact = {
        "the_loai":           pass1a_data.get("the_loai", {}),
        "nhan_vat":           [
            {k: v for k, v in nv.items() if k != "kieu_noi_examples"}
            for nv in (pass1a_data.get("nhan_vat") or [])
        ],
        "quan_he_noi_bat":    pass1a_data.get("quan_he_noi_bat", []),
        "thuat_ngu":          pass1a_data.get("thuat_ngu", {}),
        "xung_ho_toan_phim":  pass1a_data.get("xung_ho_toan_phim", {}),
    }
    pass1a_str = json.dumps(pass1a_compact, ensure_ascii=False, indent=2)

    prompt = (prompt_tpl
              .replace("{PASS1A_RESULT}", pass1a_str)
              .replace("{SRT_INPUT}",     srt_compact))

    # max_output cao vì 1B sinh nhiều hơn 1A (story + turning + 12 scenes ~6k)
    # Cộng thinking ~15k → tổng ~24k. Đặt 48k để dư an toàn.
    result = await _call_api(
        prompt, api_key, model,
        temperature=0.2,
        response_json=True,
        max_output=49152,
        on_retry=on_retry,
        thinking_budget=12288,
    )

    text = result["text"]
    finish_reason = result.get("finish_reason", "")

    if finish_reason == "MAX_TOKENS":
        raise RuntimeError(
            f"Pass 1B bị cắt token. tokens_out={result['tokens_out']}, "
            f"max_output=49152. Phim quá dài hoặc thinking quá nhiều.\n"
            f"Text trả về:\n{text[:2000]}\n"
            f"... (còn {max(0, len(text)-2000)} ký tự nữa)"
        )
    if finish_reason and finish_reason not in ("STOP", "MODEL_LENGTH", ""):
        raise RuntimeError(
            f"Pass 1B dừng bất thường (finishReason={finish_reason}).\n"
            f"Text trả về:\n{text[:2000]}"
        )

    data = _parse_json_with_fallback(text, "Pass 1B", finish_reason, result["tokens_out"])
    result["prompt"] = prompt
    return data, result


def merge_pass1_results(pass1a: dict, pass1b: dict) -> dict:
    """
    Gộp kết quả Pass 1A + 1B thành Bible hoàn chỉnh tương thích với
    schema cũ (pass3, pass4 không cần biết Bible đến từ đâu).
    """
    bible = {
        # Từ 1A:
        "the_loai":           pass1a.get("the_loai", {}),
        "nhan_vat":           pass1a.get("nhan_vat", []),
        "quan_he_noi_bat":    pass1a.get("quan_he_noi_bat", []),
        "thuat_ngu":          pass1a.get("thuat_ngu", {}),
        "xung_ho_toan_phim":  pass1a.get("xung_ho_toan_phim", {}),
        # Từ 1B:
        "story_arc":              pass1b.get("story_arc", {}),
        "turning_points_xung_ho": pass1b.get("turning_points_xung_ho", []),
        "scene_map":              pass1b.get("scene_map", []),
    }
    return bible


async def pass1_analyze(
    srt_blocks: list[dict],
    api_key: str,
    model: str,
    pid: int = None,
    on_retry=None,
    on_progress=None,  # async callback(stage_name, message) — optional
) -> tuple[dict, dict]:
    """
    Pass 1 = Pass 1A → Pass 1B → merge.

    Backward-compatible: trả về (bible, api_result) giống monolithic cũ.
    api_result là dict gộp tokens/timing của cả 2 pass.

    on_progress: callable async, nhận (stage, message). Để frontend hiển thị
    tiến trình "Bước 1/2 - Phân tích nhân vật" rồi "Bước 2/2 - Phân tích cảnh".
    """
    # ── PASS 1A ──────────────────────────────────────────────────────────────
    logger.info(f"[Pass1 pid={pid}] === BƯỚC 1/2: Pass 1A — phân tích nhân vật ===")
    if on_progress:
        try:
            await on_progress("pass1a_start", "Bước 1/2: Phân tích nhân vật & xưng hô...")
        except Exception:
            pass

    pass1a_data, result_1a = await pass1a_analyze(
        srt_blocks, api_key, model, on_retry=on_retry,
    )

    nv_count = len(pass1a_data.get("nhan_vat") or [])
    logger.info(
        f"[Pass1 pid={pid}] Pass 1A XONG — {nv_count} nhân vật, "
        f"in={result_1a['tokens_in']}, out={result_1a['tokens_out']}, "
        f"time={result_1a['timing_ms']}ms"
    )
    if on_progress:
        try:
            await on_progress(
                "pass1a_done",
                f"Pass 1A xong — phát hiện {nv_count} nhân vật. Sang Bước 2/2...",
            )
        except Exception:
            pass

    # ── PASS 1B ──────────────────────────────────────────────────────────────
    logger.info(f"[Pass1 pid={pid}] === BƯỚC 2/2: Pass 1B — phân tích scene map ===")
    if on_progress:
        try:
            await on_progress("pass1b_start", "Bước 2/2: Phân tích cốt truyện & phân đoạn...")
        except Exception:
            pass

    pass1b_data, result_1b = await pass1b_analyze(
        srt_blocks, pass1a_data, api_key, model, on_retry=on_retry,
    )

    scene_count = len(pass1b_data.get("scene_map") or [])
    logger.info(
        f"[Pass1 pid={pid}] Pass 1B XONG — {scene_count} đoạn, "
        f"in={result_1b['tokens_in']}, out={result_1b['tokens_out']}, "
        f"time={result_1b['timing_ms']}ms"
    )
    if on_progress:
        try:
            await on_progress(
                "pass1b_done",
                f"Pass 1B xong — chia {scene_count} đoạn kịch bản.",
            )
        except Exception:
            pass

    # ── MERGE ────────────────────────────────────────────────────────────────
    bible = merge_pass1_results(pass1a_data, pass1b_data)

    # Gộp api_result để FE hiển thị tổng tokens/timing
    merged_result = {
        "text":         json.dumps(bible, ensure_ascii=False, indent=2),
        "tokens_in":    result_1a["tokens_in"]  + result_1b["tokens_in"],
        "tokens_out":   result_1a["tokens_out"] + result_1b["tokens_out"],
        "timing_ms":    result_1a["timing_ms"]  + result_1b["timing_ms"],
        "finish_reason": "STOP",
        # Chi tiết từng pass — FE muốn debug có thể xem
        "pass1a": {
            "prompt":     result_1a.get("prompt", ""),
            "response":   result_1a.get("text", ""),
            "tokens_in":  result_1a["tokens_in"],
            "tokens_out": result_1a["tokens_out"],
            "timing_ms":  result_1a["timing_ms"],
        },
        "pass1b": {
            "prompt":     result_1b.get("prompt", ""),
            "response":   result_1b.get("text", ""),
            "tokens_in":  result_1b["tokens_in"],
            "tokens_out": result_1b["tokens_out"],
            "timing_ms":  result_1b["timing_ms"],
        },
    }
    return bible, merged_result


# ─────────────────────────────────────────────
# PASS 2 SPEAKER — AI QUYẾT ĐỊNH CUỐI AI NÓI DÒNG NÀO
# ─────────────────────────────────────────────

def _render_bible_summary_for_speaker(bible: dict) -> str:
    """Compact Bible cho Pass 2 Speaker — chỉ phần cần thiết."""
    lines = []
    nv_list = bible.get("nhan_vat") or []

    lines.append("NHÂN VẬT TRONG PHIM:")
    for nv in nv_list:
        zh = nv.get("zh", "?")
        vi = nv.get("vi", "?")
        vai = nv.get("vai", nv.get("tier", "?"))
        spk_ids = nv.get("speaker_ids") or []
        spk_str = ",".join(spk_ids) if spk_ids else "(không match)"
        tu_xung = nv.get("tu_xung", "?")
        than_phan = nv.get("than_phan", "")
        lines.append(f"  · {zh} ({vi}) - {vai} - tự xưng: {tu_xung} - SPEAKER: {spk_str}")
        if than_phan:
            lines.append(f"    {than_phan}")

    # Speaker mapping summary để AI biết SPEAKER nào tương ứng ai
    sms = bible.get("speaker_mapping_summary") or {}
    if sms:
        lines.append("")
        lines.append("SPEAKER MAPPING (Diarization):")
        for spk_id, info in sms.items():
            matched = info.get("matched_to", "?")
            conf    = info.get("confidence", "?")
            count   = info.get("line_count", 0)
            note    = info.get("note", "")
            lines.append(f"  · {spk_id} → {matched} (confidence={conf}, {count} dòng){' - ' + note if note else ''}")

    return "\n".join(lines)


def _render_scene_characters(scene: dict, bible: dict) -> str:
    """Render danh sách nhân vật của 1 scene cho Pass 2 Speaker."""
    nhan_vat_zh = scene.get("nhan_vat") or []
    all_nv = bible.get("nhan_vat") or []
    by_zh = {nv.get("zh"): nv for nv in all_nv}

    lines = []
    for zh in nhan_vat_zh:
        nv = by_zh.get(zh)
        if not nv:
            lines.append(f"  · {zh} (không tìm thấy trong Bible)")
            continue
        vi = nv.get("vi", "?")
        spk_ids = nv.get("speaker_ids") or []
        spk_str = ",".join(spk_ids) if spk_ids else "(?)"
        lines.append(f"  · {zh} → {vi} (SPEAKER: {spk_str})")
    return "\n".join(lines) if lines else "  (Không có nhân vật trong scene)"


async def pass2_speaker_for_scene(
    scene: dict,
    bible: dict,
    srt_blocks: list[dict],
    api_key: str,
    model: str,
    on_retry=None,
) -> tuple[list[dict], dict]:
    """
    Pass 2 Speaker cho 1 scene — AI gán speaker chính thức cho từng dòng.

    Input:
      scene: 1 entry từ scene_map (có tu_dong, den_dong, nhan_vat)
      bible: Bible đầy đủ (nhân vật + speaker_mapping_summary)
      srt_blocks: subtitles có sẵn speaker từ Diarization (field "speaker")

    Output:
      ([{"index", "speaker_zh", "confidence", "reason"}], api_result)
    """
    tu_dong = scene.get("tu_dong", 0)
    den_dong = scene.get("den_dong", 0)

    # Lấy subtitles trong scene
    scene_blocks = [b for b in srt_blocks if tu_dong <= b["index"] <= den_dong]
    if not scene_blocks:
        return [], {"tokens_in": 0, "tokens_out": 0, "timing_ms": 0}

    # Render SRT chunk
    srt_lines = []
    for b in scene_blocks:
        spk = b.get("speaker") or "?"
        srt_lines.append(f"{b['index']}|{spk}|{b['text']}")
    srt_chunk = "\n".join(srt_lines)

    # Render Bible + nhân vật trong scene
    bible_summary = _render_bible_summary_for_speaker(bible)
    chars_in_scene = _render_scene_characters(scene, bible)

    prompt_tpl = (PROMPTS_DIR / "pass2_speaker.txt").read_text(encoding="utf-8")
    prompt = (prompt_tpl
              .replace("{CHARACTERS_IN_SCENE}", chars_in_scene)
              .replace("{BIBLE_SUMMARY}",       bible_summary)
              .replace("{SRT_CHUNK}",           srt_chunk))

    result = await _call_api(
        prompt, api_key, model,
        temperature=0.1,  # Thấp để quyết định ổn định
        response_json=True,
        max_output=32768,    # Tăng từ 16k → 32k vì scene lớn output > 12k
        on_retry=on_retry,
        thinking_budget=4096,
    )

    text = result["text"]
    finish_reason = result.get("finish_reason", "")
    if finish_reason == "MAX_TOKENS":
        raise RuntimeError(
            f"Pass 2 Speaker scene {scene.get('stt')} bị cắt token. "
            f"tokens_out={result['tokens_out']}\nĐầu response:\n{text[:1500]}"
        )

    data = _parse_json_with_fallback(text, f"Pass2Speaker scene {scene.get('stt')}",
                                      finish_reason, result["tokens_out"])
    speakers = data.get("speakers") or []
    result["prompt"] = prompt
    return speakers, result


async def pass2_speaker_analyze(
    bible: dict,
    srt_blocks: list[dict],
    api_key: str,
    model: str,
    on_retry=None,
    on_progress=None,
    concurrency: int = 3,
) -> tuple[list[dict], dict]:
    """
    Pass 2 Speaker — Gán speaker cho TẤT CẢ dòng phụ đề.

    Chạy SONG SONG theo scene_map (mỗi scene 1 API call).

    Trả về (all_speakers, api_result)
      all_speakers: [{"index", "speaker_zh", "confidence", "reason"}, ...]
                    Đủ cho mọi dòng từ tu_dong scene đầu đến den_dong scene cuối.
    """
    scene_map = bible.get("scene_map") or []
    if not scene_map:
        raise RuntimeError("Bible không có scene_map. Cần chạy Pass 1B trước.")

    if on_progress:
        try:
            await on_progress("pass2_start", f"Pass 2 Speaker: gán speaker cho {len(scene_map)} đoạn...")
        except Exception:
            pass

    # Chạy song song với semaphore
    sem = asyncio.Semaphore(concurrency)
    total_tokens_in = 0
    total_tokens_out = 0
    t0 = time.monotonic()

    results_lock = asyncio.Lock()
    all_speakers: list[dict] = []
    done_count = [0]

    async def _run_scene(idx: int, scene: dict):
        async with sem:
            try:
                speakers, api_result = await pass2_speaker_for_scene(
                    scene, bible, srt_blocks, api_key, model, on_retry=on_retry,
                )
                async with results_lock:
                    all_speakers.extend(speakers)
                    nonlocal_tokens_in_out = (api_result.get("tokens_in", 0),
                                              api_result.get("tokens_out", 0))
                    done_count[0] += 1
                if on_progress:
                    try:
                        await on_progress(
                            "pass2_scene_done",
                            f"Pass 2: xong scene {idx+1}/{len(scene_map)} ({len(speakers)} dòng)",
                        )
                    except Exception:
                        pass
                return api_result
            except Exception as e:
                logger.error(f"[Pass2 scene {idx}] Lỗi: {e}", exc_info=True)
                if on_progress:
                    try:
                        await on_progress(
                            "pass2_scene_err",
                            f"Scene {idx+1} lỗi: {e}",
                        )
                    except Exception:
                        pass
                return {"tokens_in": 0, "tokens_out": 0, "timing_ms": 0}

    tasks = [_run_scene(i, sc) for i, sc in enumerate(scene_map)]
    sub_results = await asyncio.gather(*tasks)

    for r in sub_results:
        total_tokens_in  += r.get("tokens_in", 0) or 0
        total_tokens_out += r.get("tokens_out", 0) or 0

    # Sắp xếp theo index
    all_speakers.sort(key=lambda x: x.get("index", 0))

    timing_ms = int((time.monotonic() - t0) * 1000)
    if on_progress:
        try:
            await on_progress("pass2_done",
                              f"Pass 2 xong — gán {len(all_speakers)} dòng trong {timing_ms}ms")
        except Exception:
            pass

    return all_speakers, {
        "tokens_in":  total_tokens_in,
        "tokens_out": total_tokens_out,
        "timing_ms":  timing_ms,
        "scene_count": len(scene_map),
    }


# ─────────────────────────────────────────────
# PASS 2 — CHIA CHUNK THEO SCENE_MAP
# ─────────────────────────────────────────────

def build_chunks_from_bible(
    srt_blocks: list[dict],
    bible: dict,
    hard_max: int = 280,
    target_size: int = 200,   # giữ tham số cho backward-compat, không dùng
) -> list[dict]:
    """
    Chia chunks dịch dựa trên scene_map từ Bible.

    TIN PASS 1 chia scene đúng kích thước (150-250 dòng theo prompt).
    Hàm này chỉ làm 1 việc kỹ thuật: lấy đúng dòng SRT cho mỗi scene.

    Safety net DUY NHẤT: nếu scene bị Gemini chia > hard_max (280) thì
    split tại timestamp gap lớn nhất, đánh dấu "Phần x/y" và share
    scene_info. Trường hợp này hiếm vì prompt đã ép trần 250 dòng.

    KHÔNG còn merge — Pass 1 đã tự đảm bảo sàn 150 dòng.
    """
    scene_map = bible.get("scene_map", [])

    if not scene_map:
        # Fallback: chia đều 200 dòng nếu không có scene_map
        chunks = []
        for i in range(0, len(srt_blocks), 200):
            sl = srt_blocks[i:i + 200]
            chunks.append({
                "index":       len(chunks),
                "blocks":      sl,
                "scene_info":  None,
                "tom_tat":     "",
                "part_info":   "",
            })
        return chunks

    # Build raw_chunks: mỗi item = (blocks, scene, part_idx, total_parts)
    # Tin Pass 1 đã chia scene đúng kích thước (150-250 dòng). Code chỉ làm
    # safety net: split nếu Gemini lỡ chia scene > hard_max.
    raw_chunks = []
    for scene in scene_map:
        s = scene.get("tu_dong") or scene.get("dong_bat_dau", 0)
        e = scene.get("den_dong") or scene.get("dong_ket_thuc", 999999)
        scene_blocks = [b for b in srt_blocks if s <= b["index"] <= e]
        if not scene_blocks:
            continue

        if len(scene_blocks) <= hard_max:
            # Trường hợp thường — Pass 1 chia đúng kích thước
            raw_chunks.append((scene_blocks, scene, 1, 1))
        else:
            # Safety net: scene quá lớn → split kỹ thuật
            splits = _find_split_points(scene_blocks, hard_max)
            total = len(splits)
            for idx, sl in enumerate(splits, start=1):
                raw_chunks.append((sl, scene, idx, total))

    # KHÔNG merge nữa — tin Pass 1 chia chuẩn

    # Build chunk list
    chunks = []
    for idx, (blocks, scene, part_idx, total_parts) in enumerate(raw_chunks):
        if total_parts > 1:
            part_info = f"Phần {part_idx}/{total_parts} của phân cảnh dài"
        else:
            part_info = ""
        chunks.append({
            "index":       idx,
            "blocks":      blocks,
            "scene_info":  scene,
            "tom_tat":     scene.get("tom_tat", "") if scene else "",
            "part_info":   part_info,
            "part_idx":    part_idx,
            "total_parts": total_parts,
        })
    return chunks



def _find_split_points(blocks: list[dict], max_size: int) -> list[list[dict]]:
    """
    Split list of blocks thành các nhóm <= max_size.
    Cắt tại timestamp gap lớn nhất trong vùng giữa, để chunk con cân đối
    và không cắt giữa cuộc đối thoại đang diễn ra.
    """
    if len(blocks) <= max_size:
        return [blocks]

    # Tính gap (ms) giữa các block: gap[i] = block[i].start - block[i-1].end
    gaps = []
    for i in range(1, len(blocks)):
        try:
            prev_end = _ts_to_ms(blocks[i-1]["end"])
            cur_start = _ts_to_ms(blocks[i]["start"])
            gaps.append((cur_start - prev_end, i))
        except Exception:
            gaps.append((0, i))

    result = []
    start = 0
    while start < len(blocks):
        remaining = len(blocks) - start
        if remaining <= max_size:
            # Đoạn cuối — không cần split nữa
            result.append(blocks[start:])
            break

        # Vùng tìm điểm cắt: tránh chunk con quá nhỏ ở cả hai đầu.
        # Cắt trong khoảng [start + 40%·max_size, start + max_size].
        min_cut = start + max(40, int(max_size * 0.4))
        max_cut = start + max_size
        # Đảm bảo phần còn lại sau khi cắt không quá nhỏ (>= 30% max_size)
        max_cut = min(max_cut, len(blocks) - max(30, int(max_size * 0.3)))
        if max_cut <= min_cut:
            max_cut = start + max_size  # fallback nếu vùng hẹp quá

        local_gaps = [(g, i) for g, i in gaps if min_cut <= i <= max_cut]
        if local_gaps:
            # Khi nhiều gap bằng nhau, chọn vị trí gần "điểm cắt lý tưởng"
            # (start + 85% max_size) — chunk 1 tận dụng tối đa size.
            target = start + int(max_size * 0.85)
            # Sort: gap LỚN trước, rồi vị trí GẦN target trước
            local_gaps.sort(key=lambda x: (-x[0], abs(x[1] - target)))
            best_split = local_gaps[0][1]
        else:
            best_split = min(start + max_size, len(blocks))

        result.append(blocks[start:best_split])
        start = best_split

    return result


def _ts_to_ms(ts: str) -> int:
    try:
        ts = ts.replace(",", ".")
        parts = ts.split(":")
        h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
        return int((h * 3600 + m * 60 + s) * 1000)
    except Exception:
        return 0


# ─────────────────────────────────────────────
# PASS 3 — DỊCH TỪNG CHUNK (TOKEN-OPTIMIZED)
# ─────────────────────────────────────────────

def _resolve_relevant_chars(
    chunk_blocks: list[dict],
    scene_info: dict,
    bible: dict,
) -> list[dict]:
    """
    Quyết định nhân vật nào "có mặt" trong chunk này (= sẽ được đưa vào prompt).

    Quy tắc lọt — UNION của 4 nguồn:
    1. Nhân vật được Pass 1 liệt kê trong scene.nhan_vat (source of truth).
    2. Nhân vật có tên Hán (zh) xuất hiện trong text của chunk.
    3. Nhân vật chính (vai = nu_chinh / nam_chinh) — LUÔN có mặt.
    4. Nhân vật không có tên riêng (zh là vai trò như 妈妈/老爸/大哥) —
       match bằng cách gọi thân mật trong thoại (老温/妈/爸/哥 v.v.)
       hoặc bằng quan hệ gia đình suy từ context.
    """
    nhan_vat_list = bible.get("nhan_vat", [])
    if not nhan_vat_list:
        return []

    chunk_text = " ".join(b["text"] for b in chunk_blocks)
    scene_nv = set(scene_info.get("nhan_vat", []) if scene_info else [])

    # Tập các cách gọi thân mật → ánh xạ đến zh pattern
    # Key: chuỗi xuất hiện trong thoại, Value: hàm kiểm tra NV có khớp không
    FAMILIAR_CALLS = {
        # Gọi bố/mẹ theo họ: "老温" → bố/mẹ họ Ôn
        # Detect pattern: "老" + họ (ký tự đầu của zh)
        # Xử lý riêng bên dưới
        "妈":    lambda nv: any(k in nv.get("zh","") for k in ["妈","母"]) or "mẹ" in nv.get("vi","").lower(),
        "妈妈":  lambda nv: any(k in nv.get("zh","") for k in ["妈","母"]) or "mẹ" in nv.get("vi","").lower(),
        "爸":    lambda nv: any(k in nv.get("zh","") for k in ["爸","父"]) or "bố" in nv.get("vi","").lower() or "ba" in nv.get("vi","").lower(),
        "爸爸":  lambda nv: any(k in nv.get("zh","") for k in ["爸","父"]) or "bố" in nv.get("vi","").lower(),
        "哥":    lambda nv: "哥" in nv.get("zh","") or "anh" in nv.get("vi","").lower(),
        "大哥":  lambda nv: "哥" in nv.get("zh","") or "anh" in nv.get("vi","").lower(),
        "姐":    lambda nv: "姐" in nv.get("zh","") or "chị" in nv.get("vi","").lower(),
        "弟":    lambda nv: "弟" in nv.get("zh","") or "em trai" in nv.get("vi","").lower(),
        "妹":    lambda nv: "妹" in nv.get("zh","") or "em gái" in nv.get("vi","").lower(),
        "奶奶":  lambda nv: "奶" in nv.get("zh","") or "bà" in nv.get("vi","").lower(),
        "爷爷":  lambda nv: "爷" in nv.get("zh","") or "ông" in nv.get("vi","").lower(),
        "老公":  lambda nv: nv.get("vai") in ("nam_chinh", "phu") and any(k in nv.get("than_phan","") for k in ["chồng","husband"]),
        "老婆":  lambda nv: nv.get("vai") in ("nu_chinh", "phu") and any(k in nv.get("than_phan","") for k in ["vợ","wife"]),
    }

    relevant = []
    for nv in nhan_vat_list:
        zh = nv.get("zh", "")
        vai = nv.get("vai", "")

        # Nguồn 1: scene.nhan_vat từ Pass 1
        if zh in scene_nv:
            relevant.append(nv)
            continue

        # Nguồn 2: tên Hán xuất hiện trực tiếp trong chunk text
        if zh and zh in chunk_text:
            relevant.append(nv)
            continue

        # Nguồn 3: nhân vật chính luôn có mặt
        if vai in ("nu_chinh", "nam_chinh"):
            relevant.append(nv)
            continue

        # Nguồn 4a: match cách gọi thân mật cố định
        matched_familiar = False
        for call, fn in FAMILIAR_CALLS.items():
            if call in chunk_text:
                try:
                    if fn(nv):
                        matched_familiar = True
                        break
                except Exception:
                    pass
        if matched_familiar:
            relevant.append(nv)
            continue

        # Nguồn 4b: pattern "老X" — gọi ai đó theo họ kiểu thân mật
        # Ví dụ "老温" → match NV có zh bắt đầu bằng "温"
        import re as _re
        for m in _re.finditer(r"老(\w)", chunk_text):
            surname = m.group(1)
            if zh.startswith(surname) and len(zh) >= 2:
                relevant.append(nv)
                break

    return relevant


def _build_people_in_scene(
    chunk_blocks: list[dict],
    scene_info: dict,
    bible: dict,
) -> str:
    """
    Liệt kê người có mặt trong cảnh + quan hệ nổi bật giữa họ.
    Hiển thị ở phần đầu prompt để AI nắm ngay "đây là cuộc thoại của ai với ai".
    """
    relevant = _resolve_relevant_chars(chunk_blocks, scene_info, bible)
    if not relevant:
        return "(Không xác định được nhân vật trong phân cảnh này)"

    # Liệt kê ngắn: tên + vai
    vai_label = {
        "nu_chinh":  "nữ chính",
        "nam_chinh": "nam chính",
        "phan_dien": "phản diện",
        "phu":       "phụ",
    }
    people_lines = []
    for nv in relevant:
        vi = nv.get("vi", nv.get("zh", ""))
        zh = nv.get("zh", "")
        vai = vai_label.get(nv.get("vai", ""), nv.get("vai", "phụ"))
        than_phan = nv.get("than_phan", "")
        line = f"• {vi} ({zh}) — {vai}"
        if than_phan:
            line += f": {than_phan}"
        people_lines.append(line)

    # Quan hệ nổi bật: lọt nếu CÓ ÍT NHẤT 1 nhân vật của cặp thuộc relevant
    # (không bắt buộc cả hai phải có tên trong text)
    relevant_zh = {nv.get("zh") for nv in relevant}
    quan_he_list = bible.get("quan_he_noi_bat", [])
    relevant_rel = []
    for rel in quan_he_list:
        parts = rel.split(":", 1)
        if len(parts) != 2:
            continue
        pair = parts[0].strip()
        desc = parts[1].strip()
        names = [n.strip() for n in pair.replace("↔", "|").split("|")]
        # Cặp lọt khi cả 2 phía đều thuộc relevant (mới gọi là "có mặt cùng lúc")
        if all(n in relevant_zh for n in names if n):
            relevant_rel.append(f"  [{pair}]: {desc}")

    result = "\n".join(people_lines)
    if relevant_rel:
        result += "\n\nQuan hệ giữa họ:\n" + "\n".join(relevant_rel[:5])
    return result


def _render_matrix_dict(matrix: dict) -> list[str]:
    """Render 1 matrix dict (có thể value là string hoặc dict multi-state)."""
    STATE_LABELS = {
        "mac_dinh":     "bình thường",
        "mac_dinh_dau": "giai đoạn đầu",
        "than_mat":     "thân mật/yêu",
        "gian_duc":     "giận/cãi",
        "cat_tinh":     "cắt tình/lạnh",
        "de_doa":       "đe dọa",
        "gia_ta":       "giả tạo bề ngoài",
        "ghi_chu":      "⚠ lưu ý",
    }
    lines = []
    for pair, rule in matrix.items():
        if isinstance(rule, dict):
            lines.append(f"• {pair}:")
            for key, label in STATE_LABELS.items():
                if rule.get(key):
                    lines.append(f"    [{label}] {rule[key]}")
        else:
            lines.append(f"• {pair}: {rule}")
    return lines


def _build_xung_ho_matrix(chunk_blocks: list[dict], bible: dict, scene_info: dict = None) -> str:
    """
    Build xưng hô matrix 2 tầng:
      Tầng 1 (nền): xung_ho_toan_phim từ Bible — tất cả cặp trong phim
      Tầng 2 (override): matrix_xung_ho trong scene — chỉ ghi trạng thái đặc biệt của scene này

    Pass 3 đọc cả 2: nền cho context toàn phim, override cho cảnh hiện tại.
    """
    parts = []

    # Tầng 1 — toàn phim (nền chung)
    toan_phim = bible.get("xung_ho_toan_phim", {})
    if toan_phim:
        parts.append("XƯNG HÔ TOÀN PHIM (áp dụng khi không có thông tin cụ thể hơn):")
        parts.extend(_render_matrix_dict(toan_phim))

    # Tầng 2 — scene cụ thể (override)
    if scene_info and "matrix_xung_ho" in scene_info:
        scene_matrix = scene_info["matrix_xung_ho"]
        if scene_matrix:
            if parts:
                parts.append("")  # blank line separator
            parts.append("XƯNG HÔ TRONG CẢNH NÀY (ưu tiên hơn toàn phim):")
            parts.extend(_render_matrix_dict(scene_matrix))

    if parts:
        return "\n".join(parts)

    return "(Dùng xưng hô mặc định theo quan hệ nhân vật)"

def _get_tone_rules(scene_info: dict) -> str:
    """Lấy rules dựa trên tone của scene.

    Hỗ trợ 2 dạng tone từ Bible:
      - Mới (enum list): ["lanh_lung", "can_thang"]
      - Cũ (string tự do): "lạnh lùng → căng thẳng"
    """
    if not scene_info:
        return ""

    rules_txt = (PROMPTS_DIR / "tone_rules.txt").read_text(encoding="utf-8")
    sections = re.split(r"\n(?=[a-z_|]+:)", rules_txt.strip())

    raw = scene_info.get("tone")
    if raw is None:
        return ""

    # Trường hợp enum list mới
    if isinstance(raw, list):
        valid_keys = {"bi_thuong", "can_thang", "hai_huoc", "am_ap",
                      "lanh_lung", "trung_tinh"}
        keys = []
        for item in raw:
            if isinstance(item, str):
                k = item.strip().lower()
                if k in valid_keys and k not in keys:
                    keys.append(k)
        if not keys:
            return ""
        out = []
        for key in keys[:2]:
            for section in sections:
                if section.startswith(key):
                    out.append(section.strip())
                    break
        return "\n\n".join(out)

    # Backward compat: string cũ
    tone_str = str(raw).lower() if raw else ""
    if any(k in tone_str for k in ["bi thương", "phẫn uất", "cay đắng", "đau", "khóc"]):
        key = "bi_thuong"
    elif any(k in tone_str for k in ["căng thẳng", "đối đầu", "quyết liệt", "phẫn nộ"]):
        key = "can_thang"
    elif any(k in tone_str for k in ["hài hước", "tán tỉnh", "ngượng", "vui"]):
        key = "hai_huoc"
    elif any(k in tone_str for k in ["ấm áp", "thấu hiểu", "quyết tâm", "hy vọng"]):
        key = "am_ap"
    elif any(k in tone_str for k in ["lạnh lùng", "bá đạo", "ngạo", "thờ ơ"]):
        key = "lanh_lung"
    else:
        return ""

    for section in sections:
        if section.startswith(key):
            return section.strip()
    return ""


def _safe_read(filename: str) -> str:
    """Đọc file trong PROMPTS_DIR, trả "" nếu không tồn tại."""
    path = PROMPTS_DIR / filename
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _get_xung_ho_rules(bible: dict) -> str:
    """
    Load bảng xưng hô theo bối cảnh phim.
    boi_canh ∈ {do_thi, co_trang, dan_quoc, tien_hiep}.
    """
    the_loai = bible.get("the_loai", {})
    boi_canh = the_loai.get("boi_canh", "do_thi")

    # Map bối cảnh cũ (cho Bible đã sinh trước thay đổi schema)
    legacy_map = {
        "hien_dai": "do_thi",
        "co_dai":   "co_trang",
        "huyen_huyen": "tien_hiep",
    }
    boi_canh = legacy_map.get(boi_canh, boi_canh)

    if boi_canh not in {"do_thi", "co_trang", "dan_quoc", "tien_hiep"}:
        boi_canh = "do_thi"  # fallback an toàn

    return _safe_read(f"xung_ho_{boi_canh}.txt")



def _get_chuyen_xung_ho_rules() -> str:
    """Load file quy tắc đổi xưng hô — luôn dùng cho mọi phim."""
    return _safe_read("chuyen_xung_ho.txt")


def _get_thuat_ngu_rules() -> str:
    """Load bảng thuật ngữ chuyên môn — luôn dùng."""
    return _safe_read("thuat_ngu_chuyen.txt")


def _get_genre_rules(bible: dict, scene_info: dict = None) -> str:
    """
    Tổng hợp tất cả rule cho phim:
    1. Bảng xưng hô theo bối cảnh (do_thi / co_trang / dan_quoc / tien_hiep)
    2. Quy tắc đổi xưng hô khi cảm xúc thay đổi
    3. Rules theo từng yếu tố — CHỈ những yếu tố liên quan đến scene hiện tại
    4. Bảng dịch thuật ngữ chuyên môn
    """
    parts = []

    xh = _get_xung_ho_rules(bible)
    if xh:
        parts.append(xh)

    cxh = _get_chuyen_xung_ho_rules()
    if cxh:
        parts.append(cxh)

    tn = _get_thuat_ngu_rules()
    if tn:
        parts.append(tn)

    return "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n".join(parts)


def build_pass3_prompt(
    chunk: dict,
    bible: dict,
    previous_tail_zh: str = "",
    previous_tail_vi: str = "",
    next_preview_zh: str = "",
) -> str:
    """
    Build prompt Pass 3 với đầy đủ context:
    - STORY_SUMMARY: tóm tắt phim từ Bible
    - SCENE_SUMMARY: nội dung + bối cảnh + tone phân cảnh hiện tại
    - CHUNK_PART_INFO: nếu chunk này là phần x/y của phân cảnh dài
    - PEOPLE_IN_SCENE: người có mặt + quan hệ
    - XUNG_HO_MATRIX: tự xưng + cách gọi nhau
    - CONTEXT_BEFORE: 5 dòng cuối chunk trước (Trung + Việt nếu đã dịch)
    - CONTEXT_AFTER: 3 dòng đầu chunk sau (Trung — để hiểu mạch tiếp theo)
    """
    blocks      = chunk["blocks"]
    scene_info  = chunk.get("scene_info") or {}
    tom_tat     = chunk.get("tom_tat") or scene_info.get("tom_tat", "")
    # Schema mới: "dia_diem". Schema cũ: "boi_canh".
    dia_diem    = scene_info.get("dia_diem", "") or scene_info.get("boi_canh", "")
    thoi_gian   = scene_info.get("thoi_gian", "")
    # Tone có thể là list (enum mới) hoặc string (cũ)
    tone_raw    = scene_info.get("tone", "")
    if isinstance(tone_raw, list):
        tone = ", ".join(str(t) for t in tone_raw if t)
    else:
        tone = str(tone_raw) if tone_raw else ""
    ghi_chu     = scene_info.get("ghi_chu", "")
    part_info   = chunk.get("part_info", "") or ""

    # STORY SUMMARY
    story_summary = (
        bible.get("story_arc", {}).get("tom_tat_phim", "")
        or "(Không có tóm tắt phim)"
    )

    # SCENE SUMMARY
    scene_parts = []
    if tom_tat:   scene_parts.append(f"Nội dung: {tom_tat}")
    if dia_diem:  scene_parts.append(f"Địa điểm: {dia_diem}")
    if thoi_gian: scene_parts.append(f"Thời gian: {thoi_gian}")
    if tone:      scene_parts.append(f"Tone: {tone}")
    if ghi_chu:   scene_parts.append(f"Lưu ý: {ghi_chu}")
    scene_summary = "\n".join(scene_parts) if scene_parts else "(Không có thông tin phân cảnh)"

    # CHUNK PART INFO — chỉ hiển thị khi là phần x/y của phân cảnh dài
    if part_info:
        chunk_part_info = (
            f"⚠ {part_info}. Cảnh này được tách kỹ thuật để dịch — "
            f"các phần khác cùng tom_tat, cùng nhân vật, cùng tone. "
            f"Hãy giữ giọng nhất quán với các phần còn lại."
        )
    else:
        chunk_part_info = ""

    # PEOPLE IN SCENE
    people_in_scene = _build_people_in_scene(blocks, scene_info, bible)

    # XƯNG HÔ MATRIX
    xung_ho = _build_xung_ho_matrix(blocks, bible, scene_info)

    # CONTEXT BEFORE (chunk trước)
    context_before = ""
    if previous_tail_zh.strip() or previous_tail_vi.strip():
        parts = ["━" * 30, "MẠCH TRƯỚC ĐÓ (3-5 dòng cuối chunk trước, để giữ giọng và mạch nối):"]
        if previous_tail_zh.strip():
            parts.append(f"Tiếng Trung:\n{previous_tail_zh.strip()}")
        if previous_tail_vi.strip():
            parts.append(f"Bản dịch tiếng Việt đã có:\n{previous_tail_vi.strip()}")
        context_before = "\n".join(parts)

    # CONTEXT AFTER (chunk sau) — chỉ tiếng Trung, để AI hiểu mạch tiếp theo
    context_after = ""
    if next_preview_zh.strip():
        context_after = (
            "━" * 30 + "\n"
            "MẠCH KẾ TIẾP (3-5 dòng đầu của chunk sau, KHÔNG cần dịch — chỉ "
            "để bạn hiểu cảnh tiếp diễn ra sao và chọn từ kết phù hợp):\n"
            f"{next_preview_zh.strip()}"
        )

    # TONE RULES + GENRE RULES
    tone_rules = _get_tone_rules(scene_info)
    genre_rules = _get_genre_rules(bible, scene_info)

    # SRT INPUT — format có speaker nếu có
    # Pipeline mới (sau Pass 2 Speaker): blocks có field "speaker_zh"
    # Backward compat: nếu không có speaker_zh → render format cũ
    has_speaker = any(b.get("speaker_zh") for b in blocks)
    if has_speaker:
        srt_input = "\n".join(
            f"{b['index']}|{b.get('speaker_zh') or '?'}|{b['text']}" for b in blocks
        )
    else:
        srt_input = "\n".join(f"{b['index']}|{b['text']}" for b in blocks)

    # BUILD PROMPT
    prompt_tpl = (PROMPTS_DIR / "pass3_translate.txt").read_text(encoding="utf-8")
    return (prompt_tpl
            .replace("{STORY_SUMMARY}",     story_summary)
            .replace("{SCENE_SUMMARY}",     scene_summary)
            .replace("{CHUNK_PART_INFO}",   chunk_part_info)
            .replace("{PEOPLE_IN_SCENE}",   people_in_scene)
            .replace("{XUNG_HO_MATRIX}",    xung_ho)
            .replace("{CONTEXT_BEFORE}",    context_before)
            .replace("{CONTEXT_AFTER}",     context_after)
            .replace("{TONE_RULES}",        tone_rules)
            .replace("{GENRE_RULES}",       genre_rules)
            .replace("{SRT_INPUT}",         srt_input))

def parse_pass3_output(text: str, original_blocks: list[dict]) -> list[dict]:
    """
    Parse output format: số|speaker|thoại  (hoặc số|thoại nếu không có speaker)
    """
    text = re.sub(r"```\w*\s*", "", text).replace("```", "").strip()
    valid = {b["index"] for b in original_blocks}
    result = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Format mới: số|speaker|thoại
        m3 = re.match(r"^(\d+)\s*[|｜]\s*([^|｜]*)\s*[|｜]\s*(.+)$", line)
        if m3:
            idx = int(m3.group(1))
            if idx in valid:
                result.append({
                    "index":   idx,
                    "speaker": m3.group(2).strip(),
                    "text":    m3.group(3).strip(),
                })
            continue
        # Format cũ fallback: số|thoại
        m2 = re.match(r"^(\d+)\s*[|｜:：]\s*(.+)$", line)
        if m2:
            idx = int(m2.group(1))
            if idx in valid:
                result.append({
                    "index":   idx,
                    "speaker": "",
                    "text":    m2.group(2).strip(),
                })
    return result

async def pass3_translate_chunk(
    chunk: dict,
    bible: dict,
    previous_tail_zh: str = "",
    previous_tail_vi: str = "",
    next_preview_zh: str = "",
    api_key: str = "",
    model: str = "",
) -> tuple[list[dict], dict]:
    """
    Dịch 1 chunk. Trả về (translated_entries, call_info).
    translated_entries: [{index, timestamp, original_text, translated_text}]

    Args:
      previous_tail_zh: 3-5 dòng cuối chunk trước (tiếng Trung) — luôn nên có
      previous_tail_vi: 3-5 dòng cuối chunk trước đã dịch (tiếng Việt) — nếu đã dịch xong
      next_preview_zh: 3-5 dòng đầu chunk kế tiếp (tiếng Trung) — để biết mạch tiếp theo
    """
    blocks = chunk["blocks"]
    prompt = build_pass3_prompt(
        chunk, bible,
        previous_tail_zh=previous_tail_zh,
        previous_tail_vi=previous_tail_vi,
        next_preview_zh=next_preview_zh,
    )

    for attempt in range(3):
        try:
            result = await _call_api(
                prompt, api_key, model,
                temperature=0.35,
                max_output=16384,   # Nâng để chunk to (~300 dòng) có chỗ thở
                thinking_budget=0,  # Pass 3: tắt thinking → dịch nhanh hơn 3-5x
            )
            translated = parse_pass3_output(result["text"], blocks)
            trans_dict    = {t["index"]: t["text"]    for t in translated}
            speaker_dict  = {t["index"]: t.get("speaker", "") for t in translated}

            entries = []
            for b in blocks:
                entries.append({
                    "index":           b["index"],
                    "timestamp":       f"{b['start']} --> {b['end']}",
                    "original_text":   b["text"],
                    "translated_text": trans_dict.get(b["index"], b["text"]),
                    "speaker":         speaker_dict.get(b["index"], ""),
                })

            call_info = {
                "prompt":     prompt,
                "response":   result["text"],
                "tokens_in":  result["tokens_in"],
                "tokens_out": result["tokens_out"],
                "timing_ms":  result["timing_ms"],
            }
            return entries, call_info

        except Exception as e:
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)

    return [], {}


# ─────────────────────────────────────────────
# PASS 4 — QC REVIEW
# ─────────────────────────────────────────────

def _coerce_to_str(val, sep: str = "; ") -> str:
    """
    Bible có nhiều field model có thể trả về dưới dạng string HOẶC list of strings
    (vd: kieu_noi, tu_xung, nhan_vat trong scene...).
    Helper này coerce thành string, an toàn cho cả None/dict/số.
    """
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, (list, tuple)):
        parts = []
        for x in val:
            if isinstance(x, str) and x.strip():
                parts.append(x.strip())
            elif x is not None:
                parts.append(str(x).strip())
        return sep.join(p for p in parts if p)
    # dict / số / khác → cast sang str
    return str(val).strip()


def _build_nhan_vat_summary(bible: dict, scene_chars_zh: list[str] | None = None) -> str:
    """
    Tóm tắt nhân vật. Nếu truyền `scene_chars_zh` → CHỈ render những nhân vật có
    trong scene đang xét (tiết kiệm ~200 token/chunk vì không render full list 10-15 người).
    Fallback: render full nếu scene_chars rỗng hoặc không match được ai.
    """
    nv_list = bible.get("nhan_vat", []) or []

    if scene_chars_zh:
        scene_set = set(scene_chars_zh)
        filtered = [nv for nv in nv_list if nv.get("zh", "") in scene_set]
        # Nếu khớp được ≥1 thì dùng filtered, không thì fallback full để vẫn có info
        if filtered:
            nv_list = filtered

    lines = []
    for nv in nv_list:
        zh       = _coerce_to_str(nv.get("zh"))
        vi       = _coerce_to_str(nv.get("vi"))
        vai      = _coerce_to_str(nv.get("vai"))
        tu_xung  = _coerce_to_str(nv.get("tu_xung"), sep=" / ")
        kieu_noi = _coerce_to_str(nv.get("kieu_noi"), sep="; ")
        parts = [f"• {zh}={vi} ({vai}) tự xưng: {tu_xung}"]
        if kieu_noi:
            # Cắt ngắn kieu_noi để gọn (lấy 80 ký tự đầu)
            kn = kieu_noi if len(kieu_noi) <= 80 else kieu_noi[:77] + "..."
            parts.append(f"  kiểu nói: {kn}")
        lines.append("\n".join(parts))
    return "\n".join(lines) or "(Không có)"


def _build_thuat_ngu_summary(bible: dict, entries: list[dict] | None = None) -> str:
    """
    Tóm tắt thuật ngữ. Nếu truyền `entries` → CHỈ render term có XUẤT HIỆN trong
    nội dung chunk (so khớp substring trong original_text). Tiết kiệm ~100 token/chunk.
    """
    tn_raw = bible.get("thuat_ngu", {})
    if not tn_raw:
        return "(Không có)"

    # Normalize thuat_ngu thành dict {zh: vi_string}.
    # Model có thể trả: dict {zh: vi}, hoặc list of {zh, vi}, hoặc value là list.
    tn: dict[str, str] = {}
    if isinstance(tn_raw, dict):
        for zh, vi in tn_raw.items():
            if zh:
                tn[str(zh)] = _coerce_to_str(vi, sep=" / ")
    elif isinstance(tn_raw, list):
        for item in tn_raw:
            if isinstance(item, dict):
                zh = item.get("zh") or item.get("term") or ""
                vi = item.get("vi") or item.get("translation") or ""
                if zh:
                    tn[str(zh)] = _coerce_to_str(vi, sep=" / ")

    if not tn:
        return "(Không có)"

    if entries:
        # Gom toàn bộ original_text thành 1 string để check substring
        haystack = "\n".join((e.get("original_text") or "") for e in entries)
        filtered = {zh: vi for zh, vi in tn.items() if zh and zh in haystack}
        if filtered:
            tn = filtered
        # Nếu không match được term nào → vẫn render full (chunk có thể không có
        # term đặc biệt, nhưng AI vẫn nên biết để spot khi cần)

    return "\n".join(f"• {zh}→{vi}" for zh, vi in tn.items())


def _build_turning_points_summary(bible: dict, scene_range: tuple[int, int] | None = None) -> str:
    """
    Tóm tắt turning points xưng hô. Nếu truyền `scene_range=(from, to)` → CHỈ render
    turning point có dòng nằm trong hoặc gần scene (±50 dòng). Tiết kiệm ~150 token/chunk.
    """
    tp = bible.get("turning_points_xung_ho", []) or []
    if not tp:
        return "(Không có)"

    # Coerce mỗi item về string — model đôi khi trả về object {dong, mo_ta} thay vì string
    tp_str: list[str] = []
    for item in tp:
        if isinstance(item, str):
            tp_str.append(item.strip())
        elif isinstance(item, dict):
            # Format: {dong: 400, mo_ta: "..."} hoặc {line: 400, desc: "..."}
            line = item.get("dong") or item.get("line") or item.get("line_num") or ""
            desc = item.get("mo_ta") or item.get("desc") or item.get("description") or ""
            if line and desc:
                tp_str.append(f"dòng ~{line}: {desc}")
            elif desc:
                tp_str.append(str(desc))
            else:
                tp_str.append(str(item))
        else:
            tp_str.append(str(item))
    tp_str = [t for t in tp_str if t]
    if not tp_str:
        return "(Không có)"

    if scene_range:
        from_line, to_line = scene_range
        near = []
        for t in tp_str:
            # Parse số dòng trong text (vd: "Cảnh X (dòng ~400): ...")
            m = re.search(r"dòng\s*~?\s*(\d+)", t)
            if m:
                line_num = int(m.group(1))
                if from_line - 50 <= line_num <= to_line + 50:
                    near.append(t)
            else:
                # Không parse được số → giữ lại để AI vẫn có context
                near.append(t)
        if near:
            tp_str = near

    return "\n".join(f"• {t}" for t in tp_str)


def _build_nhan_vat_trong_canh(scene_info: dict, bible: dict) -> str:
    """
    Trả về danh sách tên Hán Việt của nhân vật trong cảnh (cách dấu phẩy).
    Dùng cho prompt Pass 4 để AI dễ chọn speaker_de_xuat đúng tên.
    """
    scene_chars_raw = scene_info.get("nhan_vat") or []
    if not scene_chars_raw:
        return "(Không xác định)"

    # Coerce mỗi item → mã zh (string). Model có thể trả về:
    # - list[str]: ["苏念", "顾沉舟"]
    # - list[dict]: [{"zh": "苏念", "vi": "Tô Niệm"}, ...]
    scene_chars_zh: list[str] = []
    for item in scene_chars_raw:
        if isinstance(item, str):
            scene_chars_zh.append(item)
        elif isinstance(item, dict):
            zh = item.get("zh") or item.get("name") or ""
            if zh:
                scene_chars_zh.append(str(zh))
        else:
            scene_chars_zh.append(str(item))

    if not scene_chars_zh:
        return "(Không xác định)"

    zh_to_vi = {
        _coerce_to_str(nv.get("zh")): _coerce_to_str(nv.get("vi"))
        for nv in bible.get("nhan_vat", []) or []
    }
    names = []
    for zh in scene_chars_zh:
        vi = zh_to_vi.get(zh, "")
        if vi:
            names.append(vi)
        else:
            # Không có trong Bible → vẫn dùng zh để AI có info
            names.append(zh)
    return ", ".join(names) if names else "(Không xác định)"


def _build_srt_review_input(entries: list[dict]) -> str:
    """
    Format mỗi dòng: `idx|speaker|gốc|dịch`. speaker rỗng → '?'.
    Escape ký tự `|` trong text thành `｜` (fullwidth) để parser không nhầm.
    """
    lines = []
    for e in entries:
        idx     = e["index"]
        speaker = (e.get("speaker") or "").strip() or "?"
        orig    = (e.get("original_text") or "").replace("|", "｜")
        trans   = (e.get("translated_text") or "").replace("|", "｜")
        speaker = speaker.replace("|", "｜")
        lines.append(f"{idx}|{speaker}|{orig}|{trans}")
    return "\n".join(lines)


def build_pass4_prompt(
    chunk: dict,
    bible: dict,
    entries: list[dict],
) -> str:
    scene_info   = chunk.get("scene_info") or {}
    the_loai     = bible.get("the_loai", {})
    boi_canh     = the_loai.get("boi_canh", "do_thi")
    tom_tat      = chunk.get("tom_tat") or scene_info.get("tom_tat", "")
    # Tone có thể là list (enum mới) hoặc string (cũ)
    tone_raw     = scene_info.get("tone", "")
    if isinstance(tone_raw, list):
        tone = ", ".join(str(t) for t in tone_raw if t)
    else:
        tone = str(tone_raw) if tone_raw else ""
    scene_summary = f"{tom_tat} | Tone: {tone}" if tom_tat else "(Không có)"

    # Phạm vi dòng của scene — để trim turning points
    scene_range = None
    tu_dong = scene_info.get("tu_dong")
    den_dong = scene_info.get("den_dong")
    if isinstance(tu_dong, int) and isinstance(den_dong, int):
        scene_range = (tu_dong, den_dong)

    # Nhân vật trong scene (mã zh) — để trim nhan_vat_summary.
    # scene_info.nhan_vat có thể là list[str] hoặc list[dict{zh,vi}].
    scene_chars_raw = scene_info.get("nhan_vat") or []
    scene_chars_zh: list[str] = []
    for item in scene_chars_raw:
        if isinstance(item, str):
            scene_chars_zh.append(item)
        elif isinstance(item, dict):
            zh = item.get("zh") or item.get("name") or ""
            if zh:
                scene_chars_zh.append(str(zh))

    # Matrix: chỉ render scene matrix + nhánh toan_phim của cặp có nhân vật trong scene
    matrix = scene_info.get("matrix_xung_ho", {}) or {}
    toan_phim_full = bible.get("xung_ho_toan_phim", {}) or {}

    # Lọc toan_phim chỉ giữ cặp mà cả 2 phía đều có trong scene (hoặc ít nhất 1 phía)
    if scene_chars_zh and toan_phim_full:
        scene_set = set(scene_chars_zh)
        toan_phim = {}
        for pair_key, pair_val in toan_phim_full.items():
            # pair_key dạng "A -> B"
            parts = [p.strip() for p in pair_key.split("->")]
            if len(parts) == 2 and (parts[0] in scene_set or parts[1] in scene_set):
                toan_phim[pair_key] = pair_val
        # Nếu lọc xong rỗng → fallback dùng full để không mất context
        if not toan_phim:
            toan_phim = toan_phim_full
    else:
        toan_phim = toan_phim_full

    matrix_parts = []
    if toan_phim:
        matrix_parts.append("Toàn phim:")
        matrix_parts.extend(_render_matrix_dict(toan_phim))
    if matrix:
        if matrix_parts:
            matrix_parts.append("")
        matrix_parts.append("Cảnh này:")
        matrix_parts.extend(_render_matrix_dict(matrix))
    matrix_str = "\n".join(matrix_parts) if matrix_parts else "(Dùng xưng hô mặc định)"

    prompt_tpl = (PROMPTS_DIR / "pass4_review.txt").read_text(encoding="utf-8")
    return (prompt_tpl
            .replace("{BOI_CANH}",            boi_canh)
            .replace("{NHAN_VAT_SUMMARY}",    _build_nhan_vat_summary(bible, scene_chars_zh))
            .replace("{THUAT_NGU}",           _build_thuat_ngu_summary(bible, entries))
            .replace("{TURNING_POINTS}",      _build_turning_points_summary(bible, scene_range))
            .replace("{SCENE_SUMMARY}",       scene_summary)
            .replace("{NHAN_VAT_TRONG_CANH}", _build_nhan_vat_trong_canh(scene_info, bible))
            .replace("{XUNG_HO_MATRIX}",      matrix_str)
            .replace("{SRT_REVIEW_INPUT}",    _build_srt_review_input(entries)))


async def pass4_review_chunk(
    chunk: dict,
    bible: dict,
    entries: list[dict],
    api_key: str,
    model: str,
    on_retry=None,
) -> dict:
    """
    QC review 1 chunk. Trả về {tong_ket, van_de, prompt, tokens_in, tokens_out, timing_ms}.
    Nếu lỗi → trả {} (không crash pipeline).

    `on_retry`: callback async (attempt, max_retry, wait, err) — được _call_api gọi
    mỗi khi retry. Dùng để forward thành SSE event cho FE biết server đang chờ.
    """
    prompt = build_pass4_prompt(chunk, bible, entries)
    try:
        result = await _call_api(
            prompt, api_key, model,
            temperature=0.1,
            response_json=True,
            max_output=4096,
            on_retry=on_retry,
            thinking_budget=0,  # Pass 4 QC: tắt thinking → nhanh hơn
        )
        text = result["text"]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
            data = json.loads(m.group(1)) if m else {}

        data["_prompt"]     = prompt
        data["_tokens_in"]  = result["tokens_in"]
        data["_tokens_out"] = result["tokens_out"]
        data["_timing_ms"]  = result["timing_ms"]
        return data
    except Exception as e:
        logger.error(f"pass4_review_chunk error: {e}", exc_info=True)
        return None


def apply_review_fixes(entries: list[dict], review_result: dict) -> list[dict]:
    """Patch entries với goi_y_sua từ Pass 4. Đánh dấu qc_fixed=True."""
    if not review_result or not review_result.get("van_de"):
        return entries
    entry_map = {e["index"]: e for e in entries}
    for issue in review_result["van_de"]:
        idx = issue.get("dong")
        fix = (issue.get("goi_y_sua") or "").strip()
        if idx and fix and idx in entry_map:
            entry_map[idx]["translated_text"] = fix
            entry_map[idx]["qc_fixed"] = True
    return list(entry_map.values())

# ─────────────────────────────────────────────
# PASS 0 — TIỀN XỬ LÝ / LÀM SẠCH SRT
# ─────────────────────────────────────────────

def detect_abnormal_entries(entries: list[dict]) -> list[int]:
    """
    Scan danh sách SRT entries, trả về list index (1-based) của các dòng bất thường.

    ⚠ LOGIC NÀY PHẢI KHỚP với scanAbnormal() ở FE
    (dubeditor_frontend/src/components/TranslatePage.tsx).

    Tiêu chí:
      1. Text quá dài (>25 ký tự CJK hoặc >50 ký tự tổng)
      2. Có Latin liên tiếp >=3 (logo, tên kênh)
      3. Có xuống dòng thật trong text (multi-line OCR)
      4. Có 2+ cụm CJK dài cách nhau bằng dấu cách (2 vùng OCR gộp)
      5. Lặp 1 ký tự >=5 lần liên tiếp (OCR glitch)
      6. Ký tự nhạc thuần túy (♪♫)
      7. Tag âm thanh [Music], [Applause]
      8. Mix Latin + số dài bất thường (vd: "桐A.99999")
    """
    abnormal = []
    for e in entries:
        text = e["text"].strip()
        if not text:
            continue
        reasons = []

        # 1. Quá dài
        cjk_len = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        if cjk_len > 25 or len(text) > 50:
            reasons.append("too_long")

        # 2. Có Latin liên tiếp >= 3 (logo, tên kênh)
        if re.search(r'[A-Za-z]{3,}', text):
            reasons.append("latin_noise")

        # 3. Xuống dòng thật trong 1 entry
        if '\n' in text:
            reasons.append("multiline")

        # 4. Có 2+ cụm CJK dài cách nhau bằng dấu cách (2 vùng OCR gộp)
        cjk_parts = re.split(r'\s+', text)
        cjk_parts = [p for p in cjk_parts if sum(1 for c in p if '\u4e00' <= c <= '\u9fff') >= 3]
        if len(cjk_parts) >= 2:
            reasons.append("multi_region")

        # 5. Lặp 1 ký tự >= 5 lần liên tiếp — OCR glitch
        # Ví dụ: "来来来来来" (来 lặp 5 lần), "99999"
        if re.search(r'(.)\1{4,}', text):
            reasons.append("repeated_char")

        # 6. Ký tự nhạc thuần túy
        if re.fullmatch(r'[\u266a\u266b\u266c\u266d\u266e\u266f\s]+', text):
            reasons.append("music_symbols")

        # 7. Tag âm thanh [Music], [Applause]
        if re.fullmatch(r'\[.{1,20}\]', text):
            reasons.append("audio_tag")

        # 8. Mix Latin/số dài bất thường giữa CJK
        # Vd: "桐A.99999" — có CJK + ký tự Latin/số tạo chuỗi dài ≥5
        # (không bị bắt bởi rule 2 vì chỉ có 1 Latin, không bị rule 5 vì .99999 lặp 9 chỉ ≥5)
        # → đã được bắt bởi rule 5 ("99999")
        # Bổ sung: text có CJK + chuỗi alphanumeric ≥4 ký tự liền nhau
        if cjk_len >= 1 and re.search(r'[A-Za-z0-9]{4,}', text):
            reasons.append("alphanumeric_in_cjk")

        if reasons:
            abnormal.append(e["index"])

    return abnormal


def build_pass0_windows(entries: list[dict], abnormal_indices: list[int],
                        window: int = 10, merge_gap: int = 5) -> list[list[dict]]:
    """
    Với mỗi index bất thường, lấy window +-N dòng làm context.
    Gộp các window gần nhau (cách < merge_gap) thành 1 nhóm.
    Trả về list các nhóm — mỗi nhóm là list entries cần gửi lên AI.
    """
    if not abnormal_indices:
        return []

    index_map = {e["index"]: e for e in entries}
    all_indices = sorted(e["index"] for e in entries)

    # Tạo raw windows [start, end] cho mỗi abnormal
    raw_windows = []
    for idx in sorted(set(abnormal_indices)):
        pos = all_indices.index(idx) if idx in all_indices else -1
        if pos == -1:
            continue
        start_pos = max(0, pos - window)
        end_pos   = min(len(all_indices) - 1, pos + window)
        raw_windows.append((all_indices[start_pos], all_indices[end_pos]))

    # Gộp window overlap hoặc gần nhau
    merged = []
    for w_start, w_end in raw_windows:
        if merged and w_start - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], w_end))
        else:
            merged.append((w_start, w_end))

    # Lấy entries trong mỗi window
    result = []
    for w_start, w_end in merged:
        group = [e for e in entries if w_start <= e["index"] <= w_end]
        if group:
            result.append(group)

    return result


def build_pass0_prompt(window_entries: list[dict], abnormal_indices: list[int]) -> str:
    """Tạo prompt gửi lên AI cho 1 window làm sạch.

    Đọc template từ pass0_clean.txt. Đánh dấu ⚠ vào dòng nghi ngờ.
    """
    lines = []
    for e in window_entries:
        marker = " ⚠" if e["index"] in abnormal_indices else ""
        lines.append(f"{e['index']}|{e['text']}{marker}")
    srt_text = "\n".join(lines)

    # Đọc prompt template. Có file → dùng file, không có → fallback inline.
    prompt_path = PROMPTS_DIR / "pass0_clean.txt"
    if prompt_path.exists():
        template = prompt_path.read_text(encoding="utf-8")
        return template.replace("{SRT_WINDOW}", srt_text)

    # Fallback nếu file không tồn tại (giữ backward compat)
    return (
        "Dưới đây là đoạn phụ đề phim Trung Quốc (định dạng index|text).\n"
        "Các dòng có dấu ⚠ bị nghi ngờ chứa text thừa không phải lời thoại chính.\n"
        "Text thừa có thể là: logo kênh TV, tên chương trình, chữ trên màn hình/"
        "điện thoại/sách/banner trong cảnh quay, text từ vùng OCR khác lẫn vào.\n\n"
        "Nhiệm vụ:\n"
        "1. Dựa vào ngữ cảnh xung quanh, xác định phần nào là text thừa\n"
        "2. Với dòng có text thừa: chỉ giữ lại phần là lời thoại thật, bỏ phần thừa\n"
        "3. Với dòng hoàn toàn là text thừa: đánh dấu action=\"delete\"\n"
        "4. Với dòng bình thường: KHÔNG đưa vào fixes\n\n"
        "Trả về JSON: {\"fixes\": [{\"index\": <số>, \"action\": \"clean\"|\"delete\", "
        "\"cleaned\": \"...\", \"reason\": \"...\"}]}\n\n"
        f"ĐOẠN PHỤ ĐỀ:\n{srt_text}"
    )


async def pass0_clean_window(
    window_entries: list[dict],
    abnormal_indices: list[int],
    api_key: str,
    model: str,
) -> dict:
    """
    Gửi 1 window lên AI, nhận về dict fixes.
    Trả về: {"fixes": [...]} hoặc {"fixes": []} nếu lỗi/không có gì sửa
    """
    prompt = build_pass0_prompt(window_entries, abnormal_indices)
    try:
        result = await _call_api(
            prompt, api_key, model,
            temperature=0.1,
            response_json=True,
            max_output=4096,
        )
        text = result["text"].strip()
        # Strip markdown nếu có
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
        data = json.loads(text)
        return data if "fixes" in data else {"fixes": []}
    except Exception as e:
        logger.warning(f"pass0_clean_window error: {e}")
        return {"fixes": []}


async def pass0_clean_srt(
    raw_srt: str,
    api_key: str,
    model: str,
    window: int = 10,
    on_progress=None,
) -> tuple[str, list[dict]]:
    """
    Entry point Pass 0.
    Trả về: (cleaned_srt, report)
      - cleaned_srt: SRT string đã làm sạch
      - report: list các fix đã áp dụng
    """
    entries = parse_srt(raw_srt)
    abnormal = detect_abnormal_entries(entries)

    if not abnormal:
        return raw_srt, []

    windows = build_pass0_windows(entries, abnormal, window=window)

    # Gửi song song tất cả windows
    tasks = [
        pass0_clean_window(w, abnormal, api_key, model)
        for w in windows
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Gom tất cả fixes
    all_fixes = []
    for r in results:
        if isinstance(r, dict):
            all_fixes.extend(r.get("fixes", []))

    if not all_fixes:
        return raw_srt, []

    # Áp dụng fixes vào entries
    fix_map = {f["index"]: f for f in all_fixes}
    cleaned_entries = []
    report = []

    for e in entries:
        fix = fix_map.get(e["index"])
        if not fix:
            cleaned_entries.append(e)
            continue

        if fix["action"] == "delete":
            report.append({**fix, "original": e["text"]})
            # Bỏ qua entry này — không thêm vào cleaned
        elif fix["action"] == "clean":
            cleaned_text = fix.get("cleaned", e["text"]).strip()
            if cleaned_text:
                cleaned_entries.append({**e, "text": cleaned_text})
                report.append({**fix, "original": e["text"]})
            else:
                # cleaned rỗng → xem như delete
                report.append({**fix, "action": "delete", "original": e["text"]})

    # Rebuild SRT string
    cleaned_srt = _rebuild_srt(cleaned_entries)
    return cleaned_srt, report


def _rebuild_srt(entries: list[dict]) -> str:
    """Rebuild SRT string từ list entries, reindex từ 1."""
    lines = []
    for i, e in enumerate(entries, 1):
        lines.append(f"{i}\n{e['start']} --> {e['end']}\n{e['text']}\n")
    return "\n".join(lines)