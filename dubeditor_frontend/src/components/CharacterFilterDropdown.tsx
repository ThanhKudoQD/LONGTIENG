import React, { useState, useEffect, useRef, useMemo } from 'react'
import type { Character, Subtitle } from '../types'

interface Props {
  characters: Character[]
  subtitles: Subtitle[]   // để đếm số dòng/NV
  selectedIds: number[]   // multi-select: rỗng = tất cả
  onChange: (ids: number[]) => void
}

/**
 * Dropdown multi-select để filter Editor theo Nhân vật.
 *
 * - "Tất cả" → bỏ chọn (selectedIds = [])
 * - Chọn 1 hoặc nhiều NV → chỉ hiện sub của các NV đó
 */
export default function CharacterFilterDropdown({
  characters, subtitles, selectedIds, onChange,
}: Props) {
  const [open, setOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Click ngoài đóng
  useEffect(() => {
    if (!open) return
    const onClickOut = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClickOut)
    return () => document.removeEventListener('mousedown', onClickOut)
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

  // Label hiển thị trên button
  const label = allSelected
    ? `Tất cả (${characters.length})`
    : selectedIds.length === 1
      ? characters.find(c => c.id === selectedIds[0])?.name || '?'
      : `${selectedIds.length} nhân vật`

  return (
    <div className="relative flex-shrink-0" ref={dropdownRef}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Lọc theo nhân vật"
        className={`px-2.5 py-1 text-[12px] rounded-lg border flex items-center gap-1.5 font-medium
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

      {open && (
        <div className="absolute top-full mt-1 left-0 z-50 w-72 max-h-[460px] overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-lg py-1">
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

          {/* Số dòng chưa gán */}
          {counts.unassigned > 0 && (
            <div className="px-3 py-1.5 text-[11px] text-zinc-500 dark:text-zinc-400 border-b border-zinc-100 dark:border-zinc-800">
              ⚠ {counts.unassigned} dòng chưa gán nhân vật
            </div>
          )}

          {/* List characters */}
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
    </div>
  )
}
