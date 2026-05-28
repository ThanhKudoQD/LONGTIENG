"""
Unified LLM client — Gemini / OpenAI / DeepSeek.

Features:
- Detect provider từ model name
- Caching tự động hoặc explicit
- Retry với exponential backoff
- JSON output parsing với fallback
- Tracking tokens + cost

Async-first, dùng httpx.
"""
from __future__ import annotations
import asyncio
import json
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Literal, Callable, Any

import httpx


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# PROVIDER DETECTION
# ─────────────────────────────────────────────────────────────────

Provider = Literal["gemini", "openai", "deepseek"]


def detect_provider(model: str) -> Provider:
    """Detect provider từ tên model."""
    m = model.lower()
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("deepseek"):
        return "deepseek"
    if any(m.startswith(p) for p in ("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    return "gemini"  # default


# ─────────────────────────────────────────────────────────────────
# OUTPUT CAP per model (tránh lỗi 400)
# ─────────────────────────────────────────────────────────────────

def cap_max_output(max_output: int, model: str) -> int:
    """Cap max_output theo giới hạn thực tế của từng model.

    Số liệu cập nhật theo doc chính thức (May 2026):
    - Gemini 2.5 / 3.x: 65536 max output
    - GPT-5 / o-series: 32768 (reasoning models)
    - GPT-4o / 4o-mini: 16384
    - GPT-4: 8192, GPT-3.5 / 4-turbo: 4096
    - DeepSeek V4 (Flash & Pro): up to 65536 (doc nói 384K nhưng cap ở 65536 cho ổn định)
    - DeepSeek V3 / legacy: 8192
    """
    m = model.lower()
    if "gpt-4o-mini" in m or "gpt-4o" in m:
        return min(max_output, 16384)
    if "gpt-4-turbo" in m:
        return min(max_output, 4096)
    if "gpt-4" in m:
        return min(max_output, 8192)
    if "gpt-3.5" in m:
        return min(max_output, 4096)
    # GPT-5 series: 128000 max output tokens (gồm cả reasoning tokens)
    if m.startswith("gpt-5"):
        return min(max_output, 128000)
    if m.startswith(("o1", "o3", "o4")):
        return min(max_output, 100000)
    # DeepSeek V4 (Flash & Pro) — doc nói 384K, cap ở 65536 cho ổn định + tránh chunk lớn bị cắt
    if "deepseek-v4" in m or "deepseek-reasoner" in m:
        return min(max_output, 65536)
    if "deepseek" in m:
        return min(max_output, 8192)
    # Gemini 3.x
    if "gemini-3" in m:
        return min(max_output, 65536)
    # Gemini 2.5
    if "gemini-2.5" in m:
        return min(max_output, 65536)
    return max_output


# ─────────────────────────────────────────────────────────────────
# RESPONSE WRAPPER
# ─────────────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    text: str
    model: str
    provider: Provider
    tokens_in: int = 0
    tokens_out: int = 0
    cached_tokens: int = 0
    timing_ms: int = 0
    finish_reason: str = ""
    raw: Optional[dict] = None


# ─────────────────────────────────────────────────────────────────
# REQUEST OPTIONS
# ─────────────────────────────────────────────────────────────────

@dataclass
class LLMRequest:
    """Tham số gọi LLM."""
    prompt: str
    model: str
    api_key: str
    temperature: float = 0.3
    max_output: int = 8192
    json_mode: bool = False
    timeout: float = 180.0

    # System / cached block (tách riêng để cache)
    system_prompt: Optional[str] = None
    cached_prefix: Optional[str] = None  # Block lớn để cache (Bible, instructions)

    # Thinking control (Gemini 2.5+ / OpenAI o-series)
    # None  = không gửi config (dùng default của model — Gemini Pro auto thinking)
    # True  = bật thinking dynamic (Gemini: thinkingBudget=-1)
    # False = tắt hẳn thinking (Gemini: thinkingBudget=0) — nhanh + rẻ, hợp task JSON đơn giản
    thinking: Optional[bool] = False

    # Retry
    max_retries: int = 3
    retry_backoff: float = 2.0


# ─────────────────────────────────────────────────────────────────
# GEMINI
# ─────────────────────────────────────────────────────────────────

async def call_gemini(req: LLMRequest, client: httpx.AsyncClient) -> LLMResponse:
    """Call Gemini API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{req.model}:generateContent?key={req.api_key}"

    # Build contents
    user_text = req.prompt
    if req.cached_prefix:
        # Cho lần đầu chưa có cache: gửi inline cùng prompt
        # (Explicit cache cần API riêng — implement sau)
        user_text = req.cached_prefix + "\n\n" + req.prompt

    contents = [{"role": "user", "parts": [{"text": user_text}]}]

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": req.temperature,
            "maxOutputTokens": cap_max_output(req.max_output, req.model),
        },
    }

    # Thinking control — chỉ gửi nếu được set explicit
    # thinking=False → thinkingBudget=0 (tắt, tiết kiệm output budget cho JSON task)
    # thinking=True  → thinkingBudget=-1 (dynamic, model tự quyết)
    # thinking=None  → không gửi config (Gemini Pro default = thinking bật, Flash default = bật nhẹ)
    if req.thinking is not None:
        payload["generationConfig"]["thinkingConfig"] = {
            "thinkingBudget": -1 if req.thinking else 0,
        }

    if req.system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": req.system_prompt}]}

    if req.json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    # v3 DEBUG: log toàn bộ payload TRƯỚC khi POST (mask prompt text, giữ mọi config khác)
    try:
        import copy
        _dbg_payload = copy.deepcopy(payload)
        # Mask prompt text trong contents để không log toàn bộ prompt
        for c in _dbg_payload.get("contents", []):
            for p in c.get("parts", []):
                if "text" in p:
                    p["text"] = f"<masked {len(p['text'])} chars>"
        # Mask system instruction nếu có
        if "systemInstruction" in _dbg_payload:
            for p in _dbg_payload["systemInstruction"].get("parts", []):
                if "text" in p:
                    p["text"] = f"<masked {len(p['text'])} chars>"
        # Mask URL key
        _dbg_url_safe = url.split("?key=")[0] + "?key=" + (
            "***" + (req.api_key[-6:] if req.api_key and len(req.api_key) > 6 else "EMPTY")
        )
        logger.info(
            f"[GEMINI REQUEST] url={_dbg_url_safe}, "
            f"model={req.model}, "
            f"payload={json.dumps(_dbg_payload, ensure_ascii=False)}"
        )
    except Exception as _dbg_e:
        logger.debug(f"[GEMINI debug log failed]: {_dbg_e}")

    headers = {"Content-Type": "application/json"}
    t0 = time.time()
    r = await client.post(url, json=payload, headers=headers, timeout=req.timeout)
    elapsed_ms = int((time.time() - t0) * 1000)

    if r.status_code != 200:
        raise RuntimeError(f"Gemini API error {r.status_code}: {r.text[:500]}")

    data = r.json()
    candidates = data.get("candidates", [])
    if not candidates:
        # Check prompt feedback for blocking
        feedback = data.get("promptFeedback", {})
        raise RuntimeError(f"Gemini empty response. Feedback: {feedback}")

    cand = candidates[0]
    finish_reason = cand.get("finishReason", "")

    # Extract text
    parts = cand.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)

    # Usage
    usage = data.get("usageMetadata", {})
    tokens_in = usage.get("promptTokenCount", 0)
    tokens_out = usage.get("candidatesTokenCount", 0)
    cached_tokens = usage.get("cachedContentTokenCount", 0)

    return LLMResponse(
        text=text,
        model=req.model,
        provider="gemini",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cached_tokens=cached_tokens,
        timing_ms=elapsed_ms,
        finish_reason=finish_reason,
        raw=data,
    )


# ─────────────────────────────────────────────────────────────────
# OPENAI-COMPATIBLE (OpenAI, DeepSeek)
# ─────────────────────────────────────────────────────────────────

async def call_openai_compat(req: LLMRequest, client: httpx.AsyncClient,
                              base_url: str = "https://api.openai.com/v1") -> LLMResponse:
    """Call OpenAI hoặc DeepSeek (cùng format chat completions)."""
    url = f"{base_url}/chat/completions"

    messages = []
    if req.system_prompt:
        messages.append({"role": "system", "content": req.system_prompt})
    if req.cached_prefix:
        # Để cached_prefix vào đầu user message (OpenAI auto cache prefix giống nhau)
        messages.append({"role": "user", "content": req.cached_prefix + "\n\n" + req.prompt})
    else:
        messages.append({"role": "user", "content": req.prompt})

    # v3.14 FIX: OpenAI reasoning models (gpt-5*, o1*, o3*, o4*) dùng
    # `max_completion_tokens` thay vì `max_tokens` (cũ legacy).
    # Legacy models (gpt-4*, gpt-3.5*) vẫn dùng `max_tokens`.
    # Reasoning models cũng KHÔNG support temperature ≠ 1 (chỉ default).
    _model_lower = req.model.lower()
    _is_reasoning = (
        _model_lower.startswith("gpt-5")
        or _model_lower.startswith("o1")
        or _model_lower.startswith("o3")
        or _model_lower.startswith("o4")
    )
    _max_token_field = "max_completion_tokens" if _is_reasoning else "max_tokens"

    payload = {
        "model": req.model,
        "messages": messages,
        _max_token_field: cap_max_output(req.max_output, req.model),
    }
    # v3.14: reasoning models chỉ accept temperature mặc định (1) → bỏ field
    # để model dùng default. Legacy models vẫn truyền temperature từ request.
    if not _is_reasoning:
        payload["temperature"] = req.temperature

    if req.json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {req.api_key}",
    }

    # v3 DEBUG: log toàn bộ payload TRƯỚC khi POST (mask prompt text, giữ mọi config)
    try:
        import copy
        _dbg_payload = copy.deepcopy(payload)
        for m in _dbg_payload.get("messages", []):
            if "content" in m and isinstance(m["content"], str):
                m["content"] = f"<masked {len(m['content'])} chars>"
        logger.info(
            f"[OPENAI/DEEPSEEK REQUEST] url={url}, "
            f"api_key={'***' + req.api_key[-6:] if req.api_key and len(req.api_key) > 6 else ('EMPTY' if not req.api_key else req.api_key)}, "
            f"payload={json.dumps(_dbg_payload, ensure_ascii=False)}"
        )
    except Exception as _dbg_e:
        logger.debug(f"[OPENAI/DEEPSEEK debug log failed]: {_dbg_e}")

    t0 = time.time()
    r = await client.post(url, json=payload, headers=headers, timeout=req.timeout)
    elapsed_ms = int((time.time() - t0) * 1000)

    if r.status_code != 200:
        raise RuntimeError(f"API error {r.status_code}: {r.text[:500]}")

    data = r.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("Empty response")

    choice = choices[0]
    text = choice.get("message", {}).get("content", "")
    finish_reason = choice.get("finish_reason", "")

    usage = data.get("usage", {})
    tokens_in = usage.get("prompt_tokens", 0)
    tokens_out = usage.get("completion_tokens", 0)

    # Cache info (DeepSeek)
    cached_tokens = usage.get("prompt_cache_hit_tokens", 0)
    if not cached_tokens:
        # OpenAI format
        details = usage.get("prompt_tokens_details", {})
        cached_tokens = details.get("cached_tokens", 0)

    provider: Provider = "deepseek" if "deepseek" in base_url else "openai"

    return LLMResponse(
        text=text,
        model=req.model,
        provider=provider,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cached_tokens=cached_tokens,
        timing_ms=elapsed_ms,
        finish_reason=finish_reason,
        raw=data,
    )


# ─────────────────────────────────────────────────────────────────
# MAIN CALL FUNCTION (with retry)
# ─────────────────────────────────────────────────────────────────

async def call_llm(req: LLMRequest, client: Optional[httpx.AsyncClient] = None,
                   stage_tag: str = "") -> LLMResponse:
    """Gọi LLM với retry tự động.

    stage_tag: tên stage để observer phân loại (vd: '1a_cast', '4_translate').
    """
    provider = detect_provider(req.model)

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient()

    try:
        last_exc = None
        for attempt in range(req.max_retries):
            try:
                if provider == "gemini":
                    resp = await call_gemini(req, client)
                elif provider == "deepseek":
                    resp = await call_openai_compat(
                        req, client, base_url="https://api.deepseek.com/v1"
                    )
                else:  # openai
                    resp = await call_openai_compat(req, client)

                # Notify observer (nếu có) — không block call
                _notify_observer(req, resp, stage_tag, attempt + 1, error=None)
                return resp
            except Exception as e:
                last_exc = e
                logger.warning(f"[LLM] Attempt {attempt+1}/{req.max_retries} failed: {e}")
                _notify_observer(req, None, stage_tag, attempt + 1, error=str(e))
                if attempt < req.max_retries - 1:
                    await asyncio.sleep(req.retry_backoff * (2 ** attempt))

        raise RuntimeError(f"All {req.max_retries} retries failed. Last: {last_exc}")
    finally:
        if owns_client:
            await client.aclose()


# ─────────────────────────────────────────────────────────────────
# OBSERVER — bắt prompt + response cho debug UI
# ─────────────────────────────────────────────────────────────────

# Callback signature: fn(payload: dict) -> None | Awaitable
# Payload chứa: stage_tag, model, provider, attempt, tokens_in/out, timing_ms,
#               prompt_preview, response_preview, error
_llm_observer: Optional[Callable[[dict], Any]] = None


def set_llm_observer(callback: Optional[Callable[[dict], Any]]):
    """Đặt callback để theo dõi mỗi call_llm. Truyền None để tắt."""
    global _llm_observer
    _llm_observer = callback


def _notify_observer(req: LLMRequest, resp: Optional[LLMResponse],
                      stage_tag: str, attempt: int, error: Optional[str]):
    """Gọi observer nếu có set."""
    if _llm_observer is None:
        return
    try:
        # Truncate prompt + response để tránh quá lớn qua SSE
        PROMPT_LIMIT = 4000
        RESP_LIMIT = 4000
        prompt = req.prompt or ""
        if req.cached_prefix:
            prompt = (req.cached_prefix or "") + "\n" + prompt
        prompt_trunc = prompt if len(prompt) <= PROMPT_LIMIT else (
            prompt[:PROMPT_LIMIT] + f"\n...[truncated, total {len(prompt)} chars]"
        )

        payload = {
            "stage_tag": stage_tag,
            "model": req.model,
            "provider": detect_provider(req.model),
            "attempt": attempt,
            "prompt_length": len(prompt),
            "prompt_preview": prompt_trunc,
            "temperature": req.temperature,
            "json_mode": req.json_mode,
        }
        if resp is not None:
            resp_text = resp.text or ""
            resp_trunc = resp_text if len(resp_text) <= RESP_LIMIT else (
                resp_text[:RESP_LIMIT] + f"\n...[truncated, total {len(resp_text)} chars]"
            )
            payload.update({
                "ok": True,
                "tokens_in": resp.tokens_in,
                "tokens_out": resp.tokens_out,
                "cached_tokens": resp.cached_tokens,
                "timing_ms": resp.timing_ms,
                "finish_reason": resp.finish_reason,
                "response_length": len(resp_text),
                "response_preview": resp_trunc,
            })
        else:
            payload.update({"ok": False, "error": error})

        result = _llm_observer(payload)
        if asyncio.iscoroutine(result):
            # Schedule trong loop hiện tại — observer thường là async
            asyncio.create_task(result)
    except Exception as e:
        logger.warning(f"[LLM observer] failed: {e}")


# ─────────────────────────────────────────────────────────────────
# JSON PARSING WITH FALLBACK
# ─────────────────────────────────────────────────────────────────

def parse_json_response(text: str, default: Optional[dict | list] = None) -> dict | list:
    """
    Parse JSON từ output LLM, có fallback cho output không sạch.

    v3 PARTIAL RECOVERY: nếu JSON bị cắt giữa chừng (MAX_TOKENS), thử extract
    các object hoàn chỉnh bên trong (vd. lấy decisions/translations đã parse được).
    """
    text = text.strip()

    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extract first JSON object/array
    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue

    # Try fix common issues
    # Remove trailing commas
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # v3 PARTIAL RECOVERY: JSON bị cắt → cố lấy các object hoàn chỉnh bên trong.
    # Áp dụng khi default là dict chứa array (vd {"decisions": []}, {"translations": []}).
    # Strategy:
    #  1. Tìm key của array (decisions/translations/items/...) trong text
    #  2. Match từng object hoàn chỉnh {...} cân bằng dấu ngoặc
    #  3. Trả lại dict với array chứa các object recovered
    if isinstance(default, dict):
        for arr_key in default.keys():
            arr_marker = f'"{arr_key}"'
            if arr_marker not in text:
                continue
            arr_start = text.index(arr_marker) + len(arr_marker)
            bracket_idx = text.find("[", arr_start)
            if bracket_idx < 0:
                continue
            after_bracket = text[bracket_idx + 1:]

            # Extract từng object {...} cân bằng dấu ngoặc, có ý thức về string
            # (để tránh đếm { } bên trong "text": "..." )
            objs: list = []
            depth = 0
            start = -1
            in_string = False
            escape = False
            for i, ch in enumerate(after_bracket):
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start >= 0:
                        obj_str = after_bracket[start:i + 1]
                        try:
                            objs.append(json.loads(obj_str))
                        except json.JSONDecodeError:
                            pass
                        start = -1
            if objs:
                logger.warning(
                    f"[JSON] Recovered {len(objs)} partial {arr_key!r} objects "
                    f"from truncated/malformed response."
                )
                result = dict(default)
                result[arr_key] = objs
                return result

    if default is not None:
        logger.warning(f"[JSON] Failed to parse, using default. Preview: {text[:200]}")
        return default

    raise ValueError(f"Cannot parse JSON. Preview: {text[:500]}")


# ─────────────────────────────────────────────────────────────────
# COST ESTIMATION
# ─────────────────────────────────────────────────────────────────

# Giá $/1M tokens (cập nhật May 2026)
PRICING = {
    # Gemini 3.x
    "gemini-3.1-pro":              {"in": 2.00, "out": 12.00, "cached_in": 0.50},
    "gemini-3.1-flash-lite":       {"in": 0.50, "out": 3.00,  "cached_in": 0.125},
    # Gemini 2.5
    "gemini-2.5-pro":              {"in": 1.25, "out": 10.00, "cached_in": 0.31},
    "gemini-2.5-flash":            {"in": 0.30, "out": 2.50,  "cached_in": 0.075},
    "gemini-2.5-flash-lite":       {"in": 0.10, "out": 0.40,  "cached_in": 0.025},
    # OpenAI
    "gpt-5":                       {"in": 1.25, "out": 10.00, "cached_in": 0.125},
    "gpt-5-mini":                  {"in": 0.25, "out": 2.00,  "cached_in": 0.025},
    "gpt-5-nano":                  {"in": 0.05, "out": 0.40,  "cached_in": 0.005},
    "gpt-4o":                      {"in": 2.50, "out": 10.00, "cached_in": 1.25},
    "gpt-4o-mini":                 {"in": 0.15, "out": 0.60,  "cached_in": 0.075},
    # DeepSeek V4 (mới — chính thức)
    "deepseek-v4-flash":           {"in": 0.14,  "out": 0.28, "cached_in": 0.0028},
    "deepseek-v4-pro":             {"in": 0.435, "out": 0.87, "cached_in": 0.003625},
    # DeepSeek V3 (legacy — deprecated, alias về v4)
    "deepseek-chat":               {"in": 0.14,  "out": 0.28, "cached_in": 0.0028},
    "deepseek-v3":                 {"in": 0.14,  "out": 0.28, "cached_in": 0.0028},
    "deepseek-reasoner":           {"in": 0.435, "out": 0.87, "cached_in": 0.003625},
}


def estimate_cost(resp: LLMResponse) -> float:
    """Estimate cost USD cho 1 call. Match longest prefix để tránh nhầm
    'deepseek-chat' với 'deepseek-reasoner'."""
    model_key = resp.model.lower()
    pricing = None
    best_match_len = 0
    for key, val in PRICING.items():
        if model_key.startswith(key) and len(key) > best_match_len:
            pricing = val
            best_match_len = len(key)
    # Fallback: contains match
    if not pricing:
        for key, val in PRICING.items():
            if key in model_key:
                pricing = val
                break

    if not pricing:
        return 0.0

    non_cached_in = max(0, resp.tokens_in - resp.cached_tokens)
    cost = (
        non_cached_in * pricing["in"] / 1_000_000 +
        resp.cached_tokens * pricing["cached_in"] / 1_000_000 +
        resp.tokens_out * pricing["out"] / 1_000_000
    )
    return cost


# ─────────────────────────────────────────────────────────────────
# COST TRACKER
# ─────────────────────────────────────────────────────────────────

@dataclass
class CostTracker:
    """Tracker để biết tổng chi phí trong 1 lần chạy pipeline."""
    total_calls: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cached_tokens: int = 0
    total_cost_usd: float = 0.0
    by_stage: dict[str, dict] = field(default_factory=dict)

    def add(self, stage: str, resp: LLMResponse):
        self.total_calls += 1
        self.total_tokens_in += resp.tokens_in
        self.total_tokens_out += resp.tokens_out
        self.total_cached_tokens += resp.cached_tokens
        cost = estimate_cost(resp)
        self.total_cost_usd += cost

        if stage not in self.by_stage:
            self.by_stage[stage] = {"calls": 0, "tokens_in": 0, "tokens_out": 0,
                                     "cached": 0, "cost": 0.0}
        s = self.by_stage[stage]
        s["calls"] += 1
        s["tokens_in"] += resp.tokens_in
        s["tokens_out"] += resp.tokens_out
        s["cached"] += resp.cached_tokens
        s["cost"] += cost

    def summary(self) -> str:
        lines = [
            f"📊 LLM Cost Summary",
            f"   Total calls: {self.total_calls}",
            f"   Tokens in: {self.total_tokens_in:,} (cached: {self.total_cached_tokens:,})",
            f"   Tokens out: {self.total_tokens_out:,}",
            f"   Total cost: ${self.total_cost_usd:.4f}",
            f"",
            f"   By stage:",
        ]
        for stage, s in self.by_stage.items():
            lines.append(
                f"     {stage:<20} {s['calls']:>4} calls  "
                f"in:{s['tokens_in']:>8,}  out:{s['tokens_out']:>7,}  "
                f"${s['cost']:.4f}"
            )
        return "\n".join(lines)