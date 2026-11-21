import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ClipboardCheck, Copy, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '@/api/client'
import type { QuestionPage } from '@/api/types'
import { Page } from '@/components/Layout'
import { Badge, Button, ConfirmDialog, Empty, ErrorState, Field, Loading, Modal, PageHeader, Stat, Tabs } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { shortDate } from '@/lib/format'
import { tt, tl } from '@/i18n'

export interface ExamQ { id: string; question_id: string | null; position: number; points: number; grading: 'auto' | 'manual'; problem: string | null; type: string; title: string; content: string; options: { id: string; text: string; is_correct: boolean }[]; answer: string; explanation: string; tolerance: number }
export interface Exam {
  id: string; course_id: string; course_title: string; module_id: string | null; title: string; description: string; instructions: string; category: string; difficulty: string
  status: string; effective_status: string; question_count: number; total_points: number; time_limit_minutes: number | null; opens_at: string | null; closes_at: string | null
  max_attempts: number | null; grade_policy: string; allow_resume: boolean; allow_back: boolean; allow_change_answers: boolean; one_per_page: boolean; shuffle_questions: boolean; shuffle_options: boolean
  passing_score: number; partial_credit: boolean; show_score: boolean; show_pass_fail: boolean; show_answers: boolean; show_explanations: boolean; results_release: string; results_release_at: string | null
  results_released_at: string | null; release_partial: boolean; students: number; submissions: number; average: number | null; pass_rate: number | null; locked: boolean
  questions?: ExamQ[]; problems?: string[]
}
const TONE: Record<string, 'good' | 'warn' | 'bad' | 'neutral' | 'accent'> = { draft: 'neutral', published: 'accent', open: 'good', scheduled: 'warn', closed: 'bad', archived: 'neutral' }
const toLocal = (iso: string | null) => (iso ? new Date(iso).toISOString().slice(0, 16) : '')
const fromLocal = (v: string) => (v ? new Date(v).toISOString() : null)
const useErr = () => { const t = useToast(); return (e: unknown) => t.err(e instanceof Error ? e.message : tt("Failed")) }

// ------------------------------------------------------------------ list
export function ExamsList() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const err = useErr()
  const [creating, setCreating] = useState(false)
  const [rm, setRm] = useState<Exam | null>(null)
  const q = useQuery({ queryKey: ['teach-exams'], queryFn: () => get<Exam[]>('/teach/exams') })
  const refresh = () => qc.invalidateQueries({ queryKey: ['teach-exams'] })
  const dup = useMutation({ mutationFn: (e: Exam) => post<Exam>(`/teach/exams/${e.id}/duplicate`), onSuccess: (e) => nav(`/teach/exams/${e.id}`), onError: err })
  const remove = useMutation({ mutationFn: (e: Exam) => del(`/teach/exams/${e.id}`), onSuccess: () => { refresh(); setRm(null) }, onError: err })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  return (
    <Page>
      <PageHeader title={tt("Exams")} subtitle={tt("Timed and graded exams with attempts, manual grading and result publication.")} actions={<button className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={14} /> {tt("New exam")}</button>} />
      {q.data.length === 0 ? <div className="card"><Empty title={tt("No exams yet")} icon={<ClipboardCheck size={28} />} action={<button className="btn btn-primary" onClick={() => setCreating(true)}>{tt("New exam")}</button>}>{tt("Create an exam, add questions from your bank, set the rules and publish.")}</Empty></div> : (
        <div className="card overflow-x-auto"><table className="w-full min-w-[960px] text-sm"><thead><tr className="border-b border-line text-start text-xs text-muted">
          {[tt("Exam title"), tt("Course"), tt("Status"), tt("Questions"), tt("Duration"), tt("Students"), tt("Submissions"), tt("Average grade"), tt("Pass rate"), tt("Opens"), tt("Closes"), ''].map((h, i) => <th key={i} className="px-3 py-2 text-start font-medium">{h}</th>)}</tr></thead>
          <tbody>{q.data.map((e) => (
            <tr key={e.id} className="border-b border-line last:border-0 hover:bg-raised/50">
              <td className="px-3 py-2"><Link to={`/teach/exams/${e.id}`} dir="auto" className="font-medium hover:underline">{e.title}</Link></td>
              <td className="px-3 py-2 text-muted">{e.course_title}</td>
              <td className="px-3 py-2"><Badge tone={TONE[e.effective_status]}>{tl(e.effective_status)}</Badge></td>
              <td className="px-3 py-2 tabnum">{e.question_count} · {e.total_points} {tt("pts")}</td>
              <td className="px-3 py-2 tabnum">{e.time_limit_minutes ? `${e.time_limit_minutes} ${tt("min")}` : '—'}</td>
              <td className="px-3 py-2 tabnum">{e.students}</td><td className="px-3 py-2 tabnum">{e.submissions}</td>
              <td className="px-3 py-2 tabnum">{e.average !== null ? `${e.average}%` : '—'}</td><td className="px-3 py-2 tabnum">{e.pass_rate !== null ? `${e.pass_rate}%` : '—'}</td>
              <td className="px-3 py-2 text-xs text-muted">{e.opens_at ? shortDate(e.opens_at.slice(0, 10)) : '—'}</td><td className="px-3 py-2 text-xs text-muted">{e.closes_at ? shortDate(e.closes_at.slice(0, 10)) : '—'}</td>
              <td className="px-3 py-2"><div className="flex gap-1"><Link className="btn h-7" to={`/teach/exams/${e.id}/results`}>{tt("Results")}</Link>
                <button className="btn btn-ghost btn-icon h-7 w-7" aria-label={tt("Duplicate")} onClick={() => dup.mutate(e)}><Copy size={13} /></button>
                <button className="btn btn-ghost btn-icon h-7 w-7 text-bad" aria-label={tt("Delete")} onClick={() => setRm(e)}><Trash2 size={13} /></button></div></td>
            </tr>))}</tbody></table></div>
      )}
      {creating && <NewExam onClose={() => setCreating(false)} onCreated={(id) => nav(`/teach/exams/${id}`)} />}
      <ConfirmDialog open={!!rm} onClose={() => setRm(null)} busy={remove.isPending} onConfirm={() => rm && remove.mutate(rm)} title={tt("Delete “{title}”?", { title: rm?.title ?? '' })} message={tt("An exam with student attempts cannot be deleted — archive it instead.")} />
    </Page>
  )
}

