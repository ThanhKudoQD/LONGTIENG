/**
 * BibleViewTab v2 — hiển thị Bible dễ hiểu:
 *   - Mọi nơi hiển thị tên Việt + tên Trung
 *   - Badge phe: 🟢 Chính diện / 🔴 Phản diện / ⚪ Trung lập
 *   - Quan hệ group theo từng nhân vật (card riêng): ai xưng hô với ai
 *
 * Character format: [tên Việt, gender, importance, side, [aliases]]
 *   side: main | anta | neutral
 */
import React, { useState, useMemo } from 'react'
import type { BibleState } from '../types'

interface Props {
  state: BibleState
}

// Helper đọc field từ entry (hỗ trợ cả format 4 cũ và 5 mới)
function parseChar(data: any): {
  nameVi: string; gender: string; importance: string; side: string; aliases: string[]
} {
  if (!Array.isArray(data)) {
    return { nameVi: '', gender: 'U', importance: 'support', side: 'neutral', aliases: [] }
  }
  const nameVi = data[0] || ''
  const gender = data[1] || 'U'
  const importance = data[2] || 'support'
  // Format mới (5): side ở [3], aliases ở [4]. Cũ (4): aliases ở [3]
  let side = 'neutral'
  let aliases: string[] = []
  if (data.length >= 5 && Array.isArray(data[4])) {
    side = typeof data[3] === 'string' ? data[3] : 'neutral'
    aliases = data[4]
  } else if (data.length >= 4 && Array.isArray(data[3])) {
    aliases = data[3]
  }
  if (!['main', 'anta', 'neutral'].includes(side)) side = 'neutral'
  return { nameVi, gender, importance, side, aliases }
}

