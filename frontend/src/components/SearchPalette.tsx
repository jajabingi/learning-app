import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, FileText, FolderTree, GraduationCap, HelpCircle, Layers, MessageSquare, Search, Tag as TagIcon } from 'lucide-react'
import { get } from '@/api/client'
import type { SearchResult } from '@/api/types'
import { Modal, Spinner, cx } from './ui'
import { tt } from '@/i18n'

const META: Record<string, { label: string; Icon: typeof Search; to(r: SearchResult): string }> = {
  subject: { label: tt("Subject"), Icon: BookOpen, to: (r) => `/library/subject/${r.id}` },
  course: { label: tt("Course"), Icon: GraduationCap, to: (r) => `/library/course/${r.id}` },
  topic: { label: tt("Topic"), Icon: FolderTree, to: (r) => `/library/topic/${r.id}` },
  question: { label: tt("Question"), Icon: HelpCircle, to: (r) => `/questions/${r.id}` },
  answer: { label: tt("Answer"), Icon: MessageSquare, to: (r) => `/questions/${r.id}` },
  note: { label: tt("Note"), Icon: FileText, to: (r) => `/notes/${r.id}` },
  tag: { label: tt("Tag"), Icon: TagIcon, to: (r) => `/questions?tag=${encodeURIComponent(r.title)}` },
}
const TYPES = Object.keys(META)

export function SearchPalette({ open, onClose }: { open: boolean; onClose(): void }) {
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [types, setTypes] = useState<string[]>([])
  const [idx, setIdx] = useState(0)
  const nav = useNavigate()
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 200); return () => clearTimeout(t) }, [q])
  useEffect(() => { if (open) { setQ(''); setDq(''); setIdx(0); setTimeout(() => input.current?.focus(), 30) } }, [open])
  const res = useQuery({ queryKey: ['search', dq, types], queryFn: () => get<{ results: SearchResult[] }>('/search', { q: dq, types, limit: 8 }), enabled: open && dq.length > 0 })
  const results = res.data?.results ?? []
  useEffect(() => setIdx(0), [dq, types])

  const go = (r: SearchResult) => { onClose(); nav(META[r.type].to(r)) }

  return (
    <Modal open={open} onClose={onClose} title={tt("Search everything")}>
      <div className="-mx-1">
        <div className="flex items-center gap-2 rounded border border-line px-2.5 focus-within:border-accent">
          <Search size={15} className="text-faint" />
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} aria-label={tt("Search")} placeholder={tt("Subjects, topics, questions, answers, notes, tags…")} className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-faint"
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(i + 1, results.length - 1)) }
              if (e.key === 'ArrowUp') { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)) }
              if (e.key === 'Enter' && results[idx]) go(results[idx])
            }} />
          {res.isFetching && <Spinner />}
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {TYPES.map((t) => {
            const on = types.includes(t)
            return <button key={t} aria-pressed={on} onClick={() => setTypes(on ? types.filter((x) => x !== t) : [...types, t])} className={cx('rounded border px-1.5 py-0.5 text-xs', on ? 'border-accent bg-accent/10 text-accent' : 'border-line text-muted hover:bg-raised')}>{META[t].label}</button>
          })}
        </div>
        <ul className="mt-3 max-h-[50vh] overflow-y-auto" role="listbox">
          {dq && !res.isFetching && results.length === 0 && <li className="px-2 py-6 text-center text-sm text-muted">{tt("No results for “")}{dq}”</li>}
          {!dq && <li className="px-2 py-6 text-center text-sm text-muted">{tt("Type to search your whole knowledge base")}</li>}
          {results.map((r, i) => {
            const m = META[r.type]
            return (
              <li key={`${r.type}-${r.id}`} role="option" aria-selected={i === idx}>
                <button onClick={() => go(r)} onMouseEnter={() => setIdx(i)} className={cx('flex w-full items-start gap-2.5 rounded px-2 py-2 text-start', i === idx && 'bg-raised')}>
                  <m.Icon size={15} className="mt-0.5 shrink-0 text-faint" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{r.title || tt("Untitled")}</span>
                    {r.snippet && <span className="block truncate text-xs text-muted">{r.snippet}</span>}
                  </span>
                  <span className="shrink-0 text-xs text-faint">{m.label}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </Modal>
  )
}
export { Layers }
