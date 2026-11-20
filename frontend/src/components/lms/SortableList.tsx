import { useState, type ReactNode } from 'react'
import { tt } from '@/i18n'
import { ChevronDown, ChevronUp, GripVertical } from 'lucide-react'
import { cx } from '@/components/ui'

/** Reorderable list: drag and drop (native HTML5) plus accessible up/down buttons. Calls onReorder with the new id order. */
export function SortableList<T extends { id: string }>({ items, onReorder, render, className }: { items: T[]; onReorder(ids: string[]): void; render(item: T, index: number): ReactNode; className?: string }) {
  const [drag, setDrag] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const move = (from: number, to: number) => {
    if (to < 0 || to >= items.length || from === to) return
    const ids = items.map((i) => i.id)
    ids.splice(to, 0, ids.splice(from, 1)[0])
    onReorder(ids)
  }
  return (
    <ul className={className}>
      {items.map((it, i) => (
        <li key={it.id} draggable onDragStart={(e) => { setDrag(it.id); e.dataTransfer.effectAllowed = 'move' }} onDragEnd={() => { setDrag(null); setOver(null) }}
          onDragOver={(e) => { if (drag && drag !== it.id) { e.preventDefault(); setOver(it.id) } }}
          onDrop={(e) => { e.preventDefault(); if (drag) move(items.findIndex((x) => x.id === drag), i); setDrag(null); setOver(null) }}
          className={cx('flex items-start gap-1', drag === it.id && 'opacity-40', over === it.id && 'rounded ring-2 ring-accent/50')}>
          <div className="flex shrink-0 flex-col items-center pt-1.5 text-faint">
            <button type="button" className="hover:text-fg disabled:opacity-30" aria-label={tt("Move up")} disabled={i === 0} onClick={() => move(i, i - 1)}><ChevronUp size={14} /></button>
            <GripVertical size={14} className="cursor-grab" aria-hidden />
            <button type="button" className="hover:text-fg disabled:opacity-30" aria-label={tt("Move down")} disabled={i === items.length - 1} onClick={() => move(i, i + 1)}><ChevronDown size={14} /></button>
          </div>
          <div className="min-w-0 flex-1">{render(it, i)}</div>
        </li>
      ))}
    </ul>
  )
}
