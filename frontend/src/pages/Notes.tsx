import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FileText, Link2, Plus, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { del, get, patch } from '@/api/client'
import type { Note, QuestionPage } from '@/api/types'
import { MarkdownEditor } from '@/components/MarkdownEditor'
import { useQuickCreate } from '@/components/QuickCreate'
import { TopicPicker } from '@/components/TopicPicker'
import { ConfirmDialog, Empty, Field, Loading, Menu, Modal, TagInput, cx } from '@/components/ui'
import { useTags, useTree } from '@/hooks/queries'
import { useToast } from '@/contexts/toast'
import { plain, relTime } from '@/lib/format'
import { tt } from '@/i18n'

const KIND_LABEL = { note: 'Note', definition: 'Definition', formula: 'Formula' }

export default function NotesPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const qc = useQuickCreate()
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [kind, setKind] = useState('')
  useEffect(() => { const t = setTimeout(() => setDq(q), 250); return () => clearTimeout(t) }, [q])
  const list = useQuery({ queryKey: ['notes', 'list', dq, kind], queryFn: () => get<Note[]>('/notes', { q: dq, kind }) })

  return (
    <div className="flex h-full">
      <aside className={cx('w-full shrink-0 flex-col border-e border-line bg-surface md:flex md:w-80', id ? 'hidden' : 'flex')}>
        <div className="space-y-2 border-b border-line p-3">
          <div className="flex items-center justify-between"><h1 className="text-base font-semibold">{tt("Notes")}</h1><button className="btn btn-primary" onClick={() => qc.newNote()}><Plus size={14} /> {tt("New note")}</button></div>
          <input className="field" placeholder={tt("Search notes…")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={tt("Search notes")} />
          <select className="field" value={kind} onChange={(e) => setKind(e.target.value)} aria-label={tt("Filter by type")}><option value="">{tt("All types")}</option><option value="note">{tt("Notes")}</option><option value="definition">{tt("Definitions")}</option><option value="formula">{tt("Formulas")}</option></select>
        </div>
        <div className="flex-1 overflow-y-auto">
          {list.isLoading ? <Loading /> : !list.data?.length ? <Empty title={dq ? tt("No matching notes") : tt("No notes yet")} icon={<FileText size={26} />}>{dq ? '' : tt("Write notes in Markdown with LaTeX, tables and images — then turn parts of them into questions.")}</Empty> : (
            <ul>{list.data.map((n) => (
              <li key={n.id}><Link to={`/notes/${n.id}`} className={cx('block border-b border-line px-3 py-2.5 hover:bg-raised/60', n.id === id && 'bg-raised')}>
                <div className="flex items-center gap-2"><span className="truncate text-sm font-medium">{n.title || tt("Untitled note")}</span>{n.kind !== 'note' && <span className="rounded bg-raised px-1 text-[11px] text-muted">{KIND_LABEL[n.kind]}</span>}</div>
                <p className="mt-0.5 line-clamp-2 text-xs text-muted">{plain(n.content, 140) || tt("Empty")}</p><div className="mt-1 text-[11px] text-faint">{relTime(n.updated_at)}</div>
              </Link></li>
            ))}</ul>
          )}
        </div>
      </aside>
      <section className={cx('min-w-0 flex-1 overflow-y-auto', !id && 'hidden md:block')}>
        {id ? <Editor key={id} id={id} onGone={() => nav('/notes')} /> : <div className="flex h-full items-center justify-center"><Empty title={tt("Select a note")} icon={<FileText size={28} />}>{tt("Pick a note from the list or create a new one.")}</Empty></div>}
      </section>
    </div>
  )
}

