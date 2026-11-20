import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '@/api/client'
import type { QuestionPage } from '@/api/types'
import { SortableList } from '@/components/lms/SortableList'
import { TopicPicker } from '@/components/TopicPicker'
import { Badge, Button, ConfirmDialog, Empty, Field, Loading, Modal } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { AiStudio } from '@/components/AiStudio'
import { plain } from '@/lib/format'

interface PSet { id: string; title: string; description: string; kind: 'practice' | 'exam'; is_published: boolean; question_count: number; items: { id: string; question_id: string; title: string; question_type: string }[] }

/** Topic-based practice sets and exams for a course. Questions come from the teacher's private bank; students only
 * receive the questions placed here (and only the solution after pressing "show answer"). */
export function CoursePractice({ courseId }: { courseId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<'practice' | 'exam'>('practice')
  const [picking, setPicking] = useState<string | null>(null)
  const [rm, setRm] = useState<PSet | null>(null)
  const [aiFor, setAiFor] = useState<string | null>(null)
  const list = useQuery({ queryKey: ['teach-practice', courseId], queryFn: () => get<PSet[]>(`/teach/courses/${courseId}/practice-sets`) })
  const refresh = () => qc.invalidateQueries({ queryKey: ['teach-practice', courseId] })
  const err = (e: unknown) => toast.err(e instanceof Error ? e.message : 'Failed')
  const run = useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: refresh, onError: err })
  const create = useMutation({ mutationFn: () => post(`/teach/courses/${courseId}/practice-sets`, { title, kind }), onSuccess: () => { setTitle(''); refresh() }, onError: err })

  if (list.isLoading) return <Loading />
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">Create a set per topic (or a final exam), add questions from your private question bank, then publish. Students see the question, press <b>Show answer</b>, and get the full step-by-step solution.</p>
      <form className="card flex flex-wrap items-end gap-3 p-4" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create.mutate() }}>
        <div className="min-w-56 flex-1"><Field label="New set title"><input className="field" dir="auto" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. NPV — practice" maxLength={200} /></Field></div>
        <Field label="Type"><select className="field" value={kind} onChange={(e) => setKind(e.target.value as 'practice' | 'exam')}><option value="practice">Practice</option><option value="exam">Exam</option></select></Field>
        <Button type="submit" className="btn-primary" loading={create.isPending} disabled={!title.trim()}><Plus size={14} /> Create set</Button>
      </form>
      {!list.data?.length && <div className="card"><Empty title="No practice sets yet" /></div>}
      <SortableList items={list.data ?? []} className="space-y-3" onReorder={(ids) => run.mutate(() => post(`/teach/courses/${courseId}/practice-sets/reorder`, { ids }))}
        render={(s) => (
          <section className="card">
            <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
              <input className="min-w-0 flex-1 bg-transparent font-medium outline-none focus:underline" dir="auto" defaultValue={s.title} aria-label="Set title" onBlur={(e) => e.target.value.trim() && e.target.value !== s.title && run.mutate(() => patch(`/teach/practice-sets/${s.id}`, { title: e.target.value }))} />
              <Badge tone={s.kind === 'exam' ? 'warn' : 'accent'}>{s.kind}</Badge>
              <label className="flex items-center gap-1.5 text-xs text-muted"><input type="checkbox" checked={s.is_published} onChange={(e) => run.mutate(() => patch(`/teach/practice-sets/${s.id}`, { is_published: e.target.checked }))} /> Published</label>
              <button className="btn btn-ghost btn-icon text-bad" aria-label="Delete set" onClick={() => setRm(s)}><Trash2 size={14} /></button>
            </div>
            <div className="p-3">
              {s.items.length === 0 ? <p className="text-sm text-muted">No questions yet.</p> : (
                <SortableList items={s.items} className="space-y-1" onReorder={(ids) => run.mutate(() => post(`/teach/practice-sets/${s.id}/items/reorder`, { ids }))}
                  render={(it, i) => <div className="flex items-center gap-2 rounded px-2 py-1 hover:bg-raised/60"><span className="w-6 text-xs text-muted tabnum">{i + 1}</span><span dir="auto" className="min-w-0 flex-1 truncate text-sm">{it.title}</span><Badge>{it.question_type.replace('_', ' ')}</Badge><button className="text-faint hover:text-bad" aria-label="Remove question" onClick={() => run.mutate(() => del(`/teach/practice-items/${it.id}`))}><Trash2 size={13} /></button></div>} />
              )}
              <div className="mt-2 flex flex-wrap gap-2"><button className="btn" onClick={() => setPicking(s.id)}><Plus size={14} /> Add questions from bank</button><button className="btn" onClick={() => setAiFor(s.id)}>Generate questions with AI</button></div>
            </div>
          </section>
        )} />
      {aiFor && <AiStudio courseId={courseId} practiceSetId={aiFor} initialMode="questions" onClose={() => { setAiFor(null); refresh() }} />}
      {picking && <BankPicker setId={picking} onClose={() => setPicking(null)} onDone={() => { setPicking(null); refresh() }} />}
      <ConfirmDialog open={!!rm} onClose={() => setRm(null)} title={`Delete “${rm?.title}”?`} message="The set is removed from the course. The questions stay in your private bank." onConfirm={() => rm && run.mutateAsync(() => del(`/teach/practice-sets/${rm.id}`)).then(() => setRm(null))} />
    </div>
  )
}

function BankPicker({ setId, onClose, onDone }: { setId: string; onClose(): void; onDone(): void }) {
  const [q, setQ] = useState('')
  const [topic, setTopic] = useState<string[]>([])
  const [sel, setSel] = useState<Set<string>>(new Set())
  const toast = useToast()
  const res = useQuery({ queryKey: ['questions', 'practice-picker', q, topic], queryFn: () => get<QuestionPage>('/questions', { q, topic_id: topic[0], page_size: 100 }) })
  const add = useMutation({ mutationFn: () => post(`/teach/practice-sets/${setId}/items`, { question_ids: [...sel] }), onSuccess: onDone, onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed') })
  const items = res.data?.items ?? []
  return (
    <Modal open onClose={onClose} wide title="Add questions from your private bank" footer={<><button className="btn" onClick={onClose}>Cancel</button><Button className="btn-primary" disabled={!sel.size} loading={add.isPending} onClick={() => add.mutate()}>Add {sel.size || ''} selected</Button></>}>
      <div className="mb-3 grid gap-2 sm:grid-cols-2"><input className="field" dir="auto" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search questions" /><TopicPicker single value={topic} onChange={setTopic} placeholder="Filter by topic" /></div>
      {res.isLoading ? <Loading /> : items.length === 0 ? <p className="text-sm text-muted">No questions found.</p> : (
        <>
          <button className="mb-1 text-xs text-accent underline" onClick={() => setSel(sel.size === items.length ? new Set() : new Set(items.map((i) => i.id)))}>{sel.size === items.length ? 'Clear selection' : `Select all ${items.length}`}</button>
          <ul className="max-h-[50vh] divide-y divide-line overflow-y-auto rounded border border-line">
            {items.map((x) => <li key={x.id}><label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-raised/60"><input type="checkbox" checked={sel.has(x.id)} onChange={(e) => setSel((s) => { const n = new Set(s); e.target.checked ? n.add(x.id) : n.delete(x.id); return n })} /><span dir="auto" className="min-w-0 flex-1 truncate text-sm">{x.title || plain(x.content, 80)}</span><span className="text-xs text-muted">{x.topics[0]?.name}</span></label></li>)}
          </ul>
        </>
      )}
    </Modal>
  )
}
