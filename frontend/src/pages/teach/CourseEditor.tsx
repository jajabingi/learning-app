import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Eye, Plus, Trash2 } from 'lucide-react'
import { api, del, get, patch, post } from '@/api/client'
import type { CourseDetail, LessonDetail, ModuleNode } from '@/api/types'
import { MarkdownEditor } from '@/components/MarkdownEditor'
import { SortableList } from '@/components/lms/SortableList'
import { Page } from '@/components/Layout'
import { Badge, Button, ConfirmDialog, ErrorState, Field, Loading, Menu, Tabs } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { STATUS_TONE } from './Courses'
import { CourseStudents } from './Students'
import { CoursePractice } from './CoursePractice'
import { AiStudio } from '@/components/AiStudio'

type Tab = 'curriculum' | 'practice' | 'details' | 'access' | 'students'

export default function CourseEditor() {
  const { id = '' } = useParams()
  const [tab, setTab] = useState<Tab>('curriculum')
  const [confirm, setConfirm] = useState<'delete' | null>(null)
  const [studio, setStudio] = useState(false)
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['teach-course', id], queryFn: () => get<CourseDetail>(`/teach/courses/${id}`) })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['teach-course', id] }); qc.invalidateQueries({ queryKey: ['teach-courses'] }); qc.invalidateQueries({ queryKey: ['teach-dashboard'] }) }
  const err = (e: unknown) => toast.err(e instanceof Error ? e.message : 'Failed')
  const status = useMutation({ mutationFn: (s: string) => post(`/teach/courses/${id}/status`, { status: s }), onSuccess: (_r, s) => { refresh(); toast.ok(s === 'published' ? 'Course published' : s === 'draft' ? 'Course unpublished' : 'Course archived') }, onError: err })
  const remove = useMutation({ mutationFn: () => del(`/teach/courses/${id}`), onSuccess: () => { qc.invalidateQueries(); nav('/teach/courses') }, onError: (e) => { setConfirm(null); err(e) } })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const c = q.data

  return (
    <Page>
      <Link to="/teach/courses" className="mb-1 inline-block text-xs text-muted hover:text-fg">← Courses</Link>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0"><h1 className="h-page flex items-center gap-2 truncate">{c.title}<Badge tone={STATUS_TONE[c.status]} className="capitalize">{c.status}</Badge></h1>
          <p className="text-sm text-muted">{c.module_count} modules · {c.published_lesson_count}/{c.lesson_count} lessons published · {c.enrollment_count} enrolled</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn" onClick={() => setStudio(true)}>AI studio</button>
          <Link className="btn" to={`/teach/courses/${id}/preview`}><Eye size={14} /> Preview as student</Link>
          {c.status !== 'published' ? <Button className="btn-primary" loading={status.isPending} onClick={() => status.mutate('published')}>Publish</Button> : <Button loading={status.isPending} onClick={() => status.mutate('draft')}>Unpublish</Button>}
          <Menu items={[c.status === 'archived' ? { label: 'Restore to draft', onClick: () => status.mutate('draft') } : { label: 'Archive', onClick: () => status.mutate('archived') }, 'sep', { label: 'Delete…', danger: true, onClick: () => setConfirm('delete') }]} />
        </div>
      </div>
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: 'curriculum', label: 'Curriculum' }, { id: 'practice', label: 'Practice & exams' }, { id: 'details', label: 'Details' }, { id: 'access', label: 'Pricing & access' }, { id: 'students', label: `Students · ${c.enrollment_count ?? 0}` }]} />
      <div className="pt-5">
        {tab === 'curriculum' && <Curriculum c={c} refresh={refresh} err={err} />}
        {tab === 'details' && <Details c={c} onSaved={refresh} />}
        {tab === 'access' && <Access c={c} onSaved={refresh} />}
        {tab === 'students' && <CourseStudents courseId={c.id} />}
        {tab === 'practice' && <CoursePractice courseId={c.id} />}
      </div>
      {studio && <AiStudio courseId={id} onClose={() => setStudio(false)} />}
      <ConfirmDialog open={confirm === 'delete'} onClose={() => setConfirm(null)} busy={remove.isPending} onConfirm={() => remove.mutate()} title={`Delete “${c.title}”?`} message="All modules, lessons and content blocks are permanently deleted. Courses with enrollments cannot be deleted — archive them instead." />
    </Page>
  )
}

