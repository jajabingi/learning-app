import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BookOpen, GraduationCap, Layers, PlayCircle, Users } from 'lucide-react'
import { get, post } from '@/api/client'
import type { Course } from '@/api/types'
import { Page } from '@/components/Layout'
import { Badge, Button, Empty, ErrorState, Field, Loading, Modal, PageHeader, Stat } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { relTime } from '@/lib/format'

export const STATUS_TONE = { draft: 'warn', published: 'good', archived: 'neutral' } as const

interface Dash { pending_requests: number; courses: { total: number; draft: number; published: number; archived: number }; modules: number; lessons: number; published_lessons: number; enrollments: number; recent_courses: Course[] }

export function CourseCard({ c }: { c: Course }) {
  return (
    <Link to={`/teach/courses/${c.id}`} className="card block p-4 hover:border-faint">
      <div className="flex items-start justify-between gap-2"><h3 dir="auto" className="min-w-0 truncate font-medium">{c.title}</h3><Badge tone={STATUS_TONE[c.status]} className="capitalize">{c.status}</Badge></div>
      <p dir="auto" className="mt-1 line-clamp-2 min-h-10 text-sm text-muted">{c.subtitle || c.description || 'No description yet'}</p>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted tabnum">
        <span className="inline-flex items-center gap-1"><Layers size={12} />{c.module_count ?? 0} modules</span>
        <span className="inline-flex items-center gap-1"><PlayCircle size={12} />{c.published_lesson_count ?? 0}/{c.lesson_count ?? 0} lessons live</span>
        <span className="inline-flex items-center gap-1"><Users size={12} />{c.enrollment_count ?? 0}</span>
      </div>
      <div className="mt-2 text-xs text-faint">{c.enrollment_type === 'free' ? 'Free' : c.enrollment_type === 'paid' ? `${c.currency} ${c.price_amount}` : 'Manual enrollment'} · updated {relTime(c.updated_at)}</div>
    </Link>
  )
}

export function TeachDashboard() {
  const q = useQuery({ queryKey: ['teach-dashboard'], queryFn: () => get<Dash>('/teach/dashboard') })
  const [creating, setCreating] = useState(false)
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const d = q.data
  return (
    <Page>
      <PageHeader title="Teaching" subtitle="Your courses, content and students." actions={<button className="btn btn-primary" onClick={() => setCreating(true)}>New course</button>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Published courses" value={d.courses.published} hint={`${d.courses.draft} draft · ${d.courses.archived} archived`} />
        <Stat label="Modules" value={d.modules} /><Stat label="Lessons" value={d.lessons} hint={`${d.published_lessons} published`} /><Stat label="Enrollments" value={d.enrollments} hint={d.pending_requests ? `${d.pending_requests} purchase requests waiting` : undefined} tone={d.pending_requests ? 'warn' : undefined} />
      </div>
      <h2 dir="auto" className="h-section mb-2 mt-6">Recently edited</h2>
      {d.recent_courses.length === 0 ? <div className="card"><Empty title="Create your first course" icon={<GraduationCap size={28} />} action={<button className="btn btn-primary" onClick={() => setCreating(true)}>New course</button>}>Build modules and lessons with videos, text, formulas, quizzes and downloads, preview them as a student, then publish.</Empty></div>
        : <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{d.recent_courses.map((c) => <CourseCard key={c.id} c={c} />)}</div>}
      <p className="mt-6 text-xs text-muted">Payments, student management, assignments and analytics arrive in later releases; your personal library, questions and study tools remain in the sidebar.</p>
      <NewCourse open={creating} onClose={() => setCreating(false)} />
    </Page>
  )
}

export function CoursesList() {
  const [filter, setFilter] = useState('')
  const q = useQuery({ queryKey: ['teach-courses', filter], queryFn: () => get<Course[]>('/teach/courses', { status_: filter }) })
  const [creating, setCreating] = useState(false)
  return (
    <Page>
      <PageHeader title="Courses" actions={<><select className="field h-8 w-auto py-0" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by status"><option value="">All statuses</option><option value="draft">Draft</option><option value="published">Published</option><option value="archived">Archived</option></select><button className="btn btn-primary" onClick={() => setCreating(true)}>New course</button></>} />
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} retry={q.refetch} /> : !q.data?.length ? <div className="card"><Empty title="No courses" icon={<BookOpen size={28} />}>{filter ? 'No courses with this status.' : 'Create your first course to get started.'}</Empty></div>
        : <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{q.data.map((c) => <CourseCard key={c.id} c={c} />)}</div>}
      <NewCourse open={creating} onClose={() => setCreating(false)} />
    </Page>
  )
}

function NewCourse({ open, onClose }: { open: boolean; onClose(): void }) {
  const [title, setTitle] = useState('')
  const [subtitle, setSubtitle] = useState('')
  const nav = useNavigate()
  const toast = useToast()
  const m = useMutation({ mutationFn: () => post<Course>('/teach/courses', { title, subtitle }), onSuccess: (c) => { onClose(); setTitle(''); setSubtitle(''); nav(`/teach/courses/${c.id}`) }, onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed') })
  return (
    <Modal open={open} onClose={onClose} title="New course">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (title.trim()) m.mutate() }}>
        <Field label="Title"><input className="field" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required autoFocus placeholder="e.g. Investment Fundamentals" /></Field>
        <Field label="Subtitle (optional)"><input className="field" value={subtitle} onChange={(e) => setSubtitle(e.target.value)} maxLength={300} /></Field>
        <p className="text-xs text-muted">Courses start as drafts. Students cannot see them until you publish.</p>
        <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onClose}>Cancel</button><Button type="submit" className="btn-primary" loading={m.isPending}>Create course</Button></div>
      </form>
    </Modal>
  )
}
