# Patch HOÀN CHỈNH — Thinking toggle per-stage (v3)

Zip này gộp tất cả file đã sửa qua các lần patch. **Chỉ cần giải nén 1 lần duy nhất.**

## Cách dùng

1. Cd vào thư mục **root của project** (chỗ có 3 folder ngang hàng: `dubeditor/`, `dubeditor_frontend/`, `srt_translator_v2/`).
2. Giải nén:
   ```bash
   unzip -o thinking_toggle_FULL.zip
   ```
   `-o` để ghi đè không hỏi.
3. Restart backend FastAPI.
4. Build frontend:
   ```bash
   cd dubeditor_frontend
   npm run build
   ```

## 14 file đã sửa

### Backend Python — 10 file
- `srt_translator_v2/config.py` — thêm `heavy_thinking`, `medium_thinking`, `light_thinking`, `translate_thinking`
- `srt_translator_v2/core/llm_client.py` — `LLMRequest` thêm field `thinking`
- `srt_translator_v2/stages/stage0_normalize.py` — dùng `light_thinking`
- `srt_translator_v2/stages/stage1_bible.py` — 1A dùng `heavy_thinking`, 1B dùng `medium_thinking`
- `srt_translator_v2/stages/stage2_scenes.py` — dùng `medium_thinking`
- `srt_translator_v2/stages/stage3_speaker.py` — dùng `medium_thinking`
- `srt_translator_v2/stages/stage4_translate.py` — dùng `translate_thinking` ⭐
- `srt_translator_v2/stages/stage5_polish.py` — dùng `light_thinking`
- `dubeditor/schemas.py` — `TranslateConfig` thêm 4 field
- `dubeditor/translate_service.py` — `build_pipeline_config` đọc 4 field

### Frontend TypeScript — 4 file
- `dubeditor_frontend/src/types/index.ts` — interface thêm 4 field
- `dubeditor_frontend/src/components/translate/ConfigPanel.tsx` — UI toggle thinking inline
- `dubeditor_frontend/src/components/translate/CleanedView.tsx` — build config có 4 field
- `dubeditor_frontend/src/components/ConfigModal.tsx` — `DEFAULT_CONFIG` đầy đủ

## Verify đã apply đúng (chạy trong project root)

```bash
grep "heavy_thinking" dubeditor_frontend/src/types/index.ts
grep "heavy_thinking" dubeditor_frontend/src/components/ConfigModal.tsx
grep "heavy_thinking" srt_translator_v2/config.py
```

Cả 3 lệnh đều phải in ra kết quả. Nếu lệnh nào không in gì → file đó chưa apply, giải nén lại.