export default function BibleViewTab({ state }: Props) {
  const bible = state.master_bible_json
  const [activeSection, setActiveSection] = useState<
    'overview' | 'characters' | 'relationships' | 'glossary' | 'rules' | 'raw'
  >('overview')

  if (!bible || Object.keys(bible).length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        <div className="text-5xl mb-4">📖</div>
        <div className="text-[15px] font-medium mb-2">Bible chưa được build</div>
        <div className="text-[13px]">Vào tab "Bible" để chạy Auto hoặc paste response.</div>
      </div>
    )
  }

  const characters = bible.c || {}
  const speech = bible.speech || {}
  const relationships = bible.r || {}
  const dynamics = bible.dynamics || {}
  const glossary = bible.t || {}
  const rules = bible.rules || []
  const unknowns = bible.unknowns || []

  // Map name_zh → tên Việt (để hiển thị quan hệ)
  const nameMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const [zh, data] of Object.entries(characters)) {
      m[zh] = parseChar(data).nameVi
    }
    return m
  }, [characters])

  const charCount = Object.keys(characters).length
  const sides = useMemo(() => {
    let main = 0, anta = 0, neutral = 0
    for (const data of Object.values(characters)) {
      const s = parseChar(data).side
      if (s === 'main') main++
      else if (s === 'anta') anta++
      else neutral++
    }
    return { main, anta, neutral }
  }, [characters])

  const sections = [
    { key: 'overview',      label: '🎬 Tổng quan',  count: null },
    { key: 'characters',    label: '👥 Nhân vật',   count: charCount },
    { key: 'relationships', label: '🔗 Quan hệ',    count: Object.keys(relationships).length },
    { key: 'glossary',      label: '📚 Thuật ngữ',  count: Object.keys(glossary).length },
    { key: 'rules',         label: '📋 Rules',      count: rules.length },
    { key: 'raw',           label: '{ } JSON',      count: null },
  ] as const

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="surface-card p-5">
        <h2 className="text-[17px] font-semibold text-zinc-900 dark:text-zinc-100 mb-2">
          {bible.genre || 'Chưa có genre'}
        </h2>
        <div className="flex flex-wrap gap-4 text-[12px] text-zinc-600 dark:text-zinc-400 mb-3">
          {bible.setting && <div><span className="text-zinc-500">Bối cảnh:</span> {bible.setting}</div>}
          {bible.period && <div><span className="text-zinc-500">Thời kỳ:</span> {bible.period}</div>}
        </div>
        {bible.sum && (
          <p className="text-[13px] text-zinc-700 dark:text-zinc-300 leading-relaxed">{bible.sum}</p>
        )}
        <div className="flex flex-wrap gap-2 mt-3">
          <SideCount label="Chính diện" count={sides.main} side="main" />
          <SideCount label="Phản diện" count={sides.anta} side="anta" />
          <SideCount label="Trung lập" count={sides.neutral} side="neutral" />
        </div>
      </div>

      {/* Section tabs */}
      <div className="flex flex-wrap items-center gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {sections.map(s => (
          <button
            key={s.key}
            onClick={() => setActiveSection(s.key as any)}
            className={`px-3 py-2 text-[12px] font-medium border-b-2 -mb-px transition-colors ${
              activeSection === s.key
                ? 'border-blue-600 text-zinc-900 dark:text-zinc-100'
                : 'border-transparent text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300'
            }`}
          >
            {s.label}
            {s.count !== null && (
              <span className="ml-1.5 inline-flex items-center justify-center min-w-[1.4em] px-1 rounded text-[10px] font-mono bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400">
                {s.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {activeSection === 'overview' && (
        <OverviewSection bible={bible} unknowns={unknowns} sides={sides} />
      )}
      {activeSection === 'characters' && (
        <CharactersSection characters={characters} speech={speech} />
      )}
      {activeSection === 'relationships' && (
        <RelationshipsByCharacter
          characters={characters} relationships={relationships}
          dynamics={dynamics} nameMap={nameMap} speech={speech}
        />
      )}
      {activeSection === 'glossary' && <GlossarySection glossary={glossary} />}
      {activeSection === 'rules' && <RulesSection rules={rules} />}
      {activeSection === 'raw' && <RawSection bible={bible} />}
    </div>
  )
}


// ─── Overview ────────────────────────────────────────────────────────────────

function OverviewSection({ bible, unknowns, sides }: { bible: any; unknowns: any[]; sides: any }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Nhân vật" value={Object.keys(bible.c || {}).length} />
        <StatCard label="Quan hệ" value={Object.keys(bible.r || {}).length} />
        <StatCard label="Thuật ngữ" value={Object.keys(bible.t || {}).length} />
        <StatCard label="Rules" value={(bible.rules || []).length} />
      </div>
      {unknowns.length > 0 && (
        <div className="surface-card p-4 border-l-4 border-amber-400">
          <div className="text-[11px] uppercase tracking-wider text-amber-700 dark:text-amber-300 mb-2 font-medium">
            Chưa rõ · {unknowns.length}
          </div>
          <ul className="text-[12.5px] text-zinc-700 dark:text-zinc-300 space-y-1">
            {unknowns.map((u: any, i: number) => (
              <li key={i}>{typeof u === 'string' ? u : JSON.stringify(u)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}


// ─── Characters ──────────────────────────────────────────────────────────────

function CharactersSection({ characters, speech }: { characters: any; speech: any }) {
  const entries = Object.entries(characters) as [string, any][]
  // Sort: main → neutral → anta? Thực ra: core trước, trong đó main trước anta
  const withMeta = entries.map(([zh, data]) => ({ zh, ...parseChar(data) }))

  const mains = withMeta.filter(c => c.side === 'main')
  const antas = withMeta.filter(c => c.side === 'anta')
  const neutrals = withMeta.filter(c => c.side === 'neutral')

  return (
    <div className="space-y-4">
      {mains.length > 0 && <CharGroup title="🟢 Chính diện" chars={mains} speech={speech} accent="emerald" />}
      {antas.length > 0 && <CharGroup title="🔴 Phản diện" chars={antas} speech={speech} accent="red" />}
      {neutrals.length > 0 && <CharGroup title="⚪ Trung lập / phụ" chars={neutrals} speech={speech} accent="zinc" />}
    </div>
  )
}

function CharGroup({ title, chars, speech, accent }: {
  title: string; chars: any[]; speech: any; accent: string
}) {
  const headerCls: Record<string, string> = {
    emerald: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-900',
    red: 'bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 border-red-200 dark:border-red-900',
    zinc: 'bg-zinc-50 dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 border-zinc-200 dark:border-zinc-800',
  }
  return (
    <div className="surface-card overflow-hidden">
      <div className={`px-4 py-2 text-[11px] uppercase tracking-wider font-medium border-b ${headerCls[accent]}`}>
        {title} · {chars.length}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12.5px]">
          <thead className="bg-zinc-50 dark:bg-zinc-900 text-zinc-500 text-[11px] uppercase">
            <tr>
              <th className="text-left px-3 py-2 font-medium">Nhân vật</th>
              <th className="text-left px-3 py-2 font-medium w-12">GT</th>
              <th className="text-left px-3 py-2 font-medium">Tên gọi khác</th>
              <th className="text-left px-3 py-2 font-medium">Phong cách nói</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {chars.map(c => (
              <tr key={c.zh} className="hover:bg-zinc-50 dark:hover:bg-zinc-900/40">
                <td className="px-3 py-2">
                  <div className="font-medium text-zinc-900 dark:text-zinc-100">{c.nameVi}</div>
                  <div className="text-[11px] text-zinc-400 font-mono">{c.zh}</div>
                </td>
                <td className="px-3 py-2"><GenderBadge gender={c.gender} /></td>
                <td className="px-3 py-2 text-[11px] text-zinc-500">
                  {c.aliases.length > 0
                    ? c.aliases.map((a: string) => (
                        <span key={a} className="inline-block mr-1.5">{a}</span>
                      ))
                    : '—'}
                </td>
                <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400 italic text-[12px]">
                  {speech[c.zh] || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


// ─── Relationships grouped by character ──────────────────────────────────────

function RelationshipsByCharacter({
  characters, relationships, dynamics, nameMap, speech,
}: {
  characters: any; relationships: any; dynamics: any;
  nameMap: Record<string, string>; speech: any
}) {
  // Build per-character relationship list
  // relationships key = "A>B" : "xưng hô" (A gọi B thế nào)
  // dynamics key = "A-B" : "mô tả động lực"
  const byChar = useMemo(() => {
    const result: Record<string, { addressing: { to: string; how: string }[]; dynamics: { with: string; desc: string }[] }> = {}

    const ensure = (zh: string) => {
      if (!result[zh]) result[zh] = { addressing: [], dynamics: [] }
      return result[zh]
    }

    for (const [key, how] of Object.entries(relationships)) {
      const [a, b] = key.split('>')
      if (a && b) {
        ensure(a.trim()).addressing.push({ to: b.trim(), how: how as string })
      }
    }
    for (const [key, desc] of Object.entries(dynamics)) {
      const [a, b] = key.split('-')
      if (a && b) {
        ensure(a.trim()).dynamics.push({ with: b.trim(), desc: desc as string })
        ensure(b.trim()).dynamics.push({ with: a.trim(), desc: desc as string })
      }
    }
    return result
  }, [relationships, dynamics])

  const displayName = (zh: string) => nameMap[zh] || zh

  // Sort: nhân vật có quan hệ trước
  const charsWithRel = Object.keys(byChar).filter(
    zh => byChar[zh].addressing.length > 0 || byChar[zh].dynamics.length > 0
  )

  if (charsWithRel.length === 0) {
    return (
      <div className="surface-card p-6 text-center text-zinc-500 text-[13px]">
        Bible chưa trích được quan hệ nào.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      {charsWithRel.map(zh => {
        const rel = byChar[zh]
        const meta = parseChar(characters[zh])
        return (
          <div key={zh} className="surface-card overflow-hidden">
            {/* Card header: tên nhân vật */}
            <div className="px-4 py-2.5 bg-zinc-50 dark:bg-zinc-900/60 border-b border-zinc-200/70 dark:border-zinc-800 flex items-center gap-2">
              <SideDot side={meta.side} />
              <span className="font-semibold text-zinc-900 dark:text-zinc-100 text-[13px]">
                {displayName(zh)}
              </span>
              <span className="text-[11px] text-zinc-400 font-mono">{zh}</span>
            </div>
            <div className="p-3 space-y-3">
              {/* Xưng hô */}
              {rel.addressing.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zinc-400 mb-1.5 font-medium">
                    Cách xưng hô
                  </div>
                  <div className="space-y-1">
                    {rel.addressing.map((a, i) => (
                      <div key={i} className="flex items-center gap-2 text-[12.5px]">
                        <span className="text-zinc-400">gọi</span>
                        <span className="font-medium text-zinc-800 dark:text-zinc-200">
                          {displayName(a.to)}
                        </span>
                        <span className="text-zinc-300">·</span>
                        <span className="text-blue-700 dark:text-blue-300 font-mono">{a.how}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {/* Dynamics */}
              {rel.dynamics.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zinc-400 mb-1.5 font-medium">
                    Mối quan hệ
                  </div>
                  <div className="space-y-1">
                    {rel.dynamics.map((d, i) => (
                      <div key={i} className="text-[12.5px]">
                        <span className="text-zinc-400">với </span>
                        <span className="font-medium text-zinc-800 dark:text-zinc-200">
                          {displayName(d.with)}
                        </span>
                        <span className="text-zinc-500">: {d.desc}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}


// ─── Glossary ────────────────────────────────────────────────────────────────

function GlossarySection({ glossary }: { glossary: any }) {
  const entries = Object.entries(glossary) as [string, string][]
  return (
    <div className="surface-card overflow-hidden">
      {entries.length === 0 ? (
        <div className="px-4 py-6 text-center text-zinc-500 text-[12.5px]">Chưa có thuật ngữ.</div>
      ) : (
        <table className="w-full text-[12.5px]">
          <thead className="bg-zinc-50 dark:bg-zinc-900 text-zinc-500 text-[11px] uppercase">
            <tr>
              <th className="text-left px-3 py-2 font-medium w-1/3">Tiếng Trung</th>
              <th className="text-left px-3 py-2 font-medium">Tiếng Việt</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {entries.map(([zh, vi]) => (
              <tr key={zh} className="hover:bg-zinc-50 dark:hover:bg-zinc-900/40">
                <td className="px-3 py-2 font-medium text-zinc-900 dark:text-zinc-100">{zh}</td>
                <td className="px-3 py-2 text-zinc-700 dark:text-zinc-300">{vi}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function RulesSection({ rules }: { rules: string[] }) {
  return (
    <div className="surface-card overflow-hidden">
      {rules.length === 0 ? (
        <div className="px-4 py-6 text-center text-zinc-500 text-[12.5px]">Chưa có rules.</div>
      ) : (
        <ol className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {rules.map((rule, i) => (
            <li key={i} className="px-4 py-3 flex gap-3 hover:bg-zinc-50 dark:hover:bg-zinc-900/40">
              <span className="font-mono text-[11px] text-zinc-400 min-w-[1.5em] mt-0.5">{i + 1}.</span>
              <span className="text-[13px] text-zinc-700 dark:text-zinc-300 flex-1">{rule}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function RawSection({ bible }: { bible: any }) {
  const json = JSON.stringify(bible, null, 2)
  return (
    <div className="surface-card overflow-hidden">
      <div className="px-4 py-2 flex items-center justify-between bg-zinc-50 dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800">
        <span className="text-[11px] uppercase tracking-wider text-zinc-500 font-medium">JSON gốc</span>
        <button onClick={() => navigator.clipboard.writeText(json)} className="btn text-[11px]">📋 Copy</button>
      </div>
      <pre className="px-4 py-3 text-[11.5px] font-mono text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap break-words max-h-[600px] overflow-y-auto">
        {json}
      </pre>
    </div>
  )
}


// ─── Sub-components ──────────────────────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="surface-card px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-1 font-medium">{label}</div>
      <div className="text-[20px] font-semibold text-zinc-900 dark:text-zinc-100">{value}</div>
    </div>
  )
}

function GenderBadge({ gender }: { gender: string }) {
  const colors: Record<string, string> = {
    F: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-300',
    M: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300',
    U: 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400',
  }
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${colors[gender] || colors.U}`}>
      {gender}
    </span>
  )
}

function SideDot({ side }: { side: string }) {
  const cls = side === 'main' ? 'bg-emerald-500' : side === 'anta' ? 'bg-red-500' : 'bg-zinc-400'
  return <span className={`w-2.5 h-2.5 rounded-full ${cls} shrink-0`} />
}

function SideCount({ label, count, side }: { label: string; count: number; side: string }) {
  const cls = side === 'main'
    ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800'
    : side === 'anta'
      ? 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800'
      : 'bg-zinc-50 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border-zinc-200 dark:border-zinc-700'
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium border ${cls}`}>
      <SideDot side={side} />
      {label}: {count}
    </span>
  )
}