/* ---------------- curriculum builder ---------------- */
function Curriculum({ c, refresh, err }: { c: CourseDetail; refresh(): void; err(e: unknown): void }) {
  const [newModule, setNewModule] = useState('')
  const [rm, setRm] = useState<{ kind: 'modules' | 'lessons'; id: string; title: string } | null>(null)
  const act = <T,>(fn: () => Promise<T>, ok?: string) => fn().then(() => { refresh(); ok && undefined }).catch(err)
  return (
    <div className="space-y-4">
      <SortableList items={c.curriculum} onReorder={(ids) => act(() => post(`/teach/courses/${c.id}/modules/reorder`, { ids }))} className="space-y-3"
        render={(m) => <ModuleCard m={m} course={c} act={act} onDelete={() => setRm({ kind: 'modules', id: m.id, title: m.title })} onDeleteLesson={(l) => setRm({ kind: 'lessons', id: l.id, title: l.title })} />} />
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (newModule.trim()) act(() => post(`/teach/courses/${c.id}/modules`, { title: newModule })).then(() => setNewModule('')) }}>
        <input className="field" value={newModule} onChange={(e) => setNewModule(e.target.value)} placeholder="New module title, e.g. “Module 1: Introduction”" maxLength={200} aria-label="New module title" />
        <button className="btn btn-primary" disabled={!newModule.trim()}><Plus size={14} /> Add module</button>
      </form>
      {c.curriculum.length === 0 && <p className="text-sm text-muted">Start with a module, then add lessons. Open a lesson to add videos, text, formulas, quizzes and more.</p>}
      <ConfirmDialog open={!!rm} onClose={() => setRm(null)} onConfirm={() => rm && act(() => del(`/teach/${rm.kind}/${rm.id}`)).then(() => setRm(null))} title={`Delete “${rm?.title}”?`} message={rm?.kind === 'modules' ? 'The module and all its lessons and content are permanently deleted.' : 'The lesson and all its content blocks are permanently deleted.'} />
    </div>
  )
}

function ModuleCard({ m, course, act, onDelete, onDeleteLesson }: { m: ModuleNode; course: CourseDetail; act: <T>(fn: () => Promise<T>) => Promise<void>; onDelete(): void; onDeleteLesson(l: { id: string; title: string }): void }) {
  const [title, setTitle] = useState(m.title)
  const [newLesson, setNewLesson] = useState('')
  useEffect(() => setTitle(m.title), [m.title])
  const nav = useNavigate()
  return (
    <section className="card">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <input className="min-w-0 flex-1 bg-transparent font-medium outline-none focus:underline" value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => title.trim() && title !== m.title && act(() => patch(`/teach/modules/${m.id}`, { title }))} aria-label="Module title" />
        <label className="flex items-center gap-1.5 text-xs text-muted"><input type="checkbox" checked={!!m.is_published} onChange={(e) => act(() => patch(`/teach/modules/${m.id}`, { is_published: e.target.checked }))} /> Published</label>
        <button className="btn btn-ghost btn-icon text-bad" aria-label="Delete module" onClick={onDelete}><Trash2 size={14} /></button>
      </div>
      <div className="p-2">
        <SortableList items={m.lessons} onReorder={(ids) => act(() => post(`/teach/modules/${m.id}/lessons/reorder`, { ids }))} className="space-y-1"
          render={(l) => (
            <div className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-raised/60">
              <Link to={`/teach/courses/${course.id}/lessons/${l.id}`} className="min-w-0 flex-1 truncate text-sm font-medium hover:underline">{l.title}</Link>
              <span className="hidden text-xs text-muted sm:inline">{l.block_count ?? 0} blocks</span>
              {l.is_free_preview && <Badge tone="accent">free preview</Badge>}
              <label className="flex items-center gap-1 text-xs text-muted"><input type="checkbox" checked={!!l.is_published} onChange={(e) => act(() => patch(`/teach/lessons/${l.id}`, { is_published: e.target.checked }))} /> Live</label>
              <Menu items={[
                { label: 'Edit content', onClick: () => nav(`/teach/courses/${course.id}/lessons/${l.id}`) },
                { label: 'Duplicate', onClick: () => act(() => post<LessonDetail>(`/teach/lessons/${l.id}/duplicate`)) },
                ...course.curriculum.filter((x) => x.id !== m.id).map((x) => ({ label: `Move to “${x.title}”`, onClick: () => act(() => patch(`/teach/lessons/${l.id}`, { module_id: x.id })) })),
                'sep', { label: 'Delete…', danger: true, onClick: () => onDeleteLesson(l) },
              ]} />
            </div>
          )} />
        <form className="mt-1 flex gap-2 px-1" onSubmit={(e) => { e.preventDefault(); if (newLesson.trim()) act(() => post(`/teach/modules/${m.id}/lessons`, { title: newLesson })).then(() => setNewLesson('')) }}>
          <input className="field h-8" value={newLesson} onChange={(e) => setNewLesson(e.target.value)} placeholder="Add a lesson…" maxLength={200} aria-label={`New lesson in ${m.title}`} />
          <button className="btn" disabled={!newLesson.trim()}><Plus size={14} /> Lesson</button>
        </form>
      </div>
    </section>
  )
}

