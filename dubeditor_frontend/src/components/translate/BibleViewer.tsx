/**
 * BibleViewer v3 — redesign với UI rõ ràng:
 *   - Card outer có border + shadow nhẹ
 *   - Mỗi section (role/category) là card riêng với header màu
 *   - Hàng có hover state, divider rõ ràng
 *   - Spacing thoáng đãng dễ đọc
 *
 * Tabs: Cast | World | Glossary | Raw JSON
 */
import React, { useState } from 'react'
import { translateApi } from '../../api'
import type { Bible, BibleCharacter, GlossaryTerm, BibleStoryArc } from '../../types'
import { ROLE_LABELS, ARC_TONE_LABELS, GLOSSARY_CAT_LABELS, GLOSSARY_CAT_ORDER } from '../../types'

type BibleTab = 'cast' | 'world' | 'glossary' | 'raw'

export default function BibleViewer({
  projectId, bible, onUpdate,
}: {
  projectId: number
  bible: Bible | null
  onUpdate: () => void
}) {
  const [tab, setTab] = useState<BibleTab>('cast')

  if (!bible) {
    return (
      <div className="p-8 text-center text-zinc-500">
        <div className="text-4xl mb-3">📖</div>
        <div className="text-sm">Chưa có Bible. Chạy Stage 1 để tạo.</div>
      </div>
    )
  }

  return (
    <div className="p-5 max-w-6xl mx-auto">
      {/* Outer card */}
      <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm overflow-hidden">

        {/* Header */}
        <div className="px-5 py-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center gap-3 bg-zinc-50/60 dark:bg-zinc-900/70">
          <div className="text-[13px] text-zinc-600 dark:text-zinc-400">
            Version <strong className="text-zinc-800 dark:text-zinc-100">{bible.version}</strong>
          </div>
          <div className="flex-1" />
          <div className="text-[11px] text-zinc-500 font-mono">
            {bible.tokens_in.toLocaleString()} tok in · ${bible.cost_usd.toFixed(4)}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex px-3 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
          <TabBtn active={tab === 'cast'} onClick={() => setTab('cast')}>
            👥 Nhân vật ({bible.cast?.characters?.length || 0})
          </TabBtn>
          <TabBtn active={tab === 'world'} onClick={() => setTab('world')}>
            🌍 Bối cảnh
          </TabBtn>
          <TabBtn active={tab === 'glossary'} onClick={() => setTab('glossary')}>
            📚 Thuật ngữ ({bible.glossary?.terms?.length || 0})
          </TabBtn>
          <TabBtn active={tab === 'raw'} onClick={() => setTab('raw')}>
            {} JSON
          </TabBtn>
        </div>

        {/* Content */}
        <div className="bg-[#FAFAF7] dark:bg-zinc-950/30 p-5">
          {tab === 'cast' && <CastTab bible={bible} projectId={projectId} onUpdate={onUpdate} />}
          {tab === 'world' && <WorldTab bible={bible} projectId={projectId} onUpdate={onUpdate} />}
          {tab === 'glossary' && <GlossaryTab bible={bible} projectId={projectId} onUpdate={onUpdate} />}
          {tab === 'raw' && <RawTab bible={bible} projectId={projectId} onUpdate={onUpdate} />}
        </div>
      </div>
    </div>
  )
}

// ─── CAST ────────────────────────────────────────────────────────────────────

