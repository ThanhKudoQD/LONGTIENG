# Fix v3.7.4 — max_output đủ lớn + thinking control cho DeepSeek

## Vấn đề chính

Log Stage 1A:
```
HTTP 200 OK   ← header về
... 4'56" ...
[JSON] Failed to parse, using default. Preview: (rỗng)
[Stage 1A] Got 0 characters, 0 terms
```
UI: `Response: 0 chars`, `Finish: length`.

### Nguyên nhân
1. **`cap_max_output` đang ép DeepSeek V4 chỉ 8192 tokens** (file cũ comment
   "thực tế cap ở 8192 cho ổn định" — sai với V4 spec).
2. **Stage 1A code đặt `max_output=20000`** nhưng bị cap xuống 8192.
3. **DeepSeek V4 Pro mặc định BẬT thinking** → thinking tokens ăn hết
   8192 quota → response rỗng + `finish_reason=length`.
4. **Backend không gửi `thinking` flag** cho DeepSeek → không control được.
5. **Frontend disable thinking checkbox** cho DeepSeek (không có trong
   `thinkingSupported` list) → user không tắt được.

## Cách sửa

### 1. `cap_max_output` đúng spec model (2026-05)
```python
DeepSeek V4 Pro/Flash  → 65K (đủ cho thinking + JSON dài)
Gemini 3.x             → 65K
Gemini 2.5 Pro/Flash   → 65K
GPT-5                  → 128K
GPT-4o/4o-mini         → 16K
```

### 2. Tăng `max_output` ở từng stage
| Stage | Cũ | Mới | Ghi chú |
|---|---|---|---|
| Stage 0 Normalize  |  8K | 16K | decisions ~3K |
| Stage 1A Cast      | 20K | 40K | cast ~5-8K + thinking 20-30K |
| Stage 1B World     | 10K | 32K | arcs ~5K + thinking |
| Stage 2 Chunks     |  8K | 32K | chunks ~3K + thinking |
| Stage 3 Speaker    | 12K | 32K | speakers ~5K + thinking |
| Stage 4 Translate  | 16K | 48K | 2 bản v1+v2 ~10K + thinking dài |
| Stage 5 Retry      |  8K | 24K | batch ~5K + thinking |

### 3. Backend gửi `thinking` flag cho DeepSeek V4
```python
if deepseek_v4:
    if req.thinking is True:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = "high"
    elif req.thinking is False:
        payload["thinking"] = {"type": "disabled"}
    # None → không gửi → dùng default DeepSeek (Pro=ON, Flash=OFF)
```

### 4. Frontend cho phép bật/tắt thinking cho DeepSeek V4
Trong cả `StageModelCard` và `ModelSelector` (legacy), thêm DeepSeek
vào list `thinkingSupported`:
```js
value.startsWith('deepseek-v4') || value.startsWith('deepseek-reasoner')
```

## File thay đổi (8 file)

### Backend
- `srt_translator_v2/core/llm_client.py`:
  - `cap_max_output()`: sửa caps đúng spec, đặc biệt DeepSeek V4 từ 8K → 64K
  - `call_openai_compat()`: gửi `thinking` + `reasoning_effort` cho DeepSeek V4

### Stage runners (chỉ đổi max_output)
- `srt_translator_v2/stages/stage0_normalize.py`: 8K → 16K
- `srt_translator_v2/stages/stage1_bible.py`: 20K→40K (1A), 10K→32K (1B)
- `srt_translator_v2/stages/stage2_scenes.py`: 8K → 32K
- `srt_translator_v2/stages/stage3_speaker.py`: 12K → 32K
- `srt_translator_v2/stages/stage4_translate.py`: 16K → 48K
- `srt_translator_v2/stages/stage5_polish.py`: 8K → 24K

### Frontend
- `dubeditor_frontend/src/components/translate/ConfigPanel.tsx`:
  - `StageModelCard.thinkingSupported`: thêm `deepseek-v4`, `deepseek-reasoner`
  - `ModelSelector` (legacy compat): cùng update

## Test gợi ý

1. Vào ConfigPanel → các card đang chọn DeepSeek → **checkbox Thinking
   giờ enable được** (trước đây disabled grey)
2. Tick/untick thinking → save → chạy Stage 1A với DeepSeek Pro:
   - **Thinking OFF**: response ngay, JSON parse OK, cast ra đầy đủ
   - **Thinking ON**: response chậm hơn (~30-60s) nhưng vẫn ra đầy đủ
     (không bị `Finish: length` nữa vì max_output đủ 40K)
3. Check log `[1a_cast_glossary] ✓ LLM trả response: Xs, out=Y tok` —
   `Y` không nên ≥ 40000 (= max ép cụt)

## Lưu ý

- Tăng max_output không tốn tiền nếu model không output đến đó.
  Phí tính trên **tokens thực output**, không phải max_output.
- DeepSeek V4 thinking mặc định BẬT khi không gửi flag → từ giờ với
  config OFF rõ ràng sẽ tiết kiệm token 2-5x.
- Nếu vẫn `Finish: length` thì có thể model đang chọn task quá khó
  (1A với 3000 dòng) → tăng max_output Stage 1A lên 64K trong
  `stage1_bible.py` là OK với DeepSeek (max 384K, cap 64K).