/* ---------------- details ---------------- */
function useSave(id: string, onSaved: () => void) {
  const toast = useToast()
  return useMutation({ mutationFn: (body: Record<string, unknown>) => patch(`/teach/courses/${id}`, body), onSuccess: () => { onSaved(); toast.ok('Saved') }, onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed') })
}
const lines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean)

function Details({ c, onSaved }: { c: CourseDetail; onSaved(): void }) {
  const [f, setF] = useState({ title: c.title, subtitle: c.subtitle, description: c.description, summary: c.summary, instructor_name: c.instructor_name, category: c.category, difficulty: c.difficulty, language: c.language, estimated_minutes: c.estimated_minutes, objectives: c.objectives.join('\n'), requirements: c.requirements.join('\n'), target_audience: c.target_audience, min_lesson_percent: c.completion_rule.min_lesson_percent ?? 100, require_quizzes: !!c.completion_rule.require_quizzes, institution_id: c.institution_id ?? '', cover_attachment_id: c.cover_attachment_id ?? '' })
  const institutions = useQuery({ queryKey: ['teach-institutions'], queryFn: () => get<{ id: string; name: string }[]>('/teach/institutions') })
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const save = useSave(c.id, onSaved)
  const { min_lesson_percent, require_quizzes, objectives, requirements, institution_id, cover_attachment_id, ...rest } = f
  const [uploading, setUploading] = useState(false)
  const uploadCover = async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    setUploading(true)
    try { const a = await api<{ id: string }>('/attachments', { form }); set('cover_attachment_id', a.id) } catch (e) { alert(e instanceof Error ? e.message : 'Upload failed') } finally { setUploading(false) }
  }
  return (
    <form className="max-w-3xl space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate({ ...rest, institution_id: institution_id || null, cover_attachment_id: cover_attachment_id || null, objectives: lines(objectives), requirements: lines(requirements), completion_rule: { min_lesson_percent, require_quizzes } }) }}>
      <Field label="Title"><input className="field" value={f.title} onChange={(e) => set('title', e.target.value)} required maxLength={200} /></Field>
      <Field label="Subtitle"><input className="field" value={f.subtitle} onChange={(e) => set('subtitle', e.target.value)} maxLength={300} /></Field>
      <div><span className="label">Description</span><MarkdownEditor value={f.description} onChange={(v) => set('description', v)} label="Description" minRows={6} /></div>
      <div><span className="label">Course summary (shown to students)</span><MarkdownEditor value={f.summary} onChange={(v) => set('summary', v)} label="Summary" minRows={4} /></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Institution (shown on the public landing page)"><select className="field" value={f.institution_id} onChange={(e) => set('institution_id', e.target.value)}><option value="">— none —</option>{institutions.data?.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></Field>
      <div><span className="label">Cover image (shown on the course card and page)</span><div className="flex flex-wrap items-center gap-3"><label className="btn cursor-pointer">{uploading ? 'Uploading…' : f.cover_attachment_id ? 'Replace image' : 'Choose image'}<input type="file" hidden accept="image/png,image/jpeg,image/webp,image/gif" onChange={(e) => { const x = e.target.files?.[0]; if (x) uploadCover(x); e.target.value = '' }} /></label>{f.cover_attachment_id && <><span className="text-sm text-muted">Image attached — press Save details.</span><button type="button" className="text-sm text-bad" onClick={() => set('cover_attachment_id', '')}>Remove</button></>}{c.status === 'published' && c.cover_attachment_id && <img src={`/api/public/courses/${c.id}/cover`} alt="" className="h-14 rounded border border-line" />}</div></div>
      <Field label="Instructor"><input className="field" value={f.instructor_name} onChange={(e) => set('instructor_name', e.target.value)} /></Field>
        <Field label="Category"><input className="field" value={f.category} onChange={(e) => set('category', e.target.value)} placeholder="e.g. Finance" /></Field>
        <Field label="Difficulty"><select className="field" value={f.difficulty} onChange={(e) => set('difficulty', e.target.value as typeof f.difficulty)}><option value="all">All levels</option><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></Field>
        <Field label="Language"><input className="field" value={f.language} onChange={(e) => set('language', e.target.value)} /></Field>
        <Field label="Estimated duration (minutes)"><input type="number" min={0} className="field" value={f.estimated_minutes} onChange={(e) => set('estimated_minutes', Number(e.target.value) || 0)} /></Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Objectives (one per line)"><textarea className="field" rows={5} value={f.objectives} onChange={(e) => set('objectives', e.target.value)} /></Field>
        <Field label="Requirements (one per line)"><textarea className="field" rows={5} value={f.requirements} onChange={(e) => set('requirements', e.target.value)} /></Field>
      </div>
      <Field label="Target audience"><textarea className="field" rows={2} value={f.target_audience} onChange={(e) => set('target_audience', e.target.value)} /></Field>
      <fieldset className="card p-3"><legend className="px-1 text-xs font-medium text-muted">Completion rule</legend>
        <div className="grid gap-3 sm:grid-cols-2"><Field label={`Lessons to complete: ${f.min_lesson_percent}%`}><input type="range" min={0} max={100} step={5} value={f.min_lesson_percent} onChange={(e) => set('min_lesson_percent', Number(e.target.value))} className="w-full" /></Field>
          <label className="flex items-end gap-2 pb-1 text-sm"><input type="checkbox" checked={f.require_quizzes} onChange={(e) => set('require_quizzes', e.target.checked)} /> Require passing all quizzes</label></div>
        <p className="mt-1 text-xs text-muted">A course is never completed merely by opening lessons. Progress tracking arrives with the student portal.</p></fieldset>
      <Button type="submit" className="btn-primary" loading={save.isPending}>Save details</Button>
    </form>
  )
}