function NewExam({ onClose, onCreated }: { onClose(): void; onCreated(id: string): void }) {
  const err = useErr()
  const courses = useQuery({ queryKey: ['teach-courses'], queryFn: () => get<{ id: string; title: string }[]>('/teach/courses') })
  const [title, setTitle] = useState('')
  const [course, setCourse] = useState('')
  const m = useMutation({ mutationFn: () => post<Exam>('/teach/exams', { title, course_id: course || courses.data?.[0]?.id }), onSuccess: (e) => onCreated(e.id), onError: err })
  return (
    <Modal open onClose={onClose} title={tt("New exam")}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (title.trim()) m.mutate() }}>
        <Field label={tt("Exam title")}><input className="field" dir="auto" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required autoFocus /></Field>
        <Field label={tt("Course")}><select className="field" value={course || courses.data?.[0]?.id || ''} onChange={(e) => setCourse(e.target.value)}>{courses.data?.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}</select></Field>
        <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onClose}>{tt("Cancel")}</button><Button type="submit" className="btn-primary" loading={m.isPending} disabled={!title.trim()}>{tt("Create")}</Button></div>
      </form>
    </Modal>
  )
}

// ------------------------------------------------------------------ editor (wizard)
type Tab = 'basics' | 'questions' | 'settings' | 'publish'

export function ExamEditor() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const err = useErr()
  const toast = useToast()
  const [tab, setTab] = useState<Tab>('basics')
  const [preview, setPreview] = useState(false)
  const q = useQuery({ queryKey: ['teach-exam', id], queryFn: () => get<Exam>(`/teach/exams/${id}`) })
  const sync = (e: Exam) => { qc.setQueryData(['teach-exam', id], e); qc.invalidateQueries({ queryKey: ['teach-exams'] }) }
  const save = useMutation({ mutationFn: (body: Record<string, unknown>) => patch<Exam>(`/teach/exams/${id}`, body), onSuccess: (e) => { sync(e); toast.ok(tt("Saved")) }, onError: err })
  const act = useMutation({ mutationFn: (action: string) => post<Exam>(`/teach/exams/${id}/status`, { action }), onSuccess: sync, onError: err })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const e = q.data
  return (
    <Page>
      <Link to="/teach/exams" className="mb-1 inline-block text-xs text-muted hover:text-fg">{tt("← Exams")}</Link>
      <PageHeader title={<span className="flex items-center gap-2"><span dir="auto">{e.title}</span><Badge tone={TONE[e.effective_status]}>{tl(e.effective_status)}</Badge></span>} subtitle={`${e.course_title} · ${e.question_count} ${tt("questions")} · ${e.total_points} ${tt("pts")}`}
        actions={<div className="flex flex-wrap gap-2"><button className="btn" onClick={() => setPreview(true)}>{tt("Preview as student")}</button>
          <Link className="btn" to={`/teach/exams/${id}/results`}>{tt("Results")}</Link>
          {e.status === 'published' ? <><button className="btn" onClick={() => act.mutate('unpublish')}>{tt("Unpublish")}</button><button className="btn" onClick={() => act.mutate('close')}>{tt("Close exam")}</button></> : e.status !== 'archived' && <button className="btn btn-primary" onClick={() => setTab('publish')}>{tt("Publish")}</button>}
          {e.status !== 'archived' && <button className="btn" onClick={() => act.mutate('archive')}>{tt("Archive")}</button>}</div>} />
      {e.locked && <p className="mb-3 rounded border border-warn/40 bg-warn/10 p-3 text-sm">{tt("The structure of this exam (questions, points, time, grading) is locked. Unpublish it (only possible without attempts) or duplicate it to change the structure.")}</p>}
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: 'basics', label: tt("1. Basic information") }, { id: 'questions', label: tt("2. Questions") }, { id: 'settings', label: tt("3. Settings") }, { id: 'publish', label: tt("Summary & publish") }]} />
      <div className="mt-4">
        {tab === 'basics' && <Basics e={e} onSave={(b) => save.mutate(b)} busy={save.isPending} />}
        {tab === 'questions' && <Questions e={e} onChange={sync} />}
        {tab === 'settings' && <Settings e={e} onSave={(b) => save.mutate(b)} busy={save.isPending} />}
        {tab === 'publish' && <Summary e={e} onPublish={() => act.mutate('publish')} busy={act.isPending} />}
      </div>
      {preview && <Preview id={id} onClose={() => setPreview(false)} />}
    </Page>
  )
}

function Basics({ e, onSave, busy }: { e: Exam; onSave(b: Record<string, unknown>): void; busy: boolean }) {
  const [f, setF] = useState({ title: e.title, description: e.description, instructions: e.instructions, category: e.category, difficulty: e.difficulty })
  return (
    <form className="card max-w-3xl space-y-3 p-4" onSubmit={(ev) => { ev.preventDefault(); onSave(f) }}>
      <Field label={tt("Exam title")}><input className="field" dir="auto" value={f.title} onChange={(x) => setF({ ...f, title: x.target.value })} required maxLength={200} /></Field>
      <Field label={tt("Description")}><textarea className="field" dir="auto" rows={3} value={f.description} onChange={(x) => setF({ ...f, description: x.target.value })} /></Field>
      <Field label={tt("Instructions")} hint={tt("Shown to the student before the exam starts.")}><textarea className="field" dir="auto" rows={4} value={f.instructions} onChange={(x) => setF({ ...f, instructions: x.target.value })} /></Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={tt("Exam category")}><input className="field" dir="auto" value={f.category} onChange={(x) => setF({ ...f, category: x.target.value })} maxLength={80} /></Field>
        <Field label={tt("Difficulty")}><select className="field" value={f.difficulty} onChange={(x) => setF({ ...f, difficulty: x.target.value })}><option value="easy">{tt("Easy")}</option><option value="medium">{tt("Medium")}</option><option value="hard">{tt("Hard")}</option></select></Field>
      </div>
      <p className="text-xs text-muted">{tt("Course")}: {e.course_title}</p>
      <div className="flex justify-end"><Button type="submit" className="btn-primary" loading={busy}>{tt("Save draft")}</Button></div>
    </form>
  )
}

