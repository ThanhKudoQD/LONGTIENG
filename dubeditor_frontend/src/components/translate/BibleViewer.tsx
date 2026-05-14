/**
 * BibleViewer v3 — hiển thị Bible compact + cho edit từng field.
 *
 * Schema v3 đã bỏ self_address, addresses, social_status, speaking_style.
 * Thay bằng `char` (1 câu tính cách + kiểu nói).
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
    <div className="p-4 max-w-6xl mx-auto">
      {/* Header info */}
      <div className="flex items-center gap-3 mb-4 px-2">
        <div className="text-sm text-zinc-600 dark:text-zinc-400">
          Version <strong className="text-zinc-800 dark:text-zinc-100">{bible.version}</strong>
        </div>
        <div className="flex-1" />
        <div className="text-[11px] text-zinc-500">
          {bible.tokens_in.toLocaleString()} tok in · ${bible.cost_usd.toFixed(4)}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-zinc-200 dark:border-zinc-800">
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
      {tab === 'cast' && <CastTab bible={bible} projectId={projectId} onUpdate={onUpdate} />}
      {tab === 'world' && <WorldTab bible={bible} projectId={projectId} onUpdate={onUpdate} />}
      {tab === 'glossary' && <GlossaryTab bible={bible} projectId={projectId} onUpdate={onUpdate} />}
      {tab === 'raw' && <RawTab bible={bible} projectId={projectId} onUpdate={onUpdate} />}
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

  // Filter
  const filtered = characters.filter(c => {
    if (!query) return true
    const q = query.toLowerCase()
    return c.vi.toLowerCase().includes(q) ||
           c.zh.toLowerCase().includes(q) ||
           (c.char || '').toLowerCase().includes(q) ||
           (c.alias || []).some(a => a.toLowerCase().includes(q))
  })

  // Group theo role
  const grouped: Record<string, BibleCharacter[]> = {}
  for (const c of filtered) {
    const r = c.role || 'phu'
    if (!grouped[r]) grouped[r] = []
    grouped[r].push(c)
  }

  const roleOrder = ['nam_chinh', 'nu_chinh', 'nam_phu', 'nu_phu', 'phan_dien', 'phu', 'khach']

  if (characters.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-zinc-500 italic">
        Chưa có nhân vật. Chạy Stage 1 để trích xuất.
      </div>
    )
  }

  return (
    <div>
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Tìm nhân vật (tên VI / TQ / tính cách)..."
        className="input w-full mb-4 max-w-md"
      />

      {roleOrder.filter(r => grouped[r]?.length).map(role => (
        <section key={role} className="mb-4">
          <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest px-2 py-1 bg-zinc-50 dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800 flex items-center gap-2">
            <span>{ROLE_LABELS[role] || role}</span>
            <span className="text-zinc-400 font-normal">({grouped[role].length})</span>
          </div>
          <div>
            {grouped[role].map(c => (
              <CharacterCard
                key={c.zh || c.vi}
                ch={c}
                allCharacters={characters}
                expanded={expandedZh === c.zh}
                onToggle={() => setExpandedZh(expandedZh === c.zh ? null : c.zh)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function CharacterCard({ ch, allCharacters, expanded, onToggle }: {
  ch: BibleCharacter
  allCharacters: BibleCharacter[]
  expanded: boolean
  onToggle: () => void
}) {
  const charByZh = new Map(allCharacters.map(c => [c.zh, c]))
  const genderIcon = ch.g === 'nam' ? '♂' : ch.g === 'nu' ? '♀' : '·'
  const genderColor = ch.g === 'nam' ? 'text-blue-500' : ch.g === 'nu' ? 'text-pink-500' : 'text-zinc-400'

  return (
    <div className="border-b border-zinc-100 dark:border-zinc-800">
      {/* Compact row — luôn hiện */}
      <button
        onClick={onToggle}
        className="w-full grid grid-cols-[20px_120px_20px_1fr_auto_auto] gap-3 items-center px-3 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-900/50 text-left"
      >
        <span className={`text-[15px] font-bold ${genderColor}`}>{genderIcon}</span>
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
        <span className="text-[11px] text-zinc-400 italic truncate max-w-[300px]">
          {ch.char || ''}
        </span>
        <span className="text-[10px] text-zinc-400 ml-2 w-3">
          {expanded ? '▼' : '▶'}
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-12 py-3 bg-zinc-50/50 dark:bg-zinc-900/50 text-[12px] space-y-2 border-l-2 border-blue-200 dark:border-blue-900 ml-3">
          {/* Aliases */}
          {ch.alias && ch.alias.length > 0 && (
            <div>
              <span className="text-zinc-500 mr-2">Biệt danh:</span>
              <span className="text-zinc-700 dark:text-zinc-300">
                {ch.alias.join(' · ')}
              </span>
            </div>
          )}

          {/* Catchphrase */}
          {ch.catchphrase && (
            <div>
              <span className="text-zinc-500 mr-2">Câu cửa miệng:</span>
              <em className="text-zinc-700 dark:text-zinc-300">"{ch.catchphrase}"</em>
            </div>
          )}

          {/* Relationships */}
          {ch.rel && Object.keys(ch.rel).length > 0 && (
            <div>
              <div className="text-zinc-500 mb-1">Quan hệ:</div>
              <div className="pl-3 space-y-0.5">
                {Object.entries(ch.rel).map(([otherZh, relation]) => {
                  const other = charByZh.get(otherZh)
                  const label = other
                    ? <><strong>{other.vi}</strong> <span className="text-zinc-400">({otherZh})</span></>
                    : otherZh
                  return (
                    <div key={otherZh} className="text-zinc-700 dark:text-zinc-300">
                      <span className="text-zinc-400 mr-2">↔</span>
                      {label}: <em className="text-zinc-600 dark:text-zinc-400">{relation}</em>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
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
  if (!w) return <div className="text-sm text-zinc-500">Không có world data</div>

  return (
    <div className="space-y-5 max-w-3xl">
      {/* Genre */}
      {w.genre && w.genre.length > 0 && (
        <div>
          <SectionLabel>Thể loại</SectionLabel>
          <div className="flex flex-wrap gap-1.5">
            {w.genre.map(g => (
              <span key={g}
                className="px-2 py-0.5 rounded-full text-[12px] bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
                {g}
              </span>
            ))}
            {w.era && (
              <span className="px-2 py-0.5 rounded-full text-[12px] bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                {w.era}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Tone */}
      {w.tone && (
        <div>
          <SectionLabel>Tone tổng thể</SectionLabel>
          <div className="text-sm text-zinc-700 dark:text-zinc-300">{w.tone}</div>
        </div>
      )}

      {/* Plot */}
      {w.plot && (
        <div>
          <SectionLabel>Cốt truyện</SectionLabel>
          <div className="text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed">
            {w.plot}
          </div>
        </div>
      )}

      {/* Arcs */}
      {w.arcs && w.arcs.length > 0 && (
        <div>
          <SectionLabel>Story Arcs ({w.arcs.length})</SectionLabel>
          <div className="space-y-2">
            {w.arcs.map((arc: BibleStoryArc) => (
              <div key={arc.index}
                className="border border-zinc-200 dark:border-zinc-700 rounded-lg p-3 bg-zinc-50/50 dark:bg-zinc-900/50">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-mono text-zinc-400">
                    #{arc.index + 1}
                  </span>
                  <strong className="text-zinc-800 dark:text-zinc-100">
                    {arc.t}
                  </strong>
                  {arc.tone && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
                      {ARC_TONE_LABELS[arc.tone] || arc.tone}
                    </span>
                  )}
                  <span className="ml-auto text-[11px] text-zinc-500 font-mono">
                    {arc.r[0]} – {arc.r[1]}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
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
      <div className="p-8 text-center text-sm text-zinc-500 italic">
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
  // Sort terms trong mỗi category theo n giảm dần
  for (const cat of Object.keys(byCategory)) {
    byCategory[cat].sort((a, b) => (b.n || 0) - (a.n || 0))
  }

  return (
    <div className="space-y-1">
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Tìm thuật ngữ..."
        className="input w-full mb-3 max-w-md"
      />

      {GLOSSARY_CAT_ORDER.filter(cat => byCategory[cat]?.length).map(cat => (
        <section key={cat} className="mb-4">
          <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest px-2 py-1 bg-zinc-50 dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800">
            {GLOSSARY_CAT_LABELS[cat] || cat} ({byCategory[cat].length})
          </div>
          <div>
            {byCategory[cat].map(t => (
              <GlossaryRow key={t.zh + '|' + t.vi} term={t} />
            ))}
          </div>
        </section>
      ))}

      {/* Categories không có trong ORDER nhưng có data */}
      {Object.keys(byCategory).filter(cat => !GLOSSARY_CAT_ORDER.includes(cat)).map(cat => (
        <section key={cat} className="mb-4">
          <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest px-2 py-1 bg-zinc-50 dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800">
            {GLOSSARY_CAT_LABELS[cat] || cat} ({byCategory[cat].length})
          </div>
          <div>
            {byCategory[cat].map(t => (
              <GlossaryRow key={t.zh + '|' + t.vi} term={t} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function GlossaryRow({ term }: { term: GlossaryTerm }) {
  return (
    <div className="grid grid-cols-[120px_20px_1fr_auto] gap-3 items-center px-3 py-2 border-b border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-900/50 text-[13px]">
      <span className="font-medium text-zinc-700 dark:text-zinc-300 truncate">{term.zh}</span>
      <span className="text-zinc-300 dark:text-zinc-600 text-center">→</span>
      <span className="text-zinc-900 dark:text-zinc-100">{term.vi}</span>
      <span className="text-[11px] text-zinc-400 italic text-right truncate max-w-[300px]">
        {term.note || ''}
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

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const parsed = JSON.parse(json)
      await translateApi.updateBible(projectId, parsed)
      onUpdate()
    } catch (e: any) {
      setError(e.message || 'JSON parse error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="text-[11px] text-zinc-500">
        Edit Bible JSON trực tiếp (cẩn thận với schema).
      </div>
      {error && (
        <div className="text-[12px] text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded p-2">
          ❌ {error}
        </div>
      )}
      <textarea
        value={json}
        onChange={e => setJson(e.target.value)}
        className="input w-full font-mono text-[11px] min-h-[400px]"
        spellCheck={false}
      />
      <div className="flex gap-2">
        <button onClick={handleSave} disabled={saving}
          className="btn-primary">
          {saving ? 'Đang lưu...' : '💾 Lưu Bible'}
        </button>
      </div>
    </div>
  )
}

// ─── Small helpers ───────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-2">
      {children}
    </div>
  )
}

function TabBtn({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 text-[12px] font-medium border-b-2 transition-all ${
        active
          ? 'border-blue-500 text-blue-700 dark:text-blue-300'
          : 'border-transparent text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300'
      }`}
    >
      {children}
    </button>
  )
}
