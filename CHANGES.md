# Fix v3.6.5 — Hover effect + row height 88px

## Thay đổi

### 1. `SUB_H: 80 → 88px`
Row subtitle cao hơn 8px nữa, dễ đọc.

### 2. Hover effect cho 5 action buttons
- ✨ Dịch lại / BT / Xóa / Buồn / Giận
- Hover: `filter: brightness(1.12) saturate(1.15)` + `translateY(-1px)` + `box-shadow`
- Active (đang bấm): `translateY(0) scale(0.96)` + shadow nhỏ lại
- Disabled: không có hiệu ứng (đã `:not(:disabled)`)
- Smooth 150ms transition

Vì các button dùng inline `style` (màu phụ thuộc `isActive` từ JS),
Tailwind `hover:` utilities không override được. Dùng class CSS riêng
`.sub-action-btn` trong `index.css` với `filter` (không clash với inline
`background`/`border`/`color`).

## File thay đổi (2 file)
- `dubeditor_frontend/src/components/SubtitleList.tsx`:
  - `SUB_H = 88`
  - Thay `transition-all` cho 5 button bằng `sub-action-btn`
- `dubeditor_frontend/src/index.css`:
  - Thêm `.sub-action-btn` class với hover/active rules

## Test gợi ý
1. Hover nút "Dịch lại" → row sáng hơn, nâng lên 1px, có bóng đổ → bấm xuống lại
2. Hover BT / Xóa / Buồn / Giận → tương tự
3. Nút disabled (Buồn khi chưa upload sad audio) → không có hiệu ứng hover
4. Row subtitle cao 88px, đủ chỗ 2 dòng text TQ + VI thoáng hơn