function Questions({ e, onChange }: { e: Exam; onChange(e: Exam): void }) {
  const err = useErr()
  const [picking, setPicking] = useState(false)
  const [custom, setCustom] = useState(false)
  const qs = e.questions ?? []
  const run = useMutation({ mutationFn: (fn: () => Promise<Exam | void>) => fn(), onSuccess: (r) => { if (r) onChange(r) }, onError: err })
  const reload = () => get<Exam>(`/teach/exams/${e.id}`)
  const move = (i: number, d: number) => { const ids = qs.map((x) => x.id); [ids[i], ids[i + d]] = [ids[i + d], ids[i]]; run.mutate(async () => { await post(`/teach/exams/${e.id}/questions/reorder`, { ids }); return reload() }) }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn btn-primary" disabled={e.locked} onClick={() => setPicking(true)}><Plus size={14} /> {tt("Add from question bank")}</button>
        <button className="btn" disabled={e.locked} onClick={() => setCustom(true)}>{tt("Create exam-specific question")}</button>
        <span className="ms-auto text-sm text-muted tabnum">{tt("Total points")}: <b>{e.total_points}</b></span>
      </div>
      {qs.length === 0 ? <div className="card"><Empty title={tt("No questions yet")}>{tt("Add questions from your bank or write exam-only questions.")}</Empty></div> : (
        <ol className="space-y-2">{qs.map((x, i) => (
          <li key={x.id} className="card flex flex-wrap items-center gap-3 p-3">
            <span className="w-6 text-sm text-muted tabnum">{i + 1}</span>
            <div className="min-w-0 flex-1"><div dir="auto" className="truncate text-sm font-medium">{x.title || x.content.slice(0, 90)}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted"><Badge>{tl(x.type)}</Badge>{!x.question_id && <Badge tone="accent">{tt("Exam only")}</Badge>}{x.grading === 'manual' ? <Badge tone="warn">{tt("Manual grading")}</Badge> : <Badge tone="good">{tt("Auto-graded")}</Badge>}{x.problem && <span className="text-bad">{x.problem}</span>}</div></div>
            <label className="flex items-center gap-1 text-xs text-muted">{tt("Points")}<input type="number" min={0.5} step={0.5} className="field h-8 w-20 py-0" defaultValue={x.points} disabled={e.locked} onBlur={(ev) => Number(ev.target.value) !== x.points && run.mutate(async () => patch<Exam>(`/teach/exam-questions/${x.id}`, { points: Number(ev.target.value) }))} /></label>
            <select className="field h-8 w-auto py-0 text-xs" value={x.grading} disabled={e.locked} aria-label={tt("Grading")} onChange={(ev) => run.mutate(async () => patch<Exam>(`/teach/exam-questions/${x.id}`, { grading: ev.target.value }))}><option value="auto">{tt("Auto-graded")}</option><option value="manual">{tt("Manual grading")}</option></select>
            <div className="flex gap-1">
              <button className="btn btn-ghost btn-icon h-7 w-7" disabled={e.locked || i === 0} aria-label={tt("Move up")} onClick={() => move(i, -1)}><ArrowUp size={13} /></button>
              <button className="btn btn-ghost btn-icon h-7 w-7" disabled={e.locked || i === qs.length - 1} aria-label={tt("Move down")} onClick={() => move(i, 1)}><ArrowDown size={13} /></button>
              {x.question_id && <button className="btn btn-ghost btn-icon h-7 w-7" disabled={e.locked} aria-label={tt("Refresh from bank")} title={tt("Refresh from bank")} onClick={() => run.mutate(async () => patch<Exam>(`/teach/exam-questions/${x.id}`, { refresh: true }))}><RefreshCw size={13} /></button>}
              <button className="btn btn-ghost btn-icon h-7 w-7 text-bad" disabled={e.locked} aria-label={tt("Remove question")} onClick={() => run.mutate(async () => { await del(`/teach/exam-questions/${x.id}`); return reload() })}><Trash2 size={13} /></button>
            </div>
          </li>))}</ol>
      )}
      {picking && <BankPicker e={e} onClose={() => setPicking(false)} onAdded={(x) => { onChange(x); setPicking(false) }} />}
      {custom && <CustomQ e={e} onClose={() => setCustom(false)} onAdded={(x) => { onChange(x); setCustom(false) }} />}
    </div>
  )
}

