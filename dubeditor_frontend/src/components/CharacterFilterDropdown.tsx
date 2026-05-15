import React, { useState, useEffect, useRef, useMemo } from 'react'
import type { Character, Subtitle } from '../types'

interface Props {
  characters: Character[]
  subtitles: Subtitle[]
  selectedIds: number[]
  onChange: (ids: number[]) => void
}

/**
 * Dropdown multi-select để filter Editor theo Nhân vật.
 * Dùng position: fixed để tránh bị clip / che bởi parent overflow.
 */
export default function CharacterFilterDropdown({
  characters, subtitles, selectedIds, onChange,
}: Props) {
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null)

  const buttonRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Tính vị trí khi mở
  useEffect(() => {
    if (!open || !buttonRef.current) return
    const rect = buttonRef.current.getBoundingClientRect()
    setCoords({ top: rect.bottom + 4, left: rect.left })
  }, [open])

  // Click ngoài đóng + reposition khi resize/scroll
  useEffect(() => {
    if (!open) return
    const onClickOut = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        buttonRef.current && !buttonRef.current.contains(target) &&
        dropdownRef.current && !dropdownRef.current.contains(target)
      ) {
        setOpen(false)
      }
    }
    const onReposition = () => {
      if (!buttonRef.current) return
      const rect = buttonRef.current.getBoundingClientRect()
      setCoords({ top: rect.bottom + 4, left: rect.left })
    }
    document.addEventListener('mousedown', onClickOut)
    window.addEventListener('resize', onReposition)
    window.addEventListener('scroll', onReposition, true)
    return () => {
      document.removeEventListener('mousedown', onClickOut)
      window.removeEventListener('resize', onReposition)
      window.removeEventListener('scroll', onReposition, true)
    }
  }, [open])

  // Đếm số dòng theo character
  const counts = useMemo(() => {
    const m = new Map<number, number>()
    let unassigned = 0
    for (const s of subtitles) {
      if (s.character_id) {
        m.set(s.character_id, (m.get(s.character_id) || 0) + 1)
      } else {
        unassigned++
      }
    }
    return { byChar: m, unassigned }
  }, [subtitles])

  const allSelected = selectedIds.length === 0
  const someSelected = selectedIds.length > 0 && selectedIds.length < characters.length

  const toggleAll = () => {
    if (allSelected) return
    onChange([])
  }

  const toggleOne = (id: number) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter(x => x !== id))
    } else {
      onChange([...selectedIds, id])
    }
  }

  const label = allSelected
    ? `Tất cả (${characters.length})`
    : selectedIds.length === 1
      ? characters.find(c => c.id === selectedIds[0])?.name || '?'
      : `${selectedIds.length} nhân vật`

  return (
    <>
      <button
        ref={buttonRef}
        onClick={() => setOpen(o => !o)}
        title="Lọc theo nhân vật"
        className={`flex-shrink-0 px-2.5 py-1 text-[12px] rounded-lg border flex items-center gap-1.5 font-medium
          ${someSelected
            ? 'border-violet-300 dark:border-violet-700 bg-violet-50 dark:bg-violet-950/40 text-violet-700 dark:text-violet-400'
            : 'border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300'
          }
        `}
      >
        <span>👤 Lọc NV:</span>
        <span className="font-semibold truncate max-w-[160px]">{label}</span>
        <span className="text-[10px]">▼</span>
      </button>

      {open && coords && (
        <div
          ref={dropdownRef}
          style={{ position: 'fixed', top: coords.top, left: coords.left, zIndex: 1000 }}
          className="w-72 max-h-[460px] overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-2xl py-1"
        >
          {/* Header — Tất cả */}
          <div className="sticky top-0 bg-white dark:bg-zinc-900 border-b border-zinc-100 dark:border-zinc-800 px-3 py-1.5">
            <label className="flex items-center gap-2 text-[12px] cursor-pointer">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                className="w-4 h-4 cursor-pointer"
              />
              <span className="font-semibold">Tất cả ({characters.length} nhân vật)</span>
            </label>
          </div>

          {counts.unassigned > 0 && (
            <div className="px-3 py-1.5 text-[11px] text-zinc-500 dark:text-zinc-400 border-b border-zinc-100 dark:border-zinc-800">
              ⚠ {counts.unassigned} dòng chưa gán nhân vật
            </div>
          )}

          <div className="py-1">
            {characters.map(c => {
              const isSelected = selectedIds.includes(c.id)
              const cnt = counts.byChar.get(c.id) || 0
              return (
                <label
                  key={c.id}
                  className="flex items-center gap-2 px-3 py-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-[12px]"
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleOne(c.id)}
                    className="w-4 h-4 cursor-pointer"
                  />
                  <span
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ background: c.color }}
                  />
                  <span className="flex-1 font-medium truncate" style={{ color: c.color }}>
                    {c.name}
                  </span>
                  <span className="text-[11px] text-zinc-500 dark:text-zinc-400 flex-shrink-0">
                    {cnt} dòng
                  </span>
                </label>
              )
            })}
          </div>
        </div>
      )}
    </>
  )
}
