import React, { useEffect, useState, useMemo, useRef } from 'react'
import api from '../api'
import { VoxActor, VoxRole, CHAR_COLORS } from '../types'

interface Props {
  // Giữ nguyên signature cũ để không làm hỏng code hiện tại của bạn
  onSelect: (actor: VoxActor, role: VoxRole, alias: string, color: string) => void
  onClose: () => void
}

const GENRES: Record<string, string> = {
  'all': 'Tất cả', 'co-trang': 'Cổ trang', 'hien-dai': 'Hiện đại',
  'hoat-hinh': 'Hoạt hình', 'hanh-dong': 'Hành động'
}
const TYPES: Record<string, string> = {
  'all': 'Tất cả', 'chinh': 'Vai chính', 'phu': 'Vai phụ', 'phan-dien': 'Phản diện'
}
const GENDERS: Record<string, string> = { 'all': 'Tất cả', 'nam': '♂ Nam', 'nu': '♀ Nữ' }
const TYPE_COLORS: Record<string, string> = {
  'chinh': '#7C3AED', 'phu': '#0891B2', 'phan-dien': '#DC2626'
}

function AudioPlayer({ src }: { src: string }) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!audioRef.current) {
      audioRef.current = new Audio(`${src}`)
      audioRef.current.onended = () => setPlaying(false)
    }
    if (playing) { 
      audioRef.current.pause(); 
      audioRef.current.currentTime = 0; 
      setPlaying(false) 
    } else { 
      audioRef.current.play().catch(() => {}); 
      setPlaying(true) 
    }
  }
  return (
    <button onClick={toggle} className="flex items-center gap-1.5 text-[11px] font-medium transition-colors"
      style={{ color: playing ? '#10B981' : '#9CA3AF' }}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        {playing ? (<><rect x="2" y="2" width="3.5" height="10" rx="1" fill="currentColor"/><rect x="8.5" y="2" width="3.5" height="10" rx="1" fill="currentColor"/></>) : (<path d="M3 2L11 7L3 12V2Z" fill="currentColor"/>)}
      </svg>
      {playing ? 'Đang phát...' : 'Nghe thử'}
    </button>
  )
}

interface AliasFormProps {
  item: { actor: VoxActor; role: VoxRole }
  index: number
  total: number
  onConfirm: (alias: string, color: string) => void
  onSkip: () => void
  onCancel: () => void
}

function AliasForm({ item, index, total, onConfirm, onSkip, onCancel }: AliasFormProps) {
  const [alias, setAlias] = useState(item.role.character_name)
  const [color, setColor] = useState(CHAR_COLORS[index % CHAR_COLORS.length])

  return (
    <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10 }}>
      <div style={{ background: '#1a1a2e', borderRadius: 20, padding: 28, width: 460, border: '1px solid rgba(255,255,255,0.1)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ fontSize: 17, fontWeight: 700, color: '#fff' }}>Thiết lập nhân vật</h3>
          <span style={{ fontSize: 12, color: '#6B7280', background: 'rgba(255,255,255,0.06)', padding: '3px 10px', borderRadius: 20 }}>
            {index + 1} / {total}
          </span>
        </div>

        <div style={{ height: 3, background: 'rgba(255,255,255,0.08)', borderRadius: 4, marginBottom: 16 }}>
          <div style={{ height: '100%', width: `${((index + 1) / total) * 100}%`, background: '#7C3AED', borderRadius: 4, transition: 'width 0.3s' }} />
        </div>

        <p style={{ fontSize: 13, color: '#9CA3AF', marginBottom: 20 }}>
          Diễn viên: <span style={{ color: '#C4B5FD', fontWeight: 600 }}>{item.actor.name}</span>
          {' · '}Mẫu: <span style={{ color: '#C4B5FD', fontWeight: 600 }}>{item.role.character_name}</span>
        </p>

        <label style={{ fontSize: 12, color: '#9CA3AF', display: 'block', marginBottom: 6, fontWeight: 500 }}>Tên nhân vật trong phim *</label>
        <input value={alias} onChange={e => setAlias(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && alias.trim() && onConfirm(alias.trim(), color)}
          placeholder="VD: Khương Tiểu Ngư..." autoFocus
          style={{
            width: '100%', padding: '10px 14px', borderRadius: 10, fontSize: 14,
            background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.15)',
            color: '#fff', outline: 'none', marginBottom: 20, boxSizing: 'border-box'
          }}
        />

        <label style={{ fontSize: 12, color: '#9CA3AF', display: 'block', marginBottom: 10, fontWeight: 500 }}>Màu sắc đại diện</label>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24 }}>
          {CHAR_COLORS.map(c => (
            <button key={c} onClick={() => setColor(c)}
              style={{
                width: 26, height: 26, borderRadius: '50%', background: c, border: 'none',
                cursor: 'pointer', outline: color === c ? `3px solid ${c}` : 'none', outlineOffset: 2,
                transform: color === c ? 'scale(1.2)' : 'scale(1)', transition: 'transform 0.15s',
              }} />
          ))}
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={() => onConfirm(alias.trim(), color)} disabled={!alias.trim()}
            style={{
              flex: 2, padding: '12px', borderRadius: 12,
              background: alias.trim() ? '#7C3AED' : '#4B5563',
              color: '#fff', fontSize: 14, fontWeight: 600, border: 'none',
              cursor: alias.trim() ? 'pointer' : 'not-allowed'
            }}>
            {index + 1 < total ? 'Tiếp theo →' : 'Xác nhận hoàn thành ✓'}
          </button>
          <button onClick={onSkip}
            style={{
              flex: 1, padding: '12px', borderRadius: 12,
              background: 'rgba(255,255,255,0.05)', color: '#9CA3AF',
              fontSize: 13, fontWeight: 500, border: '1px solid rgba(255,255,255,0.1)', cursor: 'pointer'
            }}>
            Bỏ qua
          </button>
          <button onClick={onCancel}
            style={{
              flex: 1, padding: '12px', borderRadius: 12,
              background: 'rgba(255,255,255,0.05)', color: '#9CA3AF',
              fontSize: 13, fontWeight: 500, border: '1px solid rgba(255,255,255,0.1)', cursor: 'pointer'
            }}>
            Huỷ
          </button>
        </div>
      </div>
    </div>
  )
}