function BankPicker({ e, onClose, onAdded }: { e: Exam; onClose(): void; onAdded(e: Exam): void }) {
  const err = useErr()
  const [q, setQ] = useState('')
  const [difficulty, setDifficulty] = useState('')
  const [tag, setTag] = useState('')
  const [sel, setSel] = useState<string[]>([])
  const [points, setPoints] = useState(1)
  const have = new Set((e.questions ?? []).map((x) => x.question_id))
  const res = useQuery({ queryKey: ['exam-bank', q, difficulty, tag], queryFn: () => get<QuestionPage>('/questions', { q, difficulty: difficulty || undefined, tag: tag ? [tag] : undefined, page_size: 50 }) })
  const add = useMutation({ mutationFn: () => post<Exam>(`/teach/exams/${e.id}/questions`, { question_ids: sel, points }), onSuccess: onAdded, onError: err })
  return (
    <Modal open onClose={onClose} wide title={tt("Add questions from your bank")} footer={<><span className="me-auto text-sm text-muted">{sel.length} {tt("selected")}</span><button className="btn" onClick={onClose}>{tt("Cancel")}</button><Button className="btn-primary" disabled={!sel.length} loading={add.isPending} onClick={() => add.mutate()}>{tt("Add")}</Button></>}>
      <div className="mb-3 flex flex-wrap gap-2">
        <input className="field w-56" placeholder={tt("Search questions…")} value={q} onChange={(x) => setQ(x.target.value)} />
        <select className="field w-auto" value={difficulty} onChange={(x) => setDifficulty(x.target.value)} aria-label={tt("Difficulty")}><option value="">{tt("All")}</option><option value="easy">{tt("Easy")}</option><option value="medium">{tt("Medium")}</option><option value="hard">{tt("Hard")}</option></select>
        <input className="field w-40" placeholder={tt("Tag")} value={tag} onChange={(x) => setTag(x.target.value)} />
        <label className="flex items-center gap-1 text-sm text-muted">{tt("Points")}<input type="number" min={0.5} step={0.5} className="field h-9 w-20" value={points} onChange={(x) => setPoints(Number(x.target.value) || 1)} /></label>
      </div>
      <ul className="max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line">
        {res.data?.items.length === 0 && <li className="px-3 py-4 text-sm text-muted">{tt("No questions found")}</li>}
        {res.data?.items.map((x) => (
          <li key={x.id}><label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-raised/60"><input type="checkbox" disabled={have.has(x.id)} checked={sel.includes(x.id) || have.has(x.id)} onChange={(ev) => setSel(ev.target.checked ? [...sel, x.id] : sel.filter((i) => i !== x.id))} />
            <span dir="auto" className="min-w-0 flex-1 truncate">{x.title || x.content.slice(0, 90)}</span><Badge>{tl(x.question_type)}</Badge><Badge>{tl(x.difficulty)}</Badge></label></li>))}
      </ul>
    </Modal>
  )
}

function CustomQ({ e, onClose, onAdded }: { e: Exam; onClose(): void; onAdded(e: Exam): void }) {
  const err = useErr()
  const [f, setF] = useState({ type: 'multiple_choice', content: '', answer: '', explanation: '', tolerance: 0, points: 1 })
  const [opts, setOpts] = useState([{ text: '', is_correct: true }, { text: '', is_correct: false }])
  const hasOptions = f.type === 'multiple_choice' || f.type === 'true_false'
  const add = useMutation({ mutationFn: () => post<Exam>(`/teach/exams/${e.id}/questions/custom`, { ...f, options: f.type === 'multiple_choice' ? opts.filter((o) => o.text.trim()) : [] }), onSuccess: onAdded, onError: err })
  return (
    <Modal open onClose={onClose} wide title={tt("Create exam-specific question")} footer={<><button className="btn" onClick={onClose}>{tt("Cancel")}</button><Button className="btn-primary" disabled={!f.content.trim()} loading={add.isPending} onClick={() => add.mutate()}>{tt("Add")}</Button></>}>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={tt("Type")}><select className="field" value={f.type} onChange={(x) => setF({ ...f, type: x.target.value })}>{['multiple_choice', 'true_false', 'calculation', 'short_answer', 'open_ended', 'case_study'].map((t) => <option key={t} value={t}>{tl(t)}</option>)}</select></Field>
          <Field label={tt("Points")}><input type="number" min={0.5} step={0.5} className="field" value={f.points} onChange={(x) => setF({ ...f, points: Number(x.target.value) || 1 })} /></Field>
          {f.type === 'calculation' && <Field label={tt("Numeric tolerance")}><input type="number" min={0} step="any" className="field" dir="ltr" value={f.tolerance} onChange={(x) => setF({ ...f, tolerance: Number(x.target.value) || 0 })} /></Field>}
        </div>
        <Field label={tt("Question text")}><textarea className="field" dir="auto" rows={3} value={f.content} onChange={(x) => setF({ ...f, content: x.target.value })} /></Field>
        {f.type === 'multiple_choice' && <div className="space-y-2"><span className="label">{tt("Answer options")}</span>{opts.map((o, i) => (
          <div key={i} className="flex items-center gap-2"><input type="checkbox" checked={o.is_correct} aria-label={tt("Correct")} onChange={(x) => setOpts(opts.map((p, j) => (j === i ? { ...p, is_correct: x.target.checked } : p)))} />
            <input className="field" dir="auto" placeholder={tt("Option {i}", { i: i + 1 })} value={o.text} onChange={(x) => setOpts(opts.map((p, j) => (j === i ? { ...p, text: x.target.value } : p)))} />
            <button type="button" className="btn btn-ghost btn-icon" aria-label={tt("Remove option")} onClick={() => setOpts(opts.filter((_, j) => j !== i))}><Trash2 size={13} /></button></div>))}
          <button type="button" className="btn" onClick={() => setOpts([...opts, { text: '', is_correct: false }])}>{tt("Add option")}</button></div>}
        {f.type === 'true_false' && <p className="text-xs text-muted">{tt("Choose the correct statement after adding the question (set it in the options).")}</p>}
        {!hasOptions && <Field label={f.type === 'calculation' ? tt("Correct number") : tt("Expected answer")}><textarea className="field" dir="auto" rows={2} value={f.answer} onChange={(x) => setF({ ...f, answer: x.target.value })} /></Field>}
        <Field label={tt("Explanation")}><textarea className="field" dir="auto" rows={2} value={f.explanation} onChange={(x) => setF({ ...f, explanation: x.target.value })} /></Field>
      </div>
    </Modal>
  )
}

