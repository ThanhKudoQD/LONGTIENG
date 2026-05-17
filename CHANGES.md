# Fix v3.4 — Filter đoạn áp dụng cho mọi xử lý hàng loạt

## Vấn đề
Trước đây các filter (đoạn / NV / text / no-char / no-TTS / overlap) chỉ áp cho
hiển thị danh sách. Các hành động hàng loạt như "TTS tất cả", select-all,
auto-fix overlap, trim bulk, áp tốc độ TTS theo NV, đổi NV (swap)... đều ăn
toàn bộ phụ đề, bỏ qua filter đang bật.

## Nguyên tắc mới
**Có filter đoạn/NV/text → mọi xử lý hàng loạt CHỈ động vào subset đang lọc.**
Không filter → áp toàn phim như cũ.

## File thay đổi (7 file)

Đặt vào đúng đường dẫn tương ứng trong dự án, ghi đè file cũ.

### Frontend
- `dubeditor_frontend/src/store/index.ts`
  - Thêm filter state vào Zustand store (filterText, filterNoChar, filterNoTTS,
    filterOverlap, filterCharIds, filterChapterIds, chapters, overlapSubIds)
  - Thêm selector dùng chung: `filterVisible`, `getVisibleSubtitles`,
    `getVisibleSubtitleIds`, `hasAnyFilter`

- `dubeditor_frontend/src/components/Editor.tsx`
  - Filter chuyển từ local useState → store (single source of truth)
  - `visibleCount` (số 25 → 9) tính đúng theo filter chapter
  - Nút ☑ select-all chỉ chọn subs visible
  - `overlapGroups` (số chuỗi đè ở nút Auto fix) chỉ đếm trong đoạn lọc
  - `done/total` ở topbar — có filter thì hiện "9 dòng (lọc)", "{done}/{total} TTS"
    theo đoạn
  - `swapCharacter` chỉ swap NV trong đoạn lọc (khi đang lọc)
  - Sync `chapters` + `overlapSubIds` vào store để DetailPanel/SpeedSection dùng được
  - Truyền `subtitleIdsFilter` xuống `<AutoFixOverlapModal>`

- `dubeditor_frontend/src/components/DetailPanel.tsx`
  - `done/total/noChar` đếm theo visible khi có filter
  - `bulkTTS` ("TTS tất cả") chỉ gen TTS trong đoạn lọc; label đổi thành
    "Tạo TTS (đoạn đang lọc)"
  - `trimAll` (trim silence bulk) chỉ trim audio trong đoạn lọc
  - `SpeedSection` mode "character" áp tốc độ chỉ cho subs NV trong đoạn lọc
    (gửi `subtitle_ids` xuống BE; không đổi `Character.tts_speed` chung)

- `dubeditor_frontend/src/components/AutoFixOverlapModal.tsx`
  - Nhận prop `subtitleIdsFilter` từ Editor → kèm vào payload API auto-fix
  - Header hiện chip "đoạn đang lọc · N dòng" khi đang scoped

- `dubeditor_frontend/src/components/CharSidebar.tsx`
  - `mapSpeakerToChar` (map SPEAKER_XX → NV thật) chỉ remap subs trong đoạn lọc
    khi có filter; không xóa speaker character nếu còn subs ngoài đoạn lọc tham
    chiếu nó

### Backend
- `dubeditor/schemas.py`
  - `CharacterSetSpeedRequest` thêm field `subtitle_ids: Optional[list[int]] = None`

- `dubeditor/routers/auto_fix.py`
  - `AutoFixRequest` thêm field `subtitle_ids: Optional[List[int]] = None`
  - `auto_fix_overlap` scope query subtitles theo `subtitle_ids` nếu có

- `dubeditor/routers/tts.py`
  - `character/{id}/set-speed` phân nhánh:
    - Có `subtitle_ids` → CHỈ override `tts_speed` cho từng sub trong list,
      KHÔNG đổi `Character.tts_speed` chung (giữ tốc độ NV ngoài đoạn lọc)
    - Không `subtitle_ids` → behavior cũ (đổi `Character.tts_speed` + reset
      mọi override)

## Hành động đã được scope theo filter

| Hành động | Hành vi khi có filter |
|---|---|
| Hiển thị danh sách | Chỉ subs trong đoạn |
| Bộ đếm "N dòng" + "{done}/{total} TTS" topbar | Chỉ trong đoạn (kèm label "lọc") |
| Nút ☑ select-all | Chỉ chọn subs trong đoạn |
| TTS tất cả | Chỉ subs trong đoạn |
| Auto fix overlap | Chỉ subs trong đoạn |
| Trim silence bulk | Chỉ subs trong đoạn |
| Áp tốc độ TTS theo NV | Chỉ subs của NV trong đoạn |
| Đổi NV (swap A→B) | Chỉ subs A trong đoạn |
| Map SPEAKER_XX → NV thật | Chỉ subs SPEAKER trong đoạn |

## Test gợi ý
1. Vào project, tạo chapter, bật filter chapter ở dropdown "Lọc đoạn" — chọn arc 9 dòng
2. Kiểm tra:
   - Số đếm topbar = **9 dòng (lọc)** và **0/9 TTS** ban đầu
   - Nút ☑ → chọn đúng 9 dòng (không phải toàn phim)
   - Bấm "TTS tất cả" → modal nói "Tạo TTS (đoạn đang lọc)" + chỉ enqueue 9 dòng
   - Bấm Auto fix → modal có chip "đoạn đang lọc · 9 dòng"
   - Bỏ filter (Tất cả đoạn) → các số/nút quay về toàn phim như cũ