export default function VoicePicker({ onSelect, onClose }: Props) {
  const [actors, setActors] = useState<VoxActor[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterGender, setFilterGender] = useState('all')
  const [filterGenre, setFilterGenre] = useState('all')
  const [filterType, setFilterType] = useState('all')
  const [sortBy, setSortBy] = useState('newest')

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [aliasList, setAliasList] = useState<{ actor: VoxActor; role: VoxRole }[]>([])
  const [aliasIdx, setAliasIdx] = useState(0)
  
  // Lưu kết quả của các bước nhập liệu
  const [tempResults, setTempResults] = useState<{actor: VoxActor, role: VoxRole, alias: string, color: string}[]>([])

  useEffect(() => {
    api.get('/tts/voices').then(r => {
      setActors(r.data.actors || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  const cards = useMemo(() => {
    const result: { actor: VoxActor; role: VoxRole }[] = []
    actors.forEach(actor => {
      if (filterGender !== 'all' && actor.gender !== filterGender) return
      actor.roles.forEach(role => {
        if (filterGenre !== 'all' && role.genre !== filterGenre) return
        if (filterType  !== 'all' && role.type  !== filterType)  return
        if (search) {
          const q = search.toLowerCase()
          if (!actor.name.toLowerCase().includes(q) &&
              !role.character_name.toLowerCase().includes(q) &&
              !role.show_name.toLowerCase().includes(q)) return
        }
        result.push({ actor, role })
      })
    })
    if (sortBy === 'name') result.sort((a,b) => a.actor.name.localeCompare(b.actor.name, 'vi'))
    else if (sortBy === 'roles') result.sort((a,b) => b.actor.roles.length - a.actor.roles.length)
    else if (sortBy === 'newest') result.sort((a,b) => a.actor.id > b.actor.id ? 1 : -1)
    else if (sortBy === 'oldest') result.sort((a,b) => a.actor.id < b.actor.id ? 1 : -1)
    return result
  }, [actors, search, filterGender, filterGenre, filterType, sortBy])

  const toggleSelect = (key: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  const startConfirm = () => {
    const items = cards.filter(c => selected.has(`${c.actor.id}-${c.role.id}`))
    if (!items.length) return
    setAliasList(items)
    setAliasIdx(0)
    setTempResults([])
  }

  // Xử lý khi nhấn Tiếp theo / Hoàn thành
  const handleAliasConfirm = (alias: string, color: string) => {
    const currentItem = aliasList[aliasIdx]
    const updatedResults = [...tempResults, { ...currentItem, alias, color }]

    if (aliasIdx + 1 < aliasList.length) {
      setTempResults(updatedResults)
      setAliasIdx(prev => prev + 1)
    } else {
      // Đã xong nhân vật cuối cùng: Gửi tất cả kết quả về cha
      updatedResults.forEach(res => {
        onSelect(res.actor, res.role, res.alias, res.color)
      })
      finishFlow()
    }
  }

  // Xử lý khi nhấn Bỏ qua
  const handleAliasSkip = () => {
    if (aliasIdx + 1 < aliasList.length) {
      setAliasIdx(prev => prev + 1)
    } else {
      // Nếu bỏ qua ở người cuối, gửi những người đã confirm trước đó (nếu có)
      tempResults.forEach(res => {
        onSelect(res.actor, res.role, res.alias, res.color)
      })
      finishFlow()
    }
  }

  const finishFlow = () => {
    setAliasList([])
    setAliasIdx(0)
    setSelected(new Set())
    setTempResults([])
    onClose()
  }

  const handleAliasCancel = () => {
    setAliasList([])
    setAliasIdx(0)
    setTempResults([])
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.85)' }}>
      <div className="rounded-2xl w-full max-w-6xl h-[92vh] flex flex-col overflow-hidden shadow-2xl relative"
        style={{ background: '#0D0D1A', color: '#fff' }}>

        {/* Header */}
        <div className="flex items-center justify-between px-8 py-5 flex-shrink-0"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 700 }}>Chọn nhân vật lồng tiếng</h2>
            <p style={{ fontSize: 13, color: '#9CA3AF', marginTop: 3 }}>
              Có <b style={{ color: '#fff' }}>{cards.length}</b> vai phù hợp
              {selected.size > 0 && <span style={{ color: '#C4B5FD', marginLeft: 8 }}>· Đã chọn: <b>{selected.size}</b></span>}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {selected.size > 0 && (
              <>
                <button onClick={() => setSelected(new Set())}
                  style={{ padding: '8px 16px', borderRadius: 10, background: 'rgba(255,255,255,0.07)', color: '#9CA3AF', fontSize: 13, fontWeight: 600, border: '1px solid rgba(255,255,255,0.1)', cursor: 'pointer' }}>
                  Bỏ chọn
                </button>
                <button onClick={startConfirm}
                  style={{ padding: '8px 20px', borderRadius: 10, background: '#7C3AED', color: '#fff', fontSize: 13, fontWeight: 700, border: 'none', cursor: 'pointer' }}>
                  Tiếp tục ({selected.size}) →
                </button>
              </>
            )}
            <button onClick={onClose}
              style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(255,255,255,0.08)', color: '#9CA3AF', fontSize: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', border: 'none', cursor: 'pointer' }}>
              ×
            </button>
          </div>
        </div>

        {/* Filters ... (Giữ nguyên phần filter của bạn) */}
        <div className="px-8 py-4 flex-shrink-0 space-y-3" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <input placeholder="🔍 Tìm tên diễn viên, nhân vật, phim..." value={search} onChange={e => setSearch(e.target.value)} style={{ width: '100%', padding: '10px 16px', borderRadius: 12, fontSize: 14, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: '#fff', outline: 'none' }} />
            <div className="flex gap-6 flex-wrap items-center">
                {[
                { label: 'Giới tính', val: filterGender, set: setFilterGender, opts: GENDERS },
                { label: 'Loại vai',  val: filterType,   set: setFilterType,   opts: TYPES },
                { label: 'Thể loại', val: filterGenre,  set: setFilterGenre,  opts: GENRES },
                ].map(({ label, val, set, opts }) => (
                <div key={label} className="flex items-center gap-2">
                    <span style={{ fontSize: 12, color: '#6B7280', fontWeight: 500 }}>{label}:</span>
                    {Object.entries(opts).map(([k, v]) => (
                    <button key={k} onClick={() => set(k)} style={{ padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 500, cursor: 'pointer', transition: 'all 0.15s', background: val === k ? '#7C3AED' : 'rgba(255,255,255,0.07)', color: val === k ? '#fff' : '#9CA3AF', border: val === k ? '1px solid #7C3AED' : '1px solid rgba(255,255,255,0.1)' }}>{v}</button>
                    ))}
                </div>
                ))}
            </div>
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {loading ? (
            <div className="flex items-center justify-center h-48 text-gray-500 text-sm">Đang tải dữ liệu...</div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
              {cards.map(({ actor, role }) => {
                const key = `${actor.id}-${role.id}`
                const isSelected = selected.has(key)
                return (
                  <div key={key}
                    onClick={() => toggleSelect(key)}
                    style={{
                      background: isSelected ? 'rgba(124,58,237,0.12)' : 'rgba(255,255,255,0.03)',
                      borderRadius: 16,
                      border: isSelected ? '2px solid #7C3AED' : '1px solid rgba(255,255,255,0.08)',
                      cursor: 'pointer', overflow: 'hidden', transition: 'all 0.15s',
                      position: 'relative',
                    }}>
                    <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 2, width: 22, height: 22, borderRadius: '50%', background: isSelected ? '#7C3AED' : 'rgba(0,0,0,0.4)', border: `2px solid ${isSelected ? '#7C3AED' : 'rgba(255,255,255,0.3)'}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {isSelected && <svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 6L5 9L10 3" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                    </div>
                    <div style={{ position: 'relative', height: 180, background: '#1a1a2e' }}>
                      {actor.avatar && <img src={`${actor.avatar}`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
                    </div>
                    <div style={{ padding: '12px' }}>
                      <p style={{ fontSize: 14, fontWeight: 700 }}>{role.character_name}</p>
                      <p style={{ fontSize: 12, color: '#9CA3AF', marginBottom: 8 }}>{actor.name}</p>
                      {role.audio && <AudioPlayer src={role.audio} />}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Alias form overlay */}
        {aliasList.length > 0 && (
          <AliasForm
            key={aliasIdx} // Bắt buộc phải có key này để React reset state của AliasForm mỗi khi chuyển người
            item={aliasList[aliasIdx]}
            index={aliasIdx}
            total={aliasList.length}
            onConfirm={handleAliasConfirm}
            onSkip={handleAliasSkip}
            onCancel={handleAliasCancel}
          />
        )}
      </div>
    </div>
  )
}