function Settings({ e, onSave, busy }: { e: Exam; onSave(b: Record<string, unknown>): void; busy: boolean }) {
  const [f, setF] = useState<Record<string, any>>({ ...e }) // eslint-disable-line @typescript-eslint/no-explicit-any
  const set = (k: string, v: unknown) => setF({ ...f, [k]: v })
  const lock = e.locked
  const chk = (k: string, label: string, locked = false) => <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={locked && lock} checked={!!f[k]} onChange={(x) => set(k, x.target.checked)} /> {label}</label>
  const num = (k: string, v: string) => (v === '' ? null : Number(v))
  const body = () => ({
    time_limit_minutes: f.time_limit_minutes, opens_at: f.opens_at, closes_at: f.closes_at, max_attempts: f.max_attempts, grade_policy: f.grade_policy, allow_resume: f.allow_resume,
    allow_back: f.allow_back, allow_change_answers: f.allow_change_answers, one_per_page: f.one_per_page, shuffle_questions: f.shuffle_questions, shuffle_options: f.shuffle_options,
    passing_score: f.passing_score, partial_credit: f.partial_credit, show_score: f.show_score, show_pass_fail: f.show_pass_fail, show_answers: f.show_answers, show_explanations: f.show_explanations,
    results_release: f.results_release, results_release_at: f.results_release === 'scheduled' ? f.results_release_at : null, release_partial: f.release_partial,
  })
  const sect = (t: string) => <h3 className="h-section mb-2 mt-1">{t}</h3>
  return (
    <form className="grid max-w-5xl gap-4 lg:grid-cols-2" onSubmit={(ev) => { ev.preventDefault(); onSave(body()) }}>
      <div className="card space-y-3 p-4">{sect(tt("Time"))}
        <Field label={tt("Time limit (minutes, optional)")}><input type="number" min={1} className="field" dir="ltr" disabled={lock} value={f.time_limit_minutes ?? ''} onChange={(x) => set('time_limit_minutes', num('t', x.target.value))} /></Field>
        <Field label={tt("Opens at (optional)")}><input type="datetime-local" className="field" dir="ltr" value={toLocal(f.opens_at)} onChange={(x) => set('opens_at', fromLocal(x.target.value))} /></Field>
        <Field label={tt("Closes at (optional)")} hint={tt("Nobody can start after this time and running attempts end by then.")}><input type="datetime-local" className="field" dir="ltr" value={toLocal(f.closes_at)} onChange={(x) => set('closes_at', fromLocal(x.target.value))} /></Field>
        {sect(tt("Attempts"))}
        <Field label={tt("Attempts allowed (empty = unlimited)")}><input type="number" min={1} className="field" dir="ltr" disabled={lock} value={f.max_attempts ?? ''} onChange={(x) => set('max_attempts', num('a', x.target.value))} /></Field>
        <Field label={tt("Which grade counts")}><select className="field" value={f.grade_policy} onChange={(x) => set('grade_policy', x.target.value)}><option value="highest">{tt("Highest grade")}</option><option value="latest">{tt("Latest grade")}</option></select></Field>
        {chk('allow_resume', tt("Students can resume an interrupted attempt"), true)}
      </div>
      <div className="card space-y-3 p-4">{sect(tt("Navigation & presentation"))}
        {chk('one_per_page', tt("One question at a time"), true)}{chk('allow_back', tt("Allow going back to previous questions"), true)}{chk('allow_change_answers', tt("Allow changing answers before submission"), true)}
        {chk('shuffle_questions', tt("Random question order"), true)}{chk('shuffle_options', tt("Random answer order"), true)}
        {sect(tt("Grading"))}
        <Field label={tt("Passing score (%)")}><input type="number" min={0} max={100} className="field" dir="ltr" disabled={lock} value={f.passing_score} onChange={(x) => set('passing_score', Number(x.target.value))} /></Field>
        {chk('partial_credit', tt("Partial credit for multi-select questions"), true)}
      </div>
      <div className="card space-y-3 p-4 lg:col-span-2">{sect(tt("Results"))}
        <div className="grid gap-2 sm:grid-cols-2">{chk('show_score', tt("Show score"))}{chk('show_pass_fail', tt("Show pass / fail"))}{chk('show_answers', tt("Show correct answers"))}{chk('show_explanations', tt("Show explanations"))}</div>
        <Field label={tt("Result release")}><select className="field" value={f.results_release} onChange={(x) => set('results_release', x.target.value)}><option value="immediate">{tt("Immediately after grading")}</option><option value="manual">{tt("Only after I publish them")}</option><option value="scheduled">{tt("On a scheduled date")}</option></select></Field>
        {f.results_release === 'scheduled' && <Field label={tt("Release date")}><input type="datetime-local" className="field" dir="ltr" value={toLocal(f.results_release_at)} onChange={(x) => set('results_release_at', fromLocal(x.target.value))} /></Field>}
        {chk('release_partial', tt("Publish results even while manual grading is incomplete"))}
        <div className="flex justify-end"><Button type="submit" className="btn-primary" loading={busy}>{tt("Save settings")}</Button></div>
      </div>
    </form>
  )
}