function CastTab({ bible, projectId, onUpdate }: {
  bible: Bible; projectId: number; onUpdate: () => void
}) {
  const characters = bible.cast?.characters || []
  const [expandedZh, setExpandedZh] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const filtered = characters.filter(c => {
    if (!query) return true
    const q = query.toLowerCase()
    return c.vi.toLowerCase().includes(q) ||
           c.zh.toLowerCase().includes(q) ||
           (c.char || '').toLowerCase().includes(q) ||
           (c.alias || []).some(a => a.toLowerCase().includes(q))
  })

  const grouped: Record<string, BibleCharacter[]> = {}
  for (const c of filtered) {
    const r = c.role || 'phu'
    if (!grouped[r]) grouped[r] = []
    grouped[r].push(c)
  }

  const roleOrder = ['nam_chinh', 'nu_chinh', 'nam_phu', 'nu_phu', 'phan_dien', 'phu', 'khach']

  // Mỗi role có 1 màu accent
  const roleAccent: Record<string, { bg: string; text: string; dot: string }> = {
    nam_chinh: { bg: 'bg-blue-50 dark:bg-blue-950/30', text: 'text-blue-700 dark:text-blue-300', dot: 'bg-blue-500' },
    nu_chinh:  { bg: 'bg-pink-50 dark:bg-pink-950/30', text: 'text-pink-700 dark:text-pink-300', dot: 'bg-pink-500' },
    nam_phu:   { bg: 'bg-cyan-50 dark:bg-cyan-950/30', text: 'text-cyan-700 dark:text-cyan-300', dot: 'bg-cyan-500' },
    nu_phu:    { bg: 'bg-fuchsia-50 dark:bg-fuchsia-950/30', text: 'text-fuchsia-700 dark:text-fuchsia-300', dot: 'bg-fuchsia-500' },
    phan_dien: { bg: 'bg-red-50 dark:bg-red-950/30', text: 'text-red-700 dark:text-red-300', dot: 'bg-red-500' },
    phu:       { bg: 'bg-zinc-50 dark:bg-zinc-900/50', text: 'text-zinc-700 dark:text-zinc-300', dot: 'bg-zinc-400' },
    khach:     { bg: 'bg-zinc-50 dark:bg-zinc-900/50', text: 'text-zinc-600 dark:text-zinc-400', dot: 'bg-zinc-300' },
  }

  if (characters.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-zinc-500 italic bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-800">
        Chưa có nhân vật. Chạy Stage 1 để trích xuất.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Search */}
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Tìm nhân vật (tên VI / TQ / tính cách)..."
        className="input w-full max-w-md"
      />

      {/* Role sections */}
      {roleOrder.filter(r => grouped[r]?.length).map(role => {
        const accent = roleAccent[role] || roleAccent.phu
        return (
          <section key={role}
            className="bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-800 shadow-sm overflow-hidden">
            {/* Section header */}
            <div className={`px-4 py-2.5 border-b border-zinc-200 dark:border-zinc-800 flex items-center gap-2 ${accent.bg}`}>
              <span className={`w-2 h-2 rounded-full ${accent.dot}`} />
              <span className={`text-[11px] font-bold uppercase tracking-wider ${accent.text}`}>
                {ROLE_LABELS[role] || role}
              </span>
              <span className={`text-[11px] font-medium ${accent.text} opacity-70`}>
                ({grouped[role].length})
              </span>
            </div>

            {/* Character rows */}
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {grouped[role].map(c => (
                <CharacterRow
                  key={c.zh || c.vi}
                  ch={c}
                  allCharacters={characters}
                  expanded={expandedZh === c.zh}
                  onToggle={() => setExpandedZh(expandedZh === c.zh ? null : c.zh)}
                />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function CharacterRow({ ch, allCharacters, expanded, onToggle }: {
  ch: BibleCharacter
  allCharacters: BibleCharacter[]
  expanded: boolean
  onToggle: () => void
}) {
  const charByZh = new Map(allCharacters.map(c => [c.zh, c]))
  const genderIcon = ch.g === 'nam' ? '♂' : ch.g === 'nu' ? '♀' : '·'
  const genderColor = ch.g === 'nam' ? 'text-blue-500' : ch.g === 'nu' ? 'text-pink-500' : 'text-zinc-400'

  return (
    <div className={expanded ? 'bg-zinc-50/60 dark:bg-zinc-900/40' : ''}>
      {/* Compact row */}
      <button
        onClick={onToggle}
        className="w-full grid grid-cols-[24px_130px_24px_1fr_auto_24px] gap-3 items-center px-4 py-2.5 hover:bg-zinc-50 dark:hover:bg-zinc-900/50 text-left transition-colors"
      >
        <span className={`text-[16px] font-bold ${genderColor}`}>{genderIcon}</span>
        <span className="font-medium text-zinc-700 dark:text-zinc-300 truncate">
          {ch.zh}
        </span>
        <span className="text-zinc-300 dark:text-zinc-600 text-center">→</span>
        <span className="text-zinc-900 dark:text-zinc-100 truncate">
          <strong>{ch.vi}</strong>
          {ch.age && (
            <span className="ml-2 text-[11px] text-zinc-400 font-normal">{ch.age}</span>
          )}
        </span>
        <span className="text-[12px] text-zinc-500 dark:text-zinc-400 italic truncate max-w-[420px]">
          {ch.char || ''}
        </span>
        <span className={`text-[10px] text-zinc-400 transition-transform ${expanded ? 'rotate-90' : ''}`}>
          ▶
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pt-1 text-[12px] space-y-2 border-t border-zinc-100 dark:border-zinc-800">
          <div className="pl-7 space-y-2">
            {/* Aliases */}
            {ch.alias && ch.alias.length > 0 && (
              <div className="flex gap-2">
                <span className="text-zinc-500 w-28 flex-shrink-0 font-medium">Biệt danh:</span>
                <span className="text-zinc-700 dark:text-zinc-300 flex-1">
                  {ch.alias.join(' · ')}
                </span>
              </div>
            )}

            {/* Catchphrase */}
            {ch.catchphrase && (
              <div className="flex gap-2">
                <span className="text-zinc-500 w-28 flex-shrink-0 font-medium">Câu cửa miệng:</span>
                <em className="text-zinc-700 dark:text-zinc-300 flex-1">"{ch.catchphrase}"</em>
              </div>
            )}

            {/* Relationships */}
            {ch.rel && Object.keys(ch.rel).length > 0 && (
              <div className="flex gap-2">
                <span className="text-zinc-500 w-28 flex-shrink-0 font-medium">Quan hệ:</span>
                <div className="flex-1 space-y-1">
                  {Object.entries(ch.rel).map(([otherZh, relation]) => {
                    const other = charByZh.get(otherZh)
                    return (
                      <div key={otherZh} className="text-zinc-700 dark:text-zinc-300 flex gap-2 items-baseline">
                        <span className="text-zinc-400">↔</span>
                        {other ? (
                          <>
                            <strong className="text-zinc-800 dark:text-zinc-100">{other.vi}</strong>
                            <span className="text-zinc-400 text-[11px]">({otherZh})</span>
                          </>
                        ) : (
                          <span className="font-medium">{otherZh}</span>
                        )}
                        <span className="text-zinc-500">·</span>
                        <em className="text-zinc-600 dark:text-zinc-400">{relation}</em>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Nếu không có gì */}
            {(!ch.alias || ch.alias.length === 0) && !ch.catchphrase && (!ch.rel || Object.keys(ch.rel).length === 0) && (
              <div className="text-zinc-400 italic text-[11px]">Không có thông tin chi tiết</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── WORLD ───────────────────────────────────────────────────────────────────

function WorldTab({ bible, projectId, onUpdate }: {
  bible: Bible; projectId: number; onUpdate: () => void
}) {
  const w = bible.world
  if (!w) {
    return (
      <div className="p-8 text-center text-sm text-zinc-500 italic bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-800">
        Không có world data
      </div>
    )
  }

  return (
    <div className="space-y-4 max-w-3xl">
      {/* Genre + Era card */}
      {(w.genre?.length > 0 || w.era) && (
        <Card title="Thể loại">
          <div className="flex flex-wrap gap-2">
            {w.genre?.map(g => (
              <span key={g}
                className="px-2.5 py-1 rounded-md text-[12px] font-medium bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                {g}
              </span>
            ))}
            {w.era && (
              <span className="px-2.5 py-1 rounded-md text-[12px] font-medium bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700">
                ⏳ {w.era}
              </span>
            )}
          </div>
        </Card>
      )}

      {/* Tone */}
      {w.tone && (
        <Card title="Tone tổng thể">
          <div className="text-[13px] text-zinc-700 dark:text-zinc-300 leading-relaxed">{w.tone}</div>
        </Card>
      )}

      {/* Plot */}
      {w.plot && (
        <Card title="Cốt truyện">
          <div className="text-[13px] text-zinc-700 dark:text-zinc-300 leading-relaxed">
            {w.plot}
          </div>
        </Card>
      )}

      {/* Arcs */}
      {w.arcs && w.arcs.length > 0 && (
        <Card title={`Story Arcs (${w.arcs.length})`}>
          <div className="space-y-2">
            {w.arcs.map((arc: BibleStoryArc) => (
              <div key={arc.index}
                className="border border-zinc-200 dark:border-zinc-700 rounded-md p-3 bg-zinc-50/50 dark:bg-zinc-900/40">
                <div className="flex items-center gap-2 flex-wrap mb-1.5">
                  <span className="text-[10px] font-mono text-zinc-400 bg-white dark:bg-zinc-800 px-1.5 py-0.5 rounded border border-zinc-200 dark:border-zinc-700">
                    #{arc.index + 1}
                  </span>
                  <strong className="text-zinc-800 dark:text-zinc-100">
                    {arc.t}
                  </strong>
                  {arc.tone && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 font-medium">
                      {ARC_TONE_LABELS[arc.tone] || arc.tone}
                    </span>
                  )}
                  <span className="ml-auto text-[11px] text-zinc-500 font-mono">
                    L{arc.r[0]} – L{arc.r[1]}
                  </span>
                </div>
                {arc.summary && (
                  <div className="text-[12px] text-zinc-600 dark:text-zinc-400 leading-relaxed pl-1">
                    {arc.summary}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-800 shadow-sm overflow-hidden">
      <div className="px-4 py-2.5 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/70">
        <span className="text-[11px] font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
          {title}
        </span>
      </div>
      <div className="p-4">
        {children}
      </div>
    </div>
  )
}

// ─── GLOSSARY ────────────────────────────────────────────────────────────────

function GlossaryTab({ bible, projectId, onUpdate }: {
  bible: Bible; projectId: number; onUpdate: () => void
}) {
  const terms = bible.glossary?.terms || []
  const [query, setQuery] = useState('')

  const filtered = terms.filter(t => {
    if (!query) return true
    const q = query.toLowerCase()
    return t.zh.toLowerCase().includes(q) ||
           t.vi.toLowerCase().includes(q) ||
           (t.note || '').toLowerCase().includes(q)
  })

  if (terms.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-zinc-500 italic bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-800">
        Chưa có thuật ngữ. Chạy lại Stage 1 để trích xuất.
      </div>
    )
  }

  // Group theo category
  const byCategory: Record<string, GlossaryTerm[]> = {}
  for (const t of filtered) {
    const cat = t.cat || 'khac'
    if (!byCategory[cat]) byCategory[cat] = []
    byCategory[cat].push(t)
  }
  for (const cat of Object.keys(byCategory)) {
    byCategory[cat].sort((a, b) => (b.n || 0) - (a.n || 0))
  }

  // Color theme per category
  const catColor: Record<string, { bg: string; text: string; dot: string }> = {
    tu_xung:   { bg: 'bg-purple-50 dark:bg-purple-950/30', text: 'text-purple-700 dark:text-purple-300', dot: 'bg-purple-500' },
    chuc_vu:   { bg: 'bg-blue-50 dark:bg-blue-950/30',     text: 'text-blue-700 dark:text-blue-300',     dot: 'bg-blue-500' },
    dia_danh:  { bg: 'bg-emerald-50 dark:bg-emerald-950/30', text: 'text-emerald-700 dark:text-emerald-300', dot: 'bg-emerald-500' },
    khai_niem: { bg: 'bg-amber-50 dark:bg-amber-950/30',   text: 'text-amber-700 dark:text-amber-300',   dot: 'bg-amber-500' },
    cliche:    { bg: 'bg-pink-50 dark:bg-pink-950/30',     text: 'text-pink-700 dark:text-pink-300',     dot: 'bg-pink-500' },
    khac:      { bg: 'bg-zinc-50 dark:bg-zinc-900/50',     text: 'text-zinc-600 dark:text-zinc-400',     dot: 'bg-zinc-400' },
  }

  const orderedCats = [
    ...GLOSSARY_CAT_ORDER.filter(cat => byCategory[cat]?.length),
    ...Object.keys(byCategory).filter(cat => !GLOSSARY_CAT_ORDER.includes(cat)),
  ]

  return (
    <div className="space-y-4">
      {/* Search */}
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Tìm thuật ngữ..."
        className="input w-full max-w-md"
      />

      {/* Category sections */}
      {orderedCats.map(cat => {
        const accent = catColor[cat] || catColor.khac
        return (
          <section key={cat}
            className="bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-800 shadow-sm overflow-hidden">
            {/* Section header */}
            <div className={`px-4 py-2.5 border-b border-zinc-200 dark:border-zinc-800 flex items-center gap-2 ${accent.bg}`}>
              <span className={`w-2 h-2 rounded-full ${accent.dot}`} />
              <span className={`text-[11px] font-bold uppercase tracking-wider ${accent.text}`}>
                {GLOSSARY_CAT_LABELS[cat] || cat}
              </span>
              <span className={`text-[11px] font-medium ${accent.text} opacity-70`}>
                ({byCategory[cat].length})
              </span>
            </div>

            {/* Rows */}
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {byCategory[cat].map(t => (
                <GlossaryRow key={t.zh + '|' + t.vi} term={t} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function GlossaryRow({ term }: { term: GlossaryTerm }) {
  return (
    <div className="grid grid-cols-[140px_24px_1fr_auto] gap-3 items-center px-4 py-2.5 hover:bg-zinc-50 dark:hover:bg-zinc-900/50 transition-colors">
      <span className="font-medium text-zinc-700 dark:text-zinc-300 truncate">{term.zh}</span>
      <span className="text-zinc-300 dark:text-zinc-600 text-center">→</span>
      <span className="text-zinc-900 dark:text-zinc-100 font-medium">{term.vi}</span>
      <span className="text-[11px] text-zinc-500 italic text-right truncate max-w-[360px]">
        {term.note || ''}
        {term.n != null && term.n > 1 && (
          <span className="ml-2 text-zinc-400 font-mono not-italic">×{term.n}</span>
        )}
      </span>
    </div>
  )
}

// ─── RAW JSON ────────────────────────────────────────────────────────────────

function RawTab({ bible, projectId, onUpdate }: {
  bible: Bible; projectId: number; onUpdate: () => void
}) {
  const [json, setJson] = useState(() => JSON.stringify({
    cast: bible.cast,
    world: bible.world,
    glossary: bible.glossary,
  }, null, 2))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  async function handleSave() {
    setSaving(true)
    setError(null)
    setSuccess(false)
    try {
      const parsed = JSON.parse(json)
      await translateApi.updateBible(projectId, parsed)
      onUpdate()
      setSuccess(true)
      setTimeout(() => setSuccess(false), 2000)
    } catch (e: any) {
      setError(e.message || 'JSON parse error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-800 shadow-sm overflow-hidden">
      <div className="px-4 py-2.5 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/70 flex items-center gap-3">
        <span className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider">
          Bible JSON
        </span>
        <span className="text-[11px] text-zinc-500">
          Edit trực tiếp (cẩn thận với schema)
        </span>
        <div className="flex-1" />
        {success && (
          <span className="text-[11px] text-green-600 dark:text-green-400 font-medium">
            ✓ Đã lưu
          </span>
        )}
        <button onClick={handleSave} disabled={saving}
          className="btn-primary text-[12px]">
          {saving ? '⏳ Đang lưu...' : '💾 Lưu Bible'}
        </button>
      </div>

      {error && (
        <div className="px-4 py-2 text-[12px] text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border-b border-red-200 dark:border-red-900">
          ❌ {error}
        </div>
      )}

      <textarea
        value={json}
        onChange={e => setJson(e.target.value)}
        className="w-full font-mono text-[11px] min-h-[500px] p-4 bg-zinc-50/30 dark:bg-zinc-950/30 text-zinc-800 dark:text-zinc-200 focus:outline-none resize-y leading-relaxed"
        spellCheck={false}
      />
    </div>
  )
}

// ─── Small helpers ───────────────────────────────────────────────────────────

function TabBtn({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2.5 text-[13px] font-medium border-b-2 -mb-[1px] transition-all ${
        active
          ? 'border-blue-500 text-blue-700 dark:text-blue-300 bg-blue-50/40 dark:bg-blue-900/10'
          : 'border-transparent text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-900/50'
      }`}
    >
      {children}
    </button>
  )
}