function Access({ c, onSaved }: { c: CourseDetail; onSaved(): void }) {
  const [f, setF] = useState({ enrollment_type: c.enrollment_type, price_amount: String(c.price_amount), discount_amount: c.discount_amount == null ? '' : String(c.discount_amount), currency: c.currency, payment_policy: c.payment_policy, access_days: c.access_days == null ? '' : String(c.access_days) })
  const save = useSave(c.id, onSaved)
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }))
  const free = f.enrollment_type === 'free'
  return (
    <form className="max-w-2xl space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate({ enrollment_type: f.enrollment_type, price_amount: free ? '0' : f.price_amount || '0', discount_amount: free || f.discount_amount === '' ? null : f.discount_amount, currency: f.currency.toUpperCase(), payment_policy: f.payment_policy, access_days: f.access_days === '' ? null : Number(f.access_days) }) }}>
      <Field label="How do students get access?"><select className="field" value={f.enrollment_type} onChange={(e) => set('enrollment_type', e.target.value)}><option value="manual">Manual enrollment only (I enroll students)</option><option value="paid">Paid course</option><option value="free">Free course</option></select></Field>
      {!free && <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Price"><input type="number" min={0} step="0.01" className="field" value={f.price_amount} onChange={(e) => set('price_amount', e.target.value)} /></Field>
        <Field label="Discount price (optional)"><input type="number" min={0} step="0.01" className="field" value={f.discount_amount} onChange={(e) => set('discount_amount', e.target.value)} /></Field>
        <Field label="Currency"><input className="field" value={f.currency} maxLength={3} onChange={(e) => set('currency', e.target.value.toUpperCase())} /></Field>
      </div>}
      {f.enrollment_type === 'paid' && <Field label="Grant access when…" hint="Applied once payments are enabled."><select className="field" value={f.payment_policy} onChange={(e) => set('payment_policy', e.target.value)}><option value="full_payment">The full price is paid</option><option value="any_payment">Any payment is received</option><option value="none">Immediately (collect payment separately)</option></select></Field>}
      <Field label="Access duration (days, empty = lifetime)"><input type="number" min={1} max={3650} className="field" value={f.access_days} onChange={(e) => set('access_days', e.target.value)} /></Field>
      <p className="rounded border border-line bg-raised/50 p-3 text-xs text-muted">Pricing is stored now; payments, balances and automatic enrollment are added in the payments release. Until then, access is granted only through enrollments.</p>
      <Button type="submit" className="btn-primary" loading={save.isPending}>Save</Button>
    </form>
  )
}
export { Copy }
