# Fix bổ sung cho patch thinking-toggle

Lỗi build trước đó là vì 2 file khác cũng build `TranslateConfig` nhưng tôi chưa cập nhật.

## File mapping (chép đè)

| File trong zip này | Đường dẫn đích |
|---|---|
| `dubeditor_frontend/src/components/translate/CleanedView.tsx` | (đã đúng path) |
| `dubeditor_frontend/src/components/ConfigModal.tsx` | (đã đúng path) |

## Đã sửa gì

- **CleanedView.tsx**: object `config: TranslateConfig` (dòng 106) giờ có thêm 4 field thinking (`null` mặc định = giữ default backend).
- **ConfigModal.tsx**: `DEFAULT_CONFIG` thiếu nhiều field (không chỉ thinking — cả `project_type`, `cps_max`, `source_lang`, `chunks_parallel`, `speaker_parallel`, `speaker_context_window`, `stage0_*`). Đã bổ sung đầy đủ.

## Cách dùng

Giải nén đè lên project root như patch trước. Hoặc copy tay 2 file vào:
- `dubeditor_frontend/src/components/translate/CleanedView.tsx`
- `dubeditor_frontend/src/components/ConfigModal.tsx`

Sau đó chạy lại `npm run build`.