function Summary({ e, onPublish, busy }: { e: Exam; onPublish(): void; busy: boolean }) {
  const rows: [string, string][] = [
    [tt("Questions"), String(e.question_count)], [tt("Total points"), String(e.total_points)], [tt("Time limit"), e.time_limit_minutes ? `${e.time_limit_minutes} ${tt("min")}` : tt("No limit")],
    [tt("Passing score"), `${e.passing_score}%`], [tt("Attempts allowed"), e.max_attempts ? String(e.max_attempts) : tt("Unlimited")], [tt("Opens"), e.opens_at ? new Date(e.opens_at).toLocaleString('he-IL') : tt("Immediately")],
    [tt("Closes"), e.closes_at ? new Date(e.closes_at).toLocaleString('he-IL') : tt("Never")], [tt("Result release"), e.results_release === 'immediate' ? tt("Immediately after grading") : e.results_release === 'manual' ? tt("Only after I publish them") : tt("On a scheduled date")],
  ]
  const warn = [...(e.problems ?? []), ...(!e.time_limit_minutes ? [tt("No time limit is set")] : []), ...(!e.closes_at ? [tt("No closing date is set")] : [])]
  return (
    <div className="card max-w-3xl space-y-4 p-4">
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">{rows.map(([k, v]) => <div key={k} className="flex justify-between border-b border-line py-1 text-sm"><dt className="text-muted">{k}</dt><dd className="font-medium tabnum">{v}</dd></div>)}</dl>
      {warn.length > 0 && <ul className="space-y-1 rounded border border-warn/40 bg-warn/10 p-3 text-sm">{warn.map((w) => <li key={w}>⚠ {w}</li>)}</ul>}
      {(e.status === 'draft' || e.status === 'closed') && <div className="flex justify-end"><Button className="btn-primary" loading={busy} disabled={(e.problems ?? []).length > 0} onClick={onPublish}>{tt("Publish exam")}</Button></div>}
      {e.status === 'published' && <p className="text-sm text-good">{tt("This exam is published.")}</p>}
    </div>
  )
}

interface PreviewData { title: string; instructions: string; description: string; time_limit_minutes: number | null; passing_score: number; total_points: number; questions: { id: string; type: string; title: string; content: string; points: number; options: { id: string; text: string }[] }[] }
function Preview({ id, onClose }: { id: string; onClose(): void }) {
  const q = useQuery({ queryKey: ['exam-preview', id], queryFn: () => get<PreviewData>(`/teach/exams/${id}/preview`), staleTime: 0 })
  return (
    <Modal open onClose={onClose} wide title={tt("Student preview")}>
      {!q.data ? <Loading /> : <div className="space-y-4">
        <div><h2 dir="auto" className="text-lg font-semibold">{q.data.title}</h2><p className="text-sm text-muted">{q.data.time_limit_minutes ? `${q.data.time_limit_minutes} ${tt("min")} · ` : ''}{tt("Passing score")} {q.data.passing_score}% · {q.data.total_points} {tt("pts")}</p>{q.data.instructions && <p dir="auto" className="mt-2 whitespace-pre-wrap text-sm">{q.data.instructions}</p>}</div>
        {q.data.questions.map((x, i) => <div key={x.id} className="rounded-lg border border-line p-3"><div className="mb-2 text-xs text-muted">{tt("Question")} {i + 1} · {x.points} {tt("pts")}</div><p dir="auto" className="whitespace-pre-wrap text-sm">{x.content}</p>
          {x.options.map((o) => <div key={o.id} dir="auto" className="mt-1.5 rounded border border-line px-3 py-1.5 text-sm">○ {o.text}</div>)}</div>)}
      </div>}
    </Modal>
  )
}

// ------------------------------------------------------------------ results & grading
interface Row { id: string; student_name: string; student_email: string; attempt_no: number; status: string; auto_submitted: boolean; started_at: string; submitted_at: string | null; score: number | null; max_score: number | null; percent: number | null; passed: boolean | null; pending_manual: number; released: boolean }
interface Stats { enrolled: number; started: number; in_progress: number; submitted: number; not_started: number; average: number | null; median: number | null; highest: number | null; lowest: number | null; pass_rate: number | null; questions: { id: string; title: string; n: number; percent_correct: number; percent_incorrect: number; percent_unanswered: number; difficult: boolean }[] }
const ST_TONE: Record<string, 'good' | 'warn' | 'bad' | 'neutral' | 'accent'> = { in_progress: 'warn', submitted: 'accent', auto_submitted: 'accent', graded: 'good', cancelled: 'bad' }

