/**
 * BibleViewer — hiển thị Bible đầy đủ + cho edit từng field.
 *
 * Tabs nội bộ: Cast | World | Glossary | Raw JSON
 * - Cast: list các nhân vật, click expand xem chi tiết, edit role/personality
 * - World: genre + setting + plot + arcs
 * - Glossary: list thuật ngữ, có thể sửa
 * - Raw: edit JSON trực tiếp (cho power user)
 */
import React, { useState } from 'react'
import { translateApi } from '../../api'
import type { Bible, BibleCharacter, GlossaryTerm } from '../../types'
import { ROLE_LABELS, GENRE_MAIN_LABELS, GENRE_SUB_LABELS } from '../../types'

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
        {bible.genre_pack_id && (
          <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">
            🎭 {bible.genre_pack_id}
          </span>
        )}
        <div className="flex-1" />
        <div className="text-[11px] text-zinc-500">
          {bible.tokens_in.toLocaleString()} tok in · ${bible.cost_usd.toFixed(4)}
        </div>
      </div>

      {/* Sub-tabs */}
      <div className="flex items-center gap-2 mb-4 px-2 border-b border-zinc-200 dark:border-zinc-800">
        <SubTab active={tab === 'cast'} onClick={() => setTab('cast')}>
          🧑 Nhân vật ({bible.cast?.characters?.length || 0})
        </SubTab>
        <SubTab active={tab === 'world'} onClick={() => setTab('world')}>
          🌍 Bối cảnh
        </SubTab>
        <SubTab active={tab === 'glossary'} onClick={() => setTab('glossary')}>
          📚 Thuật ngữ ({bible.glossary?.terms?.length || 0})
        </SubTab>
        <SubTab active={tab === 'raw'} onClick={() => setTab('raw')}>
          {} Raw JSON
        </SubTab>
      </div>

      {tab === 'cast' && <CastView bible={bible} projectId={projectId} onUpdate={onUpdate} />}
      {tab === 'world' && <WorldView bible={bible} />}
      {tab === 'glossary' && <GlossaryView bible={bible} projectId={projectId} onUpdate={onUpdate} />}
      {tab === 'raw' && <RawView bible={bible} projectId={projectId} onUpdate={onUpdate} />}
    </div>
  )
}