function Editor({ id, onGone }: { id: string; onGone(): void }) {
  const qcache = useQueryClient()
  const toast = useToast()
  const qc = useQuickCreate()
  const { data: tree = [] } = useTree()
  const { data: tags = [] } = useTags()
  const note = useQuery({ queryKey: ['note', id], queryFn: () => get<Note>(`/notes/${id}`) })
  const back = useQuery({ queryKey: ['note-back', id], queryFn: () => get<{ id: string; title: string }[]>(`/notes/${id}/backlinks`) })
  const [f, setF] = useState<Note | null>(null)
  const [tagNames, setTagNames] = useState<string[]>([])
  const [state, setState] = useState<'saved' | 'dirty' | 'saving' | 'error'>('saved')
  const [confirm, setConfirm] = useState(false)
  const [linkPicker, setLinkPicker] = useState(false)
  const ta = useRef<HTMLTextAreaElement>(null)
  const loaded = useRef(false)

  useEffect(() => { if (note.data && !loaded.current) { loaded.current = true; setF(note.data); setTagNames(note.data.tags.map((t) => t.name)) } }, [note.data])

  const save = useMutation({
    mutationFn: (n: Note) => patch<Note>(`/notes/${id}`, { title: n.title, content: n.content, kind: n.kind, subject_id: n.subject_id, course_id: n.course_id, chapter_id: n.chapter_id, topic_id: n.topic_id, question_id: n.question_id, tags: tagNames, set_links: true }),
    onMutate: () => setState('saving'),
    onSuccess: (r) => { setState('saved'); qcache.setQueryData(['note', id], r); qcache.invalidateQueries({ queryKey: ['notes'] }); qcache.invalidateQueries({ queryKey: ['note-back'] }) },
    onError: (e) => { setState('error'); toast.err(e instanceof Error ? e.message : tt("Save failed")) },
  })
  const remove = useMutation({ mutationFn: () => del(`/notes/${id}`), onSuccess: () => { qcache.invalidateQueries({ queryKey: ['notes'] }); toast.ok(tt("Note deleted")); onGone() } })

  const first = useRef(true)
  useEffect(() => {
    if (!f) return
    if (first.current) { first.current = false; return }
    setState('dirty')
    const t = setTimeout(() => save.mutate(f), 1200)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f, tagNames])

  const courses = useMemo(() => tree.find((s) => s.id === f?.subject_id)?.courses ?? [], [tree, f?.subject_id])
  const chapters = useMemo(() => courses.find((c) => c.id === f?.course_id)?.chapters ?? [], [courses, f?.course_id])

  if (note.isLoading || !f) return <Loading />
  if (note.error) return <Empty title={tt("Note not found")} action={<Link className="btn" to="/notes">{tt("Back to notes")}</Link>} />
  const set = (p: Partial<Note>) => setF({ ...f, ...p })

  function makeQuestion() {
    const el = ta.current
    const sel = el && el.selectionStart !== el.selectionEnd ? f!.content.slice(el.selectionStart, el.selectionEnd) : ''
    if (!sel.trim()) return toast.err(tt("Select some text in the editor first (switch to Write view)"))
    qc.open('question', { question: { content: sel.trim(), subject_id: f!.subject_id ?? undefined, topic_ids: f!.topic_id ? [f!.topic_id] : [], source: `Note: ${f!.title || 'Untitled'}` } })
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-5 sm:px-6">
      <Link to="/notes" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-fg md:hidden"><ArrowLeft size={14} className="rtl:rotate-180" /> {tt("Notes")}</Link>
      <div className="mb-3 flex items-center gap-2">
        <input className="min-w-0 flex-1 border-0 bg-transparent text-2xl font-semibold tracking-tight outline-none placeholder:text-faint" value={f.title} onChange={(e) => set({ title: e.target.value })} placeholder={tt("Untitled note")} maxLength={300} aria-label={tt("Title")} />
        <span className="shrink-0 text-xs text-muted" aria-live="polite">{{ saved: 'Saved', dirty: 'Unsaved…', saving: 'Saving…', error: 'Not saved' }[state]}</span>
        <Menu items={[{ label: tt("Insert link to another note…"), onClick: () => setLinkPicker(true) }, { label: tt("Generate questions with AI"), onClick: () => qc.open('ai', { ai: { note_id: id } }) }, 'sep', { label: tt("Delete note…"), danger: true, onClick: () => setConfirm(true) }]} />
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label={tt("Type")}><select className="field" value={f.kind} onChange={(e) => set({ kind: e.target.value as Note['kind'] })}><option value="note">{tt("Note")}</option><option value="definition">{tt("Definition")}</option><option value="formula">{tt("Formula")}</option></select></Field>
        <Field label={tt("Subject")}><select className="field" value={f.subject_id ?? ''} onChange={(e) => set({ subject_id: e.target.value || null, course_id: null, chapter_id: null })}><option value="">{tt("— none —")}</option>{tree.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        <Field label={tt("Course")}><select className="field" disabled={!courses.length} value={f.course_id ?? ''} onChange={(e) => set({ course_id: e.target.value || null, chapter_id: null })}><option value="">{tt("— none —")}</option>{courses.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <Field label={tt("Chapter")}><select className="field" disabled={!chapters.length} value={f.chapter_id ?? ''} onChange={(e) => set({ chapter_id: e.target.value || null })}><option value="">{tt("— none —")}</option>{chapters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <div className="sm:col-span-2"><span className="label">{tt("Topic")}</span><TopicPicker single value={f.topic_id ? [f.topic_id] : []} onChange={(v) => set({ topic_id: v[0] ?? null })} /></div>
        <div className="sm:col-span-2"><span className="label">{tt("Question")}</span><QuestionPicker value={f.question_id} onChange={(v) => set({ question_id: v })} /></div>
        <div className="sm:col-span-2 lg:col-span-4"><span className="label">{tt("Tags")}</span><TagInput value={tagNames} onChange={setTagNames} suggestions={tags.map((t) => t.name)} /></div>
      </div>

      <MarkdownEditor value={f.content} onChange={(v) => set({ content: v })} label={tt("Note content")} minRows={18} attach={{ note_id: id }} textareaRef={ta} placeholder={tt("Write in Markdown. Use $LaTeX$ for math, [[Note title]] to link notes.")} />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button className="btn" onClick={makeQuestion}><Wand2 size={14} /> {tt("Make question from selection")}</button>
        <button className="btn" onClick={() => qc.open('ai', { ai: { note_id: id } })}><Sparkles size={14} /> {tt("AI questions from this note")}</button>
      </div>

      {(f.links_to.length > 0 || (back.data?.length ?? 0) > 0) && (
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <LinkList title={tt("Links to")} items={note.data?.links_to ?? []} />
          <LinkList title={tt("Linked from")} items={back.data ?? []} />
        </div>
      )}
      <LinkPicker open={linkPicker} onClose={() => setLinkPicker(false)} currentId={id} onPick={(t) => { set({ content: f.content + (f.content && !f.content.endsWith('\n') ? '\n' : '') + `[[${t}]]` }); setLinkPicker(false) }} />
      <ConfirmDialog open={confirm} onClose={() => setConfirm(false)} onConfirm={() => remove.mutate()} title={tt("Delete this note?")} message={tt("This cannot be undone.")} busy={remove.isPending} />
    </div>
  )
}

function LinkList({ title, items }: { title: string; items: { id: string; title: string }[] }) {
  if (!items.length) return null
  return <div><h2 className="h-section mb-1 flex items-center gap-1"><Link2 size={13} /> {title}</h2><ul className="space-y-0.5 text-sm">{items.map((l) => <li key={l.id}><Link className="text-accent underline" to={`/notes/${l.id}`}>{l.title || tt("Untitled")}</Link></li>)}</ul></div>
}

function LinkPicker({ open, onClose, onPick, currentId }: { open: boolean; onClose(): void; onPick(title: string): void; currentId: string }) {
  const [q, setQ] = useState('')
  const r = useQuery({ queryKey: ['notes', 'picker', q], queryFn: () => get<Note[]>('/notes', { q, limit: 30 }), enabled: open })
  return (
    <Modal open={open} onClose={onClose} title={tt("Link to a note")}>
      <input className="field mb-2" placeholder={tt("Search notes…")} value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      <ul className="max-h-64 overflow-y-auto">{r.data?.filter((n) => n.id !== currentId && n.title.trim()).map((n) => <li key={n.id}><button className="block w-full rounded px-2 py-1.5 text-start text-sm hover:bg-raised" onClick={() => onPick(n.title)}>{n.title}</button></li>)}</ul>
      <p className="mt-2 text-xs text-muted">{tt("Links use the note’s title:")} <code className="font-mono">[[Title]]</code>{tt(". Only titled notes can be linked.")}</p>
    </Modal>
  )
}

function QuestionPicker({ value, onChange }: { value: string | null; onChange(v: string | null): void }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const current = useQuery({ queryKey: ['question', value], queryFn: () => get<{ id: string; title: string; content: string }>(`/questions/${value}`), enabled: !!value })
  const res = useQuery({ queryKey: ['questions', 'picker', q], queryFn: () => get<QuestionPage>('/questions', { q, page_size: 8 }), enabled: open })
  if (value) return <div className="flex items-center gap-2 rounded border border-line px-2.5 py-1.5 text-sm"><Link to={`/questions/${value}`} className="min-w-0 flex-1 truncate text-accent underline">{current.data?.title || plain(current.data?.content ?? '', 60) || tt("Question")}</Link><button className="text-faint hover:text-fg" aria-label={tt("Detach question")} onClick={() => onChange(null)}><Trash2 size={13} /></button></div>
  return (
    <div className="relative">
      <input className="field" placeholder={tt("Attach to a question…")} value={q} onFocus={() => setOpen(true)} onChange={(e) => { setQ(e.target.value); setOpen(true) }} aria-label={tt("Search questions")} />
      {open && <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-line bg-surface py-1 shadow-lg">
        {res.data?.items.length === 0 && <div className="px-3 py-2 text-sm text-muted">{tt("No questions found")}</div>}
        {res.data?.items.map((x) => <button key={x.id} className="block w-full truncate px-3 py-1.5 text-start text-sm hover:bg-raised" onClick={() => { onChange(x.id); setOpen(false); setQ('') }}>{x.title || plain(x.content, 80)}</button>)}
        <button className="block w-full px-3 py-1 text-start text-xs text-muted hover:bg-raised" onClick={() => setOpen(false)}>{tt("Close")}</button>
      </div>}
    </div>
  )
}
