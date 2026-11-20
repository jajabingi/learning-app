import { useMemo, useRef, useState, useEffect } from 'react'
import { X } from 'lucide-react'
import { useTopicList } from '@/hooks/queries'

export function TopicPicker({ value, onChange, subjectId, single, placeholder = 'Search topics…' }: { value: string[]; onChange(v: string[]): void; subjectId?: string | null; single?: boolean; placeholder?: string }) {
  const { data = [] } = useTopicList()
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const byId = useMemo(() => new Map(data.map((t) => [t.id, t])), [data])
  const options = useMemo(() => {
    const ql = q.toLowerCase()
    return data
      .filter((t) => !value.includes(t.id) && (!ql || t.path.toLowerCase().includes(ql) || t.subject_name.toLowerCase().includes(ql)))
      .sort((a, b) => Number(b.subject_id === subjectId) - Number(a.subject_id === subjectId) || a.path.localeCompare(b.path))
      .slice(0, 40)
  }, [data, q, value, subjectId])

  return (
    <div className="relative" ref={ref}>
      <div className="flex flex-wrap items-center gap-1 rounded border border-line bg-surface px-1.5 py-1 focus-within:border-accent" onClick={() => setOpen(true)}>
        {value.map((id) => (
          <span key={id} className="inline-flex max-w-full items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5 text-xs text-accent">
            <span className="truncate">{byId.get(id)?.name ?? 'Topic'}</span>
            <button type="button" aria-label="Remove topic" onClick={(e) => { e.stopPropagation(); onChange(value.filter((x) => x !== id)) }}><X size={11} /></button>
          </span>
        ))}
        {!(single && value.length) && (
          <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} placeholder={value.length ? '' : placeholder} aria-label="Search topics" className="min-w-24 flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-faint" />
        )}
      </div>
      {open && (
        <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-line bg-surface py-1 shadow-lg" role="listbox">
          {options.length === 0 && <div className="px-3 py-2 text-sm text-muted">{data.length ? 'No matching topics' : 'No topics yet — create one in the Library'}</div>}
          {options.map((t) => (
            <button key={t.id} type="button" role="option" aria-selected={false} className="block w-full px-3 py-1.5 text-left text-sm hover:bg-raised" onClick={() => { onChange(single ? [t.id] : [...value, t.id]); setQ(''); setOpen(!single) }}>
              <span>{t.path}</span> <span className="text-xs text-faint">· {t.subject_name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