export function ExamResults() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const err = useErr()
  const toast = useToast()
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState<'date' | 'score'>('date')
  const exam = useQuery({ queryKey: ['teach-exam', id], queryFn: () => get<Exam>(`/teach/exams/${id}`) })
  const stats = useQuery({ queryKey: ['exam-stats', id], queryFn: () => get<Stats>(`/teach/exams/${id}/stats`) })
  const rows = useQuery({ queryKey: ['exam-attempts', id], queryFn: () => get<Row[]>(`/teach/exams/${id}/attempts`) })
  const release = useMutation({ mutationFn: () => post(`/teach/exams/${id}/release-results`), onSuccess: () => { qc.invalidateQueries({ queryKey: ['teach-exam', id] }); toast.ok(tt("Results published")) }, onError: err })
  if (rows.isLoading || stats.isLoading || exam.isLoading) return <Loading />
  if (!rows.data || !stats.data || !exam.data) return <ErrorState error={rows.error ?? stats.error} retry={rows.refetch} />
  const s = stats.data
  const list = rows.data.filter((r) => !filter || r.status === filter).sort((a, b) => (sort === 'score' ? (b.percent ?? -1) - (a.percent ?? -1) : (b.started_at > a.started_at ? 1 : -1)))
  return (
    <Page>
      <Link to={`/teach/exams/${id}`} className="mb-1 inline-block text-xs text-muted hover:text-fg">{tt("← Exam")}</Link>
      <PageHeader title={`${tt("Results")}: ${exam.data.title}`} actions={exam.data.results_release === 'manual' && <button className="btn btn-primary" onClick={() => release.mutate()}>{exam.data.results_released_at ? tt("Results published") : tt("Publish results to students")}</button>} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={tt("Enrolled")} value={s.enrolled} /><Stat label={tt("Started")} value={s.started} hint={`${s.in_progress} ${tt("in progress")}`} /><Stat label={tt("Submitted")} value={s.submitted} hint={`${s.not_started} ${tt("not started")}`} /><Stat label={tt("Pass rate")} value={s.pass_rate !== null ? `${s.pass_rate}%` : '—'} />
        <Stat label={tt("Average grade")} value={s.average !== null ? `${s.average}%` : '—'} /><Stat label={tt("Median")} value={s.median !== null ? `${s.median}%` : '—'} /><Stat label={tt("Highest")} value={s.highest !== null ? `${s.highest}%` : '—'} /><Stat label={tt("Lowest")} value={s.lowest !== null ? `${s.lowest}%` : '—'} />
      </div>
      <h2 className="h-section mb-2">{tt("Attempts")}</h2>
      <div className="mb-2 flex gap-2"><select className="field w-auto" value={filter} onChange={(x) => setFilter(x.target.value)} aria-label={tt("Filter by status")}><option value="">{tt("All statuses")}</option>{['in_progress', 'submitted', 'auto_submitted', 'graded', 'cancelled'].map((x) => <option key={x} value={x}>{tl(x)}</option>)}</select>
        <select className="field w-auto" value={sort} onChange={(x) => setSort(x.target.value as 'date' | 'score')} aria-label={tt("Sort")}><option value="date">{tt("Newest")}</option><option value="score">{tt("Highest grade")}</option></select></div>
      {list.length === 0 ? <div className="card"><Empty title={tt("No attempts yet")} /></div> : <div className="card overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead><tr className="border-b border-line text-xs text-muted">{[tt("Student"), tt("Attempt"), tt("Status"), tt("Submitted"), tt("Score"), tt("Result"), ''].map((h, i) => <th key={i} className="px-3 py-2 text-start font-medium">{h}</th>)}</tr></thead>
        <tbody>{list.map((r) => <tr key={r.id} className="border-b border-line last:border-0">
          <td className="px-3 py-2"><div className="font-medium">{r.student_name}</div><div className="text-xs text-muted" dir="ltr">{r.student_email}</div></td><td className="px-3 py-2 tabnum">{r.attempt_no}</td>
          <td className="px-3 py-2"><Badge tone={ST_TONE[r.status]}>{tl(r.status)}</Badge>{r.auto_submitted && <span className="ms-1 text-xs text-muted">{tt("(auto)")}</span>}{r.pending_manual > 0 && <Badge tone="warn" className="ms-1">{tt("{n} to grade", { n: r.pending_manual })}</Badge>}</td>
          <td className="px-3 py-2 text-xs text-muted">{r.submitted_at ? new Date(r.submitted_at).toLocaleString('he-IL') : '—'}</td>
          <td className="px-3 py-2 tabnum">{r.score !== null ? `${r.score}/${r.max_score} (${r.percent}%)` : '—'}</td>
          <td className="px-3 py-2">{r.passed === null ? '—' : r.passed ? <Badge tone="good">{tt("Passed")}</Badge> : <Badge tone="bad">{tt("Failed")}</Badge>}</td>
          <td className="px-3 py-2 text-end"><Link className="btn h-7" to={`/teach/exam-attempts/${r.id}`}>{r.pending_manual ? tt("Grade") : tt("Review")}</Link></td></tr>)}</tbody></table></div>}
      <h2 className="h-section mb-2 mt-6">{tt("Question performance")}</h2>
      {s.questions.length === 0 ? <p className="text-sm text-muted">{tt("Statistics appear after the first submission.")}</p> : <div className="card overflow-x-auto"><table className="w-full min-w-[560px] text-sm"><thead><tr className="border-b border-line text-xs text-muted">{[tt("Question"), tt("Correct"), tt("Incorrect"), tt("Unanswered"), ''].map((h, i) => <th key={i} className="px-3 py-2 text-start font-medium">{h}</th>)}</tr></thead>
        <tbody>{s.questions.map((x) => <tr key={x.id} className="border-b border-line last:border-0"><td dir="auto" className="max-w-xs truncate px-3 py-2">{x.title}</td><td className="px-3 py-2 tabnum">{x.percent_correct}%</td><td className="px-3 py-2 tabnum">{x.percent_incorrect}%</td><td className="px-3 py-2 tabnum">{x.percent_unanswered}%</td><td className="px-3 py-2">{x.difficult && <Badge tone="bad">{tt("Difficult")}</Badge>}</td></tr>)}</tbody></table></div>}
    </Page>
  )
}

interface RevQ { id: string; number: number; type: string; content: string; title: string; points: number; grading: string; options: { id: string; text: string; is_correct: boolean }[]; expected_answer: string; explanation: string; answer: { option_ids?: string[]; text?: string } | null; flagged: boolean; grading_status: string; points_awarded: number | null; is_correct: boolean | null; feedback: string }
interface Review extends Row { exam_id: string; exam_title: string; questions: RevQ[] }

