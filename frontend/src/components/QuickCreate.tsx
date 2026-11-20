import { createContext, useContext, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BookOpen, FileText, FolderTree, HelpCircle, Plus, Sparkles } from 'lucide-react'
import { post } from '@/api/client'
import type { Note, QuestionDraft, SubjectNode } from '@/api/types'
import { useTree } from '@/hooks/queries'
import { useToast } from '@/contexts/toast'
import { AiGenerateDialog } from './AiGenerate'
import { QuestionForm } from './QuestionForm'
import { TopicPicker } from './TopicPicker'
import { Button, Field, Menu, Modal } from './ui'

type Kind = 'question' | 'topic' | 'subject' | 'ai'
interface Opts {
  question?: Partial<QuestionDraft>
  topic?: { subject_id?: string; parent_id?: string; chapter_id?: string }
  ai?: { topic_id?: string; text?: string; note_id?: string }
}
const Ctx = createContext<{ open(kind: Kind, opts?: Opts): void; newNote(defaults?: Partial<Note>): void }>({ open() {}, newNote() {} })
export const useQuickCreate = () => useContext(Ctx)

export function QuickCreateProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ kind: Kind; opts: Opts } | null>(null)
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const close = () => setState(null)

  const newNote = async (defaults: Partial<Note> = {}) => {
    try {
      const n = await post<Note>('/notes', { title: '', content: '', ...defaults })
      qc.invalidateQueries({ queryKey: ['notes'] })
      nav(`/notes/${n.id}`)
    } catch (e) {
      toast.err(e instanceof Error ? e.message : 'Could not create note')
    }
  }

  return (
    <Ctx.Provider value={{ open: (kind, opts = {}) => setState({ kind, opts }), newNote }}>
      {children}
      <Modal open={state?.kind === 'question'} onClose={close} title="New question" wide>
        {state?.kind === 'question' && <QuestionForm defaults={state.opts.question} onSaved={close} onCancel={close} />}
      </Modal>
      <Modal open={state?.kind === 'topic'} onClose={close} title="New topic">
        {state?.kind === 'topic' && <TopicForm defaults={state.opts.topic} onDone={(id) => { close(); nav(`/library/topic/${id}`) }} onCancel={close} />}
      </Modal>
      <Modal open={state?.kind === 'subject'} onClose={close} title="New subject">
        {state?.kind === 'subject' && <SubjectForm onDone={(s) => { close(); nav(`/library/subject/${s.id}`) }} onCancel={close} />}
      </Modal>
      {state?.kind === 'ai' && <AiGenerateDialog onClose={close} initial={state.opts.ai} />}
    </Ctx.Provider>
  )
}

export function QuickCreateMenu() {
  const qc = useQuickCreate()
  return (
    <Menu
      label="Quick create"
      icon={<span className="flex items-center gap-1 px-2.5 text-sm font-medium"><Plus size={15} /> <span className="hidden sm:inline">New</span></span>}
      items={[
        { label: 'Question', onClick: () => qc.open('question') },
        { label: 'Note', onClick: () => qc.newNote() },
        { label: 'Topic', onClick: () => qc.open('topic') },
        { label: 'Subject', onClick: () => qc.open('subject') },
        'sep',
        { label: 'Generate questions with AI', onClick: () => qc.open('ai') },
      ]}
    />
  )
}

export const QUICK_ICONS = { question: HelpCircle, note: FileText, topic: FolderTree, subject: BookOpen, ai: Sparkles }

export const SUBJECT_COLORS = ['#2f5bea', '#0e9f6e', '#d97706', '#dc2626', '#7c3aed', '#db2777', '#0891b2', '#65748b']

export function SubjectForm({ onDone, onCancel, initial }: { onDone(s: { id: string }): void; onCancel(): void; initial?: Partial<SubjectNode> }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [color, setColor] = useState(initial?.color ?? SUBJECT_COLORS[0])
  const m = useMutation({
    mutationFn: () => (initial?.id ? import('@/api/client').then((c) => c.patch<{ id: string }>(`/subjects/${initial.id}`, { name, description, color })) : post<{ id: string }>('/subjects', { name, description, color })),
    onSuccess: (s) => { qc.invalidateQueries(); toast.ok(initial?.id ? 'Subject updated' : 'Subject created'); onDone(s) },
    onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed'),
  })
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (name.trim()) m.mutate() }}>
      <Field label="Name"><input className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required autoFocus placeholder="e.g. Finance & investing" /></Field>
      <Field label="Description"><textarea className="field" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={5000} /></Field>
      <div>
        <span className="label">Color</span>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Color">
          {SUBJECT_COLORS.map((c) => (
            <button type="button" key={c} role="radio" aria-checked={color === c} aria-label={c} onClick={() => setColor(c)} className="h-6 w-6 rounded-full border-2" style={{ background: c, borderColor: color === c ? 'rgb(var(--fg))' : 'transparent' }} />
          ))}
        </div>
      </div>
      <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onCancel}>Cancel</button><Button type="submit" className="btn-primary" loading={m.isPending}>{initial?.id ? 'Save' : 'Create subject'}</Button></div>
    </form>
  )
}

export function TopicForm({ defaults, onDone, onCancel }: { defaults?: Opts['topic']; onDone(id: string): void; onCancel(): void }) {
  const { data: tree = [] } = useTree()
  const qc = useQueryClient()
  const toast = useToast()
  const [name, setName] = useState('')
  const [subjectId, setSubjectId] = useState(defaults?.subject_id ?? '')
  const [parent, setParent] = useState<string[]>(defaults?.parent_id ? [defaults.parent_id] : [])
  const [chapterId, setChapterId] = useState(defaults?.chapter_id ?? '')
  const subject = tree.find((s) => s.id === subjectId)
  const chapters = subject?.courses.flatMap((c) => c.chapters.map((ch) => ({ id: ch.id, label: `${c.name} › ${ch.name}` }))) ?? []
  const m = useMutation({
    mutationFn: () => post<{ id: string }>('/topics', { name, subject_id: subjectId || undefined, parent_id: parent[0] ?? null, chapter_id: !parent[0] && chapterId ? chapterId : null }),
    onSuccess: (t) => { qc.invalidateQueries(); toast.ok('Topic created'); onDone(t.id) },
    onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed'),
  })
  const parentSet = parent.length > 0
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (name.trim() && (subjectId || parentSet)) m.mutate() }}>
      <Field label="Name"><input className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required autoFocus /></Field>
      <div>
        <span className="label">Parent topic (makes this a subtopic)</span>
        <TopicPicker single value={parent} onChange={setParent} subjectId={subjectId || null} placeholder="None — top-level topic" />
      </div>
      {!parentSet && (
        <>
          <Field label="Subject">
            <select className="field" value={subjectId} onChange={(e) => { setSubjectId(e.target.value); setChapterId('') }} required>
              <option value="">Choose a subject…</option>
              {tree.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          {chapters.length > 0 && (
            <Field label="Chapter (optional)">
              <select className="field" value={chapterId} onChange={(e) => setChapterId(e.target.value)}>
                <option value="">— directly under the subject —</option>
                {chapters.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </Field>
          )}
        </>
      )}
      <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onCancel}>Cancel</button><Button type="submit" className="btn-primary" loading={m.isPending}>Create topic</Button></div>
    </form>
  )
}