function SubTab({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 text-[12px] font-medium border-b-2 -mb-px transition-colors ${
        active
          ? 'border-blue-500 text-blue-600 dark:text-blue-400'
          : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
      }`}
    >
      {children}
    </button>
  )
}

// ─── CAST ────────────────────────────────────────────────────────────────────

function CastView({ bible, projectId, onUpdate }: {
  bible: Bible; projectId: number; onUpdate: () => void
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)
  const chars = bible.cast?.characters || []

  // Group by role
  const byRole = chars.reduce<Record<string, BibleCharacter[]>>((acc, c) => {
    const role = c.role || 'phu'
    acc[role] = acc[role] || []
    acc[role].push(c)
    return acc
  }, {})

  const order = ['nam_chinh', 'nu_chinh', 'nam_phu', 'nu_phu', 'phan_dien', 'phu', 'khach']

  return (
    <div className="space-y-4">
      {order.filter(r => byRole[r]?.length > 0).map(role => (
        <div key={role}>
          <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-2 px-2">
            {ROLE_LABELS[role] || role} ({byRole[role].length})
          </div>
          <div className="space-y-2">
            {byRole[role].map((char, _i) => {
              const idx = chars.indexOf(char)
              const isOpen = expandedIdx === idx
              return (
                <div key={idx} className="bg-white dark:bg-zinc-950 rounded-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden">
                  <button
                    onClick={() => setExpandedIdx(isOpen ? null : idx)}
                    className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-zinc-800 dark:text-zinc-100">{char.vi}</span>
                        <span className="text-[11px] text-zinc-400">{char.zh}</span>
                        {char.gender !== '?' && (
                          <span className="text-[11px] text-zinc-500">· {char.gender === 'nam' ? '♂' : '♀'}</span>
                        )}
                        {char.age_group && (
                          <span className="text-[11px] text-zinc-500">· {char.age_group}</span>
                        )}
                      </div>
                      {char.speaking_style && (
                        <div className="text-[11px] text-zinc-500 mt-0.5 truncate">
                          {char.speaking_style}
                        </div>
                      )}
                    </div>
                    <span className="text-zinc-400">{isOpen ? '▾' : '▸'}</span>
                  </button>

                  {isOpen && (
                    <div className="px-4 pb-4 pt-2 border-t border-zinc-100 dark:border-zinc-800 text-sm space-y-2">
                      {char.social_status && (
                        <div><span className="text-zinc-500">Vị trí: </span>{char.social_status}</div>
                      )}
                      {char.personality && (
                        <div><span className="text-zinc-500">Tính cách: </span>{char.personality}</div>
                      )}
                      {char.self_address && (
                        <div>
                          <span className="text-zinc-500">Tự xưng: </span>
                          <span className="font-medium">{char.self_address.default}</span>
                          {char.self_address.when_angry && (
                            <span className="text-zinc-500"> · giận: <span className="text-zinc-700 dark:text-zinc-300">{char.self_address.when_angry}</span></span>
                          )}
                          {char.self_address.when_intimate && (
                            <span className="text-zinc-500"> · thân mật: <span className="text-zinc-700 dark:text-zinc-300">{char.self_address.when_intimate}</span></span>
                          )}
                        </div>
                      )}
                      {char.addresses && Object.keys(char.addresses).length > 0 && (
                        <div>
                          <span className="text-zinc-500">Gọi người khác: </span>
                          {Object.entries(char.addresses).map(([target, how]) => (
                            <span key={target} className="inline-block mr-2 px-2 py-0.5 rounded text-[11px] bg-zinc-100 dark:bg-zinc-800">
                              {target} → "{how}"
                            </span>
                          ))}
                        </div>
                      )}
                      {char.relationships && Object.keys(char.relationships).length > 0 && (
                        <div>
                          <span className="text-zinc-500">Quan hệ: </span>
                          {Object.entries(char.relationships).map(([target, rel]) => (
                            <span key={target} className="inline-block mr-2 px-2 py-0.5 rounded text-[11px] bg-zinc-100 dark:bg-zinc-800">
                              {target} = {rel}
                            </span>
                          ))}
                        </div>
                      )}
                      {char.notes && (
                        <div className="text-[12px] text-zinc-500 italic border-l-2 border-zinc-200 dark:border-zinc-700 pl-2">
                          {char.notes}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── WORLD ───────────────────────────────────────────────────────────────────

function WorldView({ bible }: { bible: Bible }) {
  const w = bible.world
  if (!w) return <div className="text-zinc-500 p-4">Chưa có world data.</div>

  return (
    <div className="space-y-4">
      <div className="bg-white dark:bg-zinc-950 rounded-lg border border-zinc-200 dark:border-zinc-800 p-4">
        <div className="grid grid-cols-2 gap-4 mb-3">
          <Field label="Thể loại chính" value={GENRE_MAIN_LABELS[w.genre_main] || w.genre_main} />
          <Field label="Thể loại phụ" value={w.genre_sub?.map(g => GENRE_SUB_LABELS[g] || g).join(', ') || '—'} />
          <Field label="Thời đại" value={w.era || '—'} />
          <Field label="Bối cảnh" value={w.setting || '—'} />
        </div>
        <Field label="Tone tổng thể" value={w.tone_overall || '—'} />
        <div className="mt-3">
          <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1">
            Tóm tắt cốt truyện
          </div>
          <div className="text-sm text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap">
            {w.plot_summary || '—'}
          </div>
        </div>
        {w.main_conflict && (
          <div className="mt-3">
            <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1">
              Xung đột chính
            </div>
            <div className="text-sm text-zinc-700 dark:text-zinc-300">{w.main_conflict}</div>
          </div>
        )}
      </div>

      {/* Story arcs */}
      {w.story_arcs?.length > 0 && (
        <div>
          <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-2 px-2">
            Story Arcs ({w.story_arcs.length})
          </div>
          <div className="space-y-2">
            {w.story_arcs.map((arc) => (
              <div key={arc.index} className="bg-white dark:bg-zinc-950 rounded-lg border border-zinc-200 dark:border-zinc-800 p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[11px] font-semibold text-zinc-400">#{arc.index + 1}</span>
                  <span className="font-medium text-zinc-800 dark:text-zinc-100">{arc.title}</span>
                  <span className="text-[11px] text-zinc-400">
                    · dòng {arc.start_line}-{arc.end_line}
                  </span>
                </div>
                <div className="text-[12px] text-zinc-600 dark:text-zinc-400 mb-1">
                  {arc.summary}
                </div>
                {arc.emotional_tone && (
                  <div className="text-[11px] text-zinc-500 italic">
                    Tone: {arc.emotional_tone}
                  </div>
                )}
                {arc.key_events?.length > 0 && (
                  <div className="mt-1.5 text-[11px]">
                    {arc.key_events.map((e, i) => (
                      <span key={i} className="inline-block mr-1.5 mb-1 px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
                        • {e}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1">
        {label}
      </div>
      <div className="text-sm text-zinc-800 dark:text-zinc-100">{value}</div>
    </div>
  )
}

// ─── GLOSSARY ────────────────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<string, string> = {
  organization: 'Tổ chức', location: 'Địa danh', title: 'Chức vụ',
  object: 'Vật phẩm', concept: 'Khái niệm', nickname: 'Biệt danh',
  idiom: 'Thành ngữ', cliche: 'Cliché', other: 'Khác',
}

function GlossaryView({ bible, projectId, onUpdate }: {
  bible: Bible; projectId: number; onUpdate: () => void
}) {
  const terms = bible.glossary?.terms || []
  const [filter, setFilter] = useState('')

  const filtered = filter
    ? terms.filter(t =>
        t.zh.includes(filter) ||
        t.vi.toLowerCase().includes(filter.toLowerCase()) ||
        t.category.includes(filter))
    : terms

  // Group by category
  const byCategory = filtered.reduce<Record<string, GlossaryTerm[]>>((acc, t) => {
    const cat = t.category || 'other'
    acc[cat] = acc[cat] || []
    acc[cat].push(t)
    return acc
  }, {})

  return (
    <div className="space-y-3">
      <input
        type="text"
        value={filter}
        onChange={e => setFilter(e.target.value)}
        placeholder="Tìm thuật ngữ..."
        className="input w-full max-w-md"
      />

      {Object.keys(byCategory).length === 0 && (
        <div className="text-zinc-500 p-4 text-center">Không tìm thấy thuật ngữ.</div>
      )}

      {Object.entries(byCategory).map(([cat, items]) => (
        <div key={cat}>
          <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1.5 px-2">
            {CATEGORY_LABELS[cat] || cat} ({items.length})
          </div>
          <div className="bg-white dark:bg-zinc-950 rounded-lg border border-zinc-200 dark:border-zinc-800 divide-y divide-zinc-100 dark:divide-zinc-800">
            {items.map((t, i) => (
              <div key={i} className="px-4 py-2.5 flex items-baseline gap-3">
                <div className="font-mono text-[13px] text-zinc-700 dark:text-zinc-300 min-w-[100px]">{t.zh}</div>
                <div className="text-zinc-400">→</div>
                <div className="font-medium text-[13px] text-zinc-800 dark:text-zinc-100 flex-1">{t.vi}</div>
                {t.notes && (
                  <div className="text-[11px] text-zinc-500 italic max-w-md truncate" title={t.notes}>
                    {t.notes}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── RAW JSON ────────────────────────────────────────────────────────────────

function RawView({ bible, projectId, onUpdate }: {
  bible: Bible; projectId: number; onUpdate: () => void
}) {
  const [castText, setCastText] = useState(() => JSON.stringify(bible.cast, null, 2))
  const [worldText, setWorldText] = useState(() => JSON.stringify(bible.world, null, 2))
  const [glossText, setGlossText] = useState(() => JSON.stringify(bible.glossary, null, 2))
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  async function save() {
    setErr('')
    let cast, world, glossary
    try {
      cast = JSON.parse(castText)
      world = JSON.parse(worldText)
      glossary = JSON.parse(glossText)
    } catch (e: any) {
      setErr(`JSON không hợp lệ: ${e.message}`)
      return
    }
    setSaving(true)
    try {
      await translateApi.updateBible(projectId, { cast, world, glossary })
      onUpdate()
      alert('Đã lưu Bible')
    } catch (e: any) {
      setErr(`Lỗi: ${e?.response?.data?.detail || e.message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="text-[11px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 px-3 py-2 rounded">
        ⚠ Edit JSON trực tiếp. Cẩn thận giữ đúng format Pydantic schema, sai schema sẽ gây lỗi pipeline.
      </div>

      {err && (
        <div className="text-[12px] text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded">
          {err}
        </div>
      )}

      <details open>
        <summary className="cursor-pointer text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1">Cast</summary>
        <textarea
          value={castText}
          onChange={e => setCastText(e.target.value)}
          className="input w-full font-mono text-[11px]"
          rows={12}
        />
      </details>

      <details>
        <summary className="cursor-pointer text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1">World</summary>
        <textarea
          value={worldText}
          onChange={e => setWorldText(e.target.value)}
          className="input w-full font-mono text-[11px]"
          rows={12}
        />
      </details>

      <details>
        <summary className="cursor-pointer text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1">Glossary</summary>
        <textarea
          value={glossText}
          onChange={e => setGlossText(e.target.value)}
          className="input w-full font-mono text-[11px]"
          rows={12}
        />
      </details>

      <button onClick={save} disabled={saving} className="btn-primary">
        {saving ? 'Đang lưu...' : '💾 Lưu Bible'}
      </button>
    </div>
  )
}
