import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ChevronLeft, ChevronRight, Search, SlidersHorizontal } from 'lucide-react'
import { del, get, post } from '@/api/client'
import { QUESTION_TYPES, type Question, type QuestionPage, type Status } from '@/api/types'
import { useTags, useTree } from '@/hooks/queries'
import { useToast } from '@/contexts/toast'
import { plain, relTime } from '@/lib/format'
import { Badge, ConfirmDialog, Empty, ErrorState, Field, Loading, Menu, Modal, StatusBadge, TagInput, cx } from './ui'
import { TopicPicker } from './TopicPicker'
import { tt, tl } from '@/i18n'

export interface QFilters {
  q?: string
  subject_id?: string
  topic_id?: string
  tag?: string
  question_type?: string
  difficulty?: string
  status?: string
  archived?: boolean
  sort?: string
}

const SORTS = [
  ['created_desc', 'Newest'], ['created_asc', 'Oldest'], ['updated_desc', 'Recently edited'],
  ['title', 'Title A–Z'], ['due', 'Next review'], ['lapses', 'Most forgotten'],
]

export function QuestionTable({ initial, fixed, compact, empty }: { initial?: QFilters; fixed?: QFilters; compact?: boolean; empty?: React.ReactNode }) {
  const [f, setF] = useState<QFilters>({ sort: 'created_desc', ...initial })
  const [q, setQ] = useState(f.q ?? '')
  const [page, setPage] = useState(1)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [showFilters, setShowFilters] = useState(!!(initial?.subject_id || initial?.tag || initial?.status || initial?.question_type || initial?.difficulty))
  const [confirm, setConfirm] = useState<null | { ids: string[]; action: string }>(null)
  const [bulkModal, setBulkModal] = useState<null | 'tags' | 'subject' | 'topic' | 'difficulty'>(null)
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const { data: tree = [] } = useTree()
  const { data: tags = [] } = useTags()

  useEffect(() => { const t = setTimeout(() => { setF((x) => ({ ...x, q })); setPage(1) }, 250); return () => clearTimeout(t) }, [q])
  useEffect(() => setSel(new Set()), [f, page])

  const params = { ...f, ...fixed, tag: (fixed?.tag ?? f.tag) || undefined, page, page_size: compact ? 10 : 25 }
  const { data, isLoading, error, refetch, isPlaceholderData } = useQuery({ queryKey: ['questions', params], queryFn: () => get<QuestionPage>('/questions', params as never), placeholderData: keepPreviousData })

  const bulk = useMutation({
    mutationFn: (b: Record<string, unknown>) => post<{ affected: number }>('/questions/bulk/apply', { ids: [...sel], ...b }),
    onSuccess: (r) => { qc.invalidateQueries(); toast.ok(`${r.affected} question${r.affected === 1 ? '' : 's'} updated`); setSel(new Set()); setBulkModal(null); setConfirm(null) },
    onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")),
  })
  const one = useMutation({
    mutationFn: async (v: { id: string; action: 'duplicate' | 'delete' | 'archive' | 'unarchive' | 'suspend' | 'unsuspend' }) => {
      if (v.action === 'duplicate') return post(`/questions/${v.id}/duplicate`)
      if (v.action === 'delete') return del(`/questions/${v.id}`)
      if (v.action === 'suspend' || v.action === 'unsuspend') return post(`/questions/${v.id}/suspend?suspended=${v.action === 'suspend'}`)
      return post('/questions/bulk/apply', { ids: [v.id], action: v.action })
    },
    onSuccess: () => { qc.invalidateQueries(); setConfirm(null) },
    onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")),
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / (compact ? 10 : 25)))
  const allSelected = items.length > 0 && items.every((i) => sel.has(i.id))
  const set = (p: Partial<QFilters>) => { setF((x) => ({ ...x, ...p })); setPage(1) }
  const activeFilters = useMemo(() => ['subject_id', 'tag', 'question_type', 'difficulty', 'status'].filter((k) => (f as Record<string, unknown>)[k]).length + (f.archived ? 1 : 0), [f])

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex h-8 min-w-48 flex-1 items-center gap-2 rounded border border-line bg-surface px-2.5 focus-within:border-accent">
          <Search size={14} className="text-faint" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={tt("Search questions and answers…")} aria-label={tt("Search questions")} className="w-full bg-transparent text-sm outline-none placeholder:text-faint" />
        </div>
        <button className={cx('btn', activeFilters && 'border-accent text-accent')} onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters}>
          <SlidersHorizontal size={14} /> {tt("Filters")}{activeFilters ? ` · ${activeFilters}` : ''}
        </button>
        <select className="field h-8 w-auto py-0" aria-label={tt("Sort")} value={f.sort} onChange={(e) => set({ sort: e.target.value })}>
          {SORTS.map(([v, l]) => <option key={v} value={v}>{tt(l)}</option>)}
        </select>
      </div>

      {showFilters && (
        <div className="card mb-3 grid gap-3 p-3 sm:grid-cols-3 lg:grid-cols-6">
          {!fixed?.subject_id && !fixed?.topic_id && (
            <Field label={tt("Subject")}><select className="field" value={f.subject_id ?? ''} onChange={(e) => set({ subject_id: e.target.value || undefined })}><option value="">{tt("All")}</option>{tree.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
          )}
          <Field label={tt("Type")}><select className="field" value={f.question_type ?? ''} onChange={(e) => set({ question_type: e.target.value || undefined })}><option value="">{tt("All")}</option>{QUESTION_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</select></Field>
          <Field label={tt("Difficulty")}><select className="field" value={f.difficulty ?? ''} onChange={(e) => set({ difficulty: e.target.value || undefined })}><option value="">{tt("All")}</option><option value="easy">{tt("Easy")}</option><option value="medium">{tt("Medium")}</option><option value="hard">{tt("Hard")}</option></select></Field>
          <Field label={tt("Status")}><select className="field" value={f.status ?? ''} onChange={(e) => set({ status: e.target.value || undefined })}><option value="">{tt("All")}</option><option value="due">{tt("Due now")}</option><option value="new">{tt("New")}</option><option value="learning">{tt("Learning")}</option><option value="reviewing">{tt("Reviewing")}</option><option value="mastered">{tt("Mastered")}</option><option value="suspended">{tt("Suspended")}</option></select></Field>
          <Field label={tt("Tag")}><select className="field" value={f.tag ?? ''} onChange={(e) => set({ tag: e.target.value || undefined })}><option value="">{tt("All")}</option>{tags.map((t) => <option key={t.id} value={t.name}>#{t.name}</option>)}</select></Field>
          <label className="flex items-end gap-2 pb-1.5 text-sm"><input type="checkbox" checked={!!f.archived} onChange={(e) => set({ archived: e.target.checked })} /> {tt("Archived")}</label>
        </div>
      )}

      {sel.size > 0 && (
        <div className="card mb-3 flex flex-wrap items-center gap-2 border-accent/40 bg-accent/5 px-3 py-2" role="region" aria-label={tt("Bulk actions")}>
          <span className="text-sm font-medium">{sel.size} {tt("selected")}</span>
          <button className="btn h-7" onClick={() => setBulkModal('tags')}>{tt("Add / remove tags")}</button>
          <button className="btn h-7" onClick={() => setBulkModal('subject')}>{tt("Set subject")}</button>
          <button className="btn h-7" onClick={() => setBulkModal('topic')}>{tt("Add to topic")}</button>
          <button className="btn h-7" onClick={() => setBulkModal('difficulty')}>{tt("Difficulty")}</button>
          <Menu items={[
            { label: f.archived ? tt("Unarchive") : tt("Archive"), onClick: () => bulk.mutate({ action: f.archived ? 'unarchive' : 'archive' }) },
            { label: tt("Suspend"), onClick: () => bulk.mutate({ action: 'suspend' }) },
            { label: tt("Unsuspend"), onClick: () => bulk.mutate({ action: 'unsuspend' }) },
            { label: tt("Reset learning progress"), onClick: () => setConfirm({ ids: [...sel], action: 'reset_progress' }) },
            'sep',
            { label: tt("Delete…"), danger: true, onClick: () => setConfirm({ ids: [...sel], action: 'delete' }) },
          ]} />
          <button className="btn btn-ghost ml-auto h-7" onClick={() => setSel(new Set())}>{tt("Clear")}</button>
        </div>
      )}

      {isLoading ? <Loading /> : error ? <ErrorState error={error} retry={refetch} /> : items.length === 0 ? (
        empty ?? <Empty title={activeFilters || f.q ? tt("No questions match") : tt("No questions yet")} icon={<Archive size={28} />}>{activeFilters || f.q ? tt("Try removing a filter or changing your search.") : tt("Create your first question with the New button.")}</Empty>
      ) : (
        <div className={cx('card divide-y divide-line', isPlaceholderData && 'opacity-60')}>
          {!compact && (
            <div className="flex items-center gap-3 px-3 py-2 text-xs text-muted">
              <input type="checkbox" checked={allSelected} onChange={(e) => setSel(e.target.checked ? new Set(items.map((i) => i.id)) : new Set())} aria-label={tt("Select all on page")} />
              <span>{total} {tt("question")}{total === 1 ? '' : 's'}</span>
            </div>
          )}
          {items.map((it) => (
            <Row key={it.id} q={it} compact={compact} selected={sel.has(it.id)} onSelect={(on) => setSel((s) => { const n = new Set(s); on ? n.add(it.id) : n.delete(it.id); return n })}
              menu={[
                { label: tt("Edit"), onClick: () => nav(`/questions/${it.id}`) },
                { label: tt("Duplicate"), onClick: () => one.mutate({ id: it.id, action: 'duplicate' }) },
                { label: it.progress.suspended ? tt("Unsuspend") : tt("Suspend"), onClick: () => one.mutate({ id: it.id, action: it.progress.suspended ? 'unsuspend' : 'suspend' }) },
                { label: it.archived ? tt("Unarchive") : tt("Archive"), onClick: () => one.mutate({ id: it.id, action: it.archived ? 'unarchive' : 'archive' }) },
                'sep',
                { label: tt("Delete…"), danger: true, onClick: () => setConfirm({ ids: [it.id], action: 'delete-one' }) },
              ]} />
          ))}
        </div>
      )}

      {pages > 1 && (
        <div className="mt-3 flex items-center justify-between text-sm text-muted">
          <span>{tt("Page")} {page} {tt("of")} {pages}</span>
          <div className="flex gap-1">
            <button className="btn btn-icon" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label={tt("Previous page")}><ChevronLeft size={15} className="rtl:rotate-180" /></button>
            <button className="btn btn-icon" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label={tt("Next page")}><ChevronRight size={15} className="rtl:rotate-180" /></button>
          </div>
        </div>
      )}

      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} busy={bulk.isPending || one.isPending}
        title={confirm?.action === 'reset_progress' ? tt("Reset progress?") : tt("Delete permanently?")}
        confirmLabel={confirm?.action === 'reset_progress' ? tt("Reset") : tt("Delete")}
        message={confirm?.action === 'reset_progress' ? tt("Learning progress for {n} question(s) returns to “New”. Review history is kept.", { n: confirm.ids.length }) : tt("{n} question(s) and their review history will be permanently deleted. This cannot be undone. (Archive instead to hide them.)", { n: confirm?.ids.length ?? 0 })}
        onConfirm={() => { if (!confirm) return; if (confirm.action === 'delete-one') one.mutate({ id: confirm.ids[0], action: 'delete' }); else bulk.mutate({ action: confirm.action }) }} />
      <BulkModal kind={bulkModal} onClose={() => setBulkModal(null)} tags={tags.map((t) => t.name)} subjects={tree.map((s) => ({ id: s.id, name: s.name }))} busy={bulk.isPending} onApply={(b) => bulk.mutate(b)} />
    </div>
  )
}

function Row({ q, selected, onSelect, menu, compact }: { q: Question; selected: boolean; onSelect(on: boolean): void; menu: React.ComponentProps<typeof Menu>['items']; compact?: boolean }) {
  const p = q.progress
  return (
    <div className={cx('flex items-start gap-3 px-3 py-2.5 hover:bg-raised/60', selected && 'bg-accent/5')}>
      {!compact && <input type="checkbox" className="mt-1.5" checked={selected} onChange={(e) => onSelect(e.target.checked)} aria-label={tt("Select {question}", { question: q.title || 'question' })} />}
      <Link to={`/questions/${q.id}`} className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate text-sm font-medium">{q.title || plain(q.content, 90) || tt("Untitled question")}</span>
          {q.archived && <Badge>{tt("Archived")}</Badge>}
        </div>
        {q.title && q.content && <p className="mt-0.5 truncate text-sm text-muted">{plain(q.content, 140)}</p>}
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <StatusBadge status={p.status} />
          <Badge>{QUESTION_TYPES.find((t) => t.value === q.question_type)?.label}</Badge>
          <Badge tone={q.difficulty === 'hard' ? 'bad' : q.difficulty === 'easy' ? 'good' : 'neutral'} className="capitalize">{tl(q.difficulty)}</Badge>
          {q.topics.slice(0, 2).map((t) => <span key={t.id} className="truncate">· {t.name}</span>)}
          {q.tags.slice(0, 3).map((t) => <span key={t.id}>#{t.name}</span>)}
          {p.due_at && !p.suspended && <span className="ml-auto">{new Date(p.due_at) <= new Date() ? <span className="font-medium text-warn">{tt("Due")}</span> : `Due ${relTime(p.due_at)}`}</span>}
        </div>
      </Link>
      <Menu items={menu} />
    </div>
  )
}

function BulkModal({ kind, onClose, tags, subjects, onApply, busy }: { kind: 'tags' | 'subject' | 'topic' | 'difficulty' | null; onClose(): void; tags: string[]; subjects: { id: string; name: string }[]; onApply(b: Record<string, unknown>): void; busy: boolean }) {
  const [tagNames, setTagNames] = useState<string[]>([])
  const [subject, setSubject] = useState('')
  const [topic, setTopic] = useState<string[]>([])
  const [diff, setDiff] = useState('medium')
  useEffect(() => { setTagNames([]); setSubject(''); setTopic([]) }, [kind])
  const footer = (
    <>
      <button className="btn" onClick={onClose}>{tt("Cancel")}</button>
      {kind === 'tags' && <><button className="btn" disabled={busy || !tagNames.length} onClick={() => onApply({ action: 'remove_tags', tags: tagNames })}>{tt("Remove tags")}</button><button className="btn btn-primary" disabled={busy || !tagNames.length} onClick={() => onApply({ action: 'add_tags', tags: tagNames })}>{tt("Add tags")}</button></>}
      {kind === 'subject' && <button className="btn btn-primary" disabled={busy} onClick={() => onApply({ action: 'set_subject', subject_id: subject || null })}>{tt("Apply")}</button>}
      {kind === 'topic' && <button className="btn btn-primary" disabled={busy || !topic[0]} onClick={() => onApply({ action: 'add_topic', topic_id: topic[0] })}>{tt("Add to topic")}</button>}
      {kind === 'difficulty' && <button className="btn btn-primary" disabled={busy} onClick={() => onApply({ action: 'set_difficulty', difficulty: diff })}>{tt("Apply")}</button>}
    </>
  )
  return (
    <Modal open={!!kind} onClose={onClose} title={{ tags: tt("Bulk tagging"), subject: tt("Set subject"), topic: tt("Add to topic"), difficulty: tt("Set difficulty") }[kind ?? 'tags']} footer={footer}>
      {kind === 'tags' && <TagInput value={tagNames} onChange={setTagNames} suggestions={tags} />}
      {kind === 'subject' && <select className="field" value={subject} onChange={(e) => setSubject(e.target.value)}><option value="">{tt("— none —")}</option>{subjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
      {kind === 'topic' && <TopicPicker single value={topic} onChange={setTopic} />}
      {kind === 'difficulty' && <select className="field" value={diff} onChange={(e) => setDiff(e.target.value)}><option value="easy">{tt("Easy")}</option><option value="medium">{tt("Medium")}</option><option value="hard">{tt("Hard")}</option></select>}
    </Modal>
  )
}
export type { Status }
