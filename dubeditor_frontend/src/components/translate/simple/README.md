# Simple Translator UI v2

Pipeline dịch đơn giản 5 bước, thay thế `TranslatePage` cũ.

## Thay đổi so với v1

**Typography:**
- Bỏ `font-serif` (system serif không đẹp, mỗi máy khác nhau)
- Title dùng `font-semibold/bold` + tăng size, không italic
- Bỏ số La Mã italic → dùng circle badge 1/2/3/4/5 cho rõ ràng hơn
- Tăng contrast text: zinc-500 → zinc-600 cho secondary text
- Tăng padding cards (p-3 → p-3.5/p-4) cho thoáng
- Tăng font-size một số chỗ quá nhỏ (10.5px → 11px)
- Badge mạnh hơn: `bg-X-50` → `bg-X-100` cho dễ đọc

**ConfigPanel mới:**
- File `ConfigPanel.tsx` mới (~500 dòng)
- 3 tab cấu hình: API & Models | Batch & Lọc lỗi | Review & Repair
- Chỉ 4 task AI (Bible / Translate / Repair / QA) — đơn giản hơn ConfigPanel cũ (8+ stages)
- Lưu vào `localStorage` key `simple_translate_config_v1`
- Nút "⚙ Cấu hình" ở header (có badge cảnh báo nếu chưa nhập API key)
- Cũng có thể mở từ Tab II (nút "⚙ Cấu hình batch")
- ESC để đóng modal

**Helpers mới (modelCatalog.ts):**
- `MODELS`: catalog model cho 3 providers (Gemini / OpenAI / DeepSeek)
- `PROVIDER_LABELS`, `TASK_LABELS`: i18n
- `DEFAULT_TASK_MODELS`: mặc định cho 4 task

## Cấu trúc folder

```
simple/
├── TranslatePageSimple.tsx     ← Component chính (entry point)
├── ConfigPanel.tsx             ← Modal cấu hình (3 tabs)
├── modelCatalog.ts             ← Catalog models + labels
├── index.ts                    ← Re-export
├── types.ts                    ← TypeScript types
├── mockData.ts                 ← Mock data tạm
├── README.md                   ← File này
│
├── tabs/                       ← 5 tab content
│   ├── BibleTab.tsx
│   ├── TranslateTab.tsx
│   ├── FilterTab.tsx
│   ├── ReviewTab.tsx
│   └── IssuesTab.tsx
│
└── shared/
    └── SharedUI.tsx            ← PromptResponsePair, PartCard, ModeBar,
                                   StatusBadge, SectionHead, InfoStrip,
                                   TabBadge, TabNumber
```

## Cách tích hợp

### 1. Copy folder `simple/` vào `src/components/translate/`

```bash
# Backup file cũ trước (nếu muốn rollback)
mv dubeditor_frontend/src/components/translate/ConfigPanel.tsx \
   dubeditor_frontend/src/components/translate/ConfigPanel.OLD.tsx

cp -r simple/ dubeditor_frontend/src/components/translate/
```

### 2. Update `App.tsx`

```diff
- import TranslatePage from './components/TranslatePage'
+ import TranslatePage from './components/translate/simple'
```

Props (`projectId`, `onBack`) giữ y nguyên.

### 3. (Optional) Migrate config cũ

Code cũ lưu config ở key `translate_config_v3`. Code mới ở `simple_translate_config_v1`. Nếu muốn migrate keys cũ:

```ts
import { loadSimpleConfig, saveSimpleConfig } from './components/translate/simple'

const oldRaw = localStorage.getItem('translate_config_v3')
if (oldRaw) {
  const old = JSON.parse(oldRaw)
  const newConfig = loadSimpleConfig()
  if (old.api_keys) {
    newConfig.api_keys = old.api_keys
    saveSimpleConfig(newConfig)
  }
}
```

## Sử dụng ConfigPanel độc lập

```tsx
import ConfigPanel, { loadSimpleConfig, type SimpleConfig } from './components/translate/simple'

function MyPage() {
  const [showConfig, setShowConfig] = useState(false)
  const [config, setConfig] = useState<SimpleConfig>(loadSimpleConfig())

  return (
    <>
      <button onClick={() => setShowConfig(true)}>⚙ Cấu hình</button>
      {showConfig && (
        <ConfigPanel
          initialConfig={config}
          onClose={() => setShowConfig(false)}
          onSave={setConfig}
        />
      )}
    </>
  )
}
```

## Tone màu

Dùng đúng tone hiện tại của project (`src/index.css`):

- Background: `#FAFAF7` off-white (light), `#0A0A0B` dark
- Primary: `blue-600`
- Cards: `.surface-card`
- Buttons: `.btn` / `.btn-primary`
- Mono font: `font-mono` Tailwind cho prompt/data
- Status colors: emerald (done), blue (running), amber (warn), red (err)

## API endpoints cần BE implement

Xem chi tiết trong file `README.md` v1 cũ. Tóm tắt:

```
/api/projects/{pid}/simple/
├── bible/{idx}/{save,auto}, bible/merge/{save,auto}, bible/run-all, bible/reset
├── batches/{idx}/{save,auto,reset}, batches/run-from/{idx}, batches/config
├── filter/{stats,scan,auto-fix,push-review}
├── review/{idx}/{save,auto}, review/run-all, review/sub-mode
└── issues/{id}/{refix,manual-edit,resolve}, issues/export.csv
```

Ngoài ra cần endpoint lưu config (optional — vì hiện lưu localStorage):

```
GET  /api/projects/{pid}/simple/config       → SimpleConfig
POST /api/projects/{pid}/simple/config       → body: SimpleConfig
```

## Mock vs Real data

File `mockData.ts` tạo state mẫu để FE chạy được mà chưa cần BE.

Khi BE xong, sửa `TranslatePageSimple.tsx`:

```tsx
// CŨ (dùng mock)
const [bible, setBible] = useState<BibleState>(makeMockBibleState())

// MỚI (fetch từ BE)
const [bible, setBible] = useState<BibleState | null>(null)
useEffect(() => {
  api.get(`/projects/${projectId}/simple/bible`).then(r => setBible(r.data))
}, [projectId])
```

Và thay các `console.log()` trong callbacks bằng API calls thật.

## Notes về UX

- **Header có nút "⚙ Cấu hình"** — luôn truy cập được từ mọi tab
- Nếu chưa nhập API key, nút sẽ có viền vàng + dấu `!` cảnh báo
- **Tab II có nút "⚙ Cấu hình batch"** — mở cùng modal (jump tới tab "Batch")
- ESC để đóng modal
- Modal có 3 tab: API & Models | Batch & Lọc lỗi | Review & Repair
- Mỗi field có hint giải thích tác dụng
- Nút "Reset mặc định" ở footer modal