export function ExamAttemptGrade() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const err = useErr()
  const toast = useToast()
  const q = useQuery({ queryKey: ['exam-attempt', id], queryFn: () => get<Review>(`/teach/exam-attempts/${id}`) })
  const [draft, setDraft] = useState<Record<string, { points: string; feedback: string }>>({})
  const refresh = () => { qc.invalidateQueries({ queryKey: ['exam-attempt', id] }); qc.invalidateQueries({ queryKey: ['exam-attempts'] }); qc.invalidateQueries({ queryKey: ['exam-stats'] }) }
  const save = useMutation({ mutationFn: () => post(`/teach/exam-attempts/${id}/grade`, { grades: Object.entries(draft).filter(([, v]) => v.points !== '').map(([k, v]) => ({ exam_question_id: k, points: Number(v.points), feedback: v.feedback })) }), onSuccess: () => { setDraft({}); refresh(); toast.ok(tt("Grades saved")) }, onError: err })
  const rel = useMutation({ mutationFn: () => post(`/teach/exam-attempts/${id}/release`), onSuccess: () => { refresh(); toast.ok(tt("Result released to the student")) }, onError: err })
  const cancel = useMutation({ mutationFn: () => post(`/teach/exam-attempts/${id}/cancel`), onSuccess: refresh, onError: err })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const a = q.data
  const val = (x: RevQ) => draft[x.id] ?? { points: x.points_awarded !== null && x.grading_status === 'graded' ? String(x.points_awarded) : '', feedback: x.feedback }
  return (
    <Page>
      <Link to={`/teach/exams/${a.exam_id}/results`} className="mb-1 inline-block text-xs text-muted hover:text-fg">{tt("← Results")}</Link>
      <PageHeader title={`${a.student_name} — ${a.exam_title}`} subtitle={`${tt("Attempt")} ${a.attempt_no} · ${tl(a.status)}${a.score !== null ? ` · ${a.score}/${a.max_score} (${a.percent}%)` : ''}`}
        actions={<div className="flex gap-2">{a.status !== 'in_progress' && a.status !== 'cancelled' && <button className="btn" onClick={() => rel.mutate()}>{tt("Release result")}</button>}{a.status !== 'cancelled' && <button className="btn btn-danger" onClick={() => confirm(tt("Void this attempt? It stops counting toward the attempt limit.")) && cancel.mutate()}>{tt("Void attempt")}</button>}</div>} />
      <div className="space-y-3">{a.questions.map((x) => {
        const v = val(x)
        const chosen = new Set(x.answer?.option_ids ?? [])
        return (
          <section key={x.id} className="card p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted"><span>{tt("Question")} {x.number}</span><span>· {x.points} {tt("pts")}</span>{x.grading === 'manual' && <Badge tone={x.grading_status === 'pending' ? 'warn' : 'good'}>{x.grading_status === 'pending' ? tt("Pending grading") : tt("Graded")}</Badge>}{x.flagged && <Badge>{tt("Flagged")}</Badge>}</div>
            <p dir="auto" className="whitespace-pre-wrap text-sm font-medium">{x.content}</p>
            {x.options.length > 0 ? <ul className="mt-2 space-y-1">{x.options.map((o) => <li key={o.id} dir="auto" className={`rounded border px-3 py-1.5 text-sm ${o.is_correct ? 'border-good/50 bg-good/10' : chosen.has(o.id) ? 'border-bad/50 bg-bad/10' : 'border-line'}`}>{chosen.has(o.id) ? '● ' : '○ '}{o.text}{o.is_correct ? ' ✓' : ''}</li>)}</ul>
              : <div className="mt-2 space-y-2"><div><span className="label">{tt("Student answer")}</span><p dir="auto" className="whitespace-pre-wrap rounded border border-line bg-raised/50 p-2 text-sm">{x.answer?.text || <span className="text-muted">{tt("No answer")}</span>}</p></div>{x.expected_answer && <div><span className="label">{tt("Expected answer")}</span><p dir="auto" className="whitespace-pre-wrap text-sm text-muted">{x.expected_answer}</p></div>}</div>}
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <Field label={`${tt("Points")} (0–${x.points})`}><input type="number" min={0} max={x.points} step={0.5} className="field w-28" dir="ltr" value={v.points} placeholder={x.points_awarded !== null ? String(x.points_awarded) : ''} onChange={(ev) => setDraft({ ...draft, [x.id]: { ...v, points: ev.target.value } })} /></Field>
              <div className="min-w-56 flex-1"><Field label={tt("Feedback")}><input className="field" dir="auto" value={v.feedback} onChange={(ev) => setDraft({ ...draft, [x.id]: { ...v, feedback: ev.target.value } })} /></Field></div>
              {x.points_awarded !== null && x.grading_status !== 'pending' && <span className="pb-2 text-sm tabnum text-muted">{tt("Awarded")}: {x.points_awarded}</span>}
            </div>
          </section>)
      })}</div>
      <div className="sticky bottom-0 mt-4 flex justify-end border-t border-line bg-bg/90 py-3 backdrop-blur"><Button className="btn-primary" loading={save.isPending} disabled={!Object.values(draft).some((d) => d.points !== '')} onClick={() => save.mutate()}>{tt("Save grades")}</Button></div>
    </Page>
  )
}

/** Exam grades block for the student profile (teacher view). */
export function StudentExamGrades({ studentId }: { studentId: string }) {
  const q = useQuery({ queryKey: ['student-exams', studentId], queryFn: () => get<(Row & { exam_id: string; exam_title: string })[]>(`/teach/students/${studentId}/exams`) })
  if (!q.data) return null
  return (
    <>
      <h2 className="h-section mb-2 mt-6">{tt("Exam grades")}</h2>
      {q.data.length === 0 ? <p className="text-sm text-muted">{tt("No exam attempts yet.")}</p> : <div className="card overflow-x-auto"><table className="w-full min-w-[560px] text-sm"><thead><tr className="border-b border-line text-xs text-muted">{[tt("Exam"), tt("Attempt"), tt("Status"), tt("Score"), tt("Time taken")].map((h) => <th key={h} className="px-3 py-2 text-start font-medium">{h}</th>)}</tr></thead>
        <tbody>{q.data.map((r) => <tr key={r.id} className="border-b border-line last:border-0"><td className="px-3 py-2"><Link className="font-medium hover:underline" to={`/teach/exam-attempts/${r.id}`}>{r.exam_title}</Link></td><td className="px-3 py-2 tabnum">{r.attempt_no}</td><td className="px-3 py-2"><Badge tone={ST_TONE[r.status]}>{tl(r.status)}</Badge></td><td className="px-3 py-2 tabnum">{r.score !== null ? `${r.score}/${r.max_score} (${r.percent}%)` : '—'}</td><td className="px-3 py-2 tabnum">{r.submitted_at ? `${Math.max(1, Math.round((+new Date(r.submitted_at) - +new Date(r.started_at)) / 60000))} ${tt("min")}` : '—'}</td></tr>)}</tbody></table></div>}
    </>
  )
}
