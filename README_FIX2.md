# Fix 2 — ConfigModal.tsx

## Nguyên nhân lỗi

`ConfigModal.tsx` có **interface `TranslateConfig` RIÊNG** (dòng 14), không import từ `types/index.ts`. Comment trong file ghi rõ đây là "backward-compat shim" cho component cũ (SubtitleList retranslate inline).

Patch trước tôi thêm field thinking vào DEFAULT_CONFIG nhưng quên thêm vào interface local → TS báo lỗi.

## Đã sửa

Đồng bộ interface và DEFAULT_CONFIG:
- Thêm 4 field optional `heavy_thinking`, `medium_thinking`, `light_thinking`, `translate_thinking` (kiểu `boolean | null`) vào interface.
- DEFAULT_CONFIG khởi tạo 4 field = `null` (= giữ default backend).
- Rollback các field thừa tôi thêm nhầm trước đó (project_type, cps_max, source_lang, chunks_parallel, ...) — vì interface local của ConfigModal không có chúng, không cần.

## Cách dùng

Chép đè 1 file:
- `dubeditor_frontend/src/components/ConfigModal.tsx`

Rồi `npm run build` lại.
