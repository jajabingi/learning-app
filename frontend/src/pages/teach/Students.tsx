import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import { get, patch, post } from '@/api/client'
import { Page } from '@/components/Layout'
import { Badge, Button, Empty, ErrorState, Field, Loading, PageHeader, ProgressBar } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { duration, relTime, shortDate } from '@/lib/format'

interface Progress { percent: number; completed_lessons: number; total_lessons: number; time_spent_seconds: number; last_activity_at: string | null }
interface Enr { id: string; student_id: string; course_id: string; course_title: string; status: string; source: string; notes: string; starts_at: string | null; expires_at: string | null; completed_at: string | null; progress: Progress; student?: { id: string; email: string; display_name: string } }
const TONE: Record<string, 'good' | 'warn' | 'bad' | 'neutral' | 'accent'> = { active: 'good', completed: 'accent', pending: 'warn', suspended: 'warn', expired: 'neutral', cancelled: 'bad' }

export function StudentsList() {
  const [q, setQ] = useState('')
  const res = useQuery({ queryKey: ['teach-students', q], queryFn: () => get<{ id: string; email: string; display_name: string; enrollments: number; active_enrollments: number; last_activity_at: string | null; joined_at: string }[]>('/teach/students', { q }) })
  return (
    <Page>
      <PageHeader title="Students" subtitle="Students enrolled in your courses. To add a student to a course, open the course → Students." actions={<input className="field w-64" placeholder="Search name or email…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search students" />} />
      {res.isLoading ? <Loading /> : res.error ? <ErrorState error={res.error} retry={res.refetch} /> : !res.data?.length ? <div className="card"><Empty title={q ? 'No matching students' : 'No students yet'} icon={<Users size={28} />}>{q ? '' : 'Students register themselves, then you enroll them from a course’s Students tab.'}</Empty></div> : (
        <div className="card overflow-x-auto"><table className="w-full min-w-[560px] text-sm"><thead><tr className="border-b border-line text-left text-xs text-muted"><th className="px-4 py-2 font-medium">Student</th><th className="px-4 py-2 text-right font-medium">Courses</th><th className="px-4 py-2 text-right font-medium">Last activity</th></tr></thead>
          <tbody>{res.data.map((s) => <tr key={s.id} className="border-b border-line last:border-0 hover:bg-raised/50"><td className="px-4 py-2"><Link to={`/teach/students/${s.id}`} className="font-medium hover:underline">{s.display_name}</Link><div className="text-xs text-muted">{s.email}</div></td><td className="px-4 py-2 text-right tabnum">{s.active_enrollments} active / {s.enrollments}</td><td className="px-4 py-2 text-right text-muted">{s.last_activity_at ? relTime(s.last_activity_at) : '—'}</td></tr>)}</tbody></table></div>
      )}
    </Page>
  )
}

export function StudentProfile() {
  const { id = '' } = useParams()
  const q = useQuery({ queryKey: ['teach-student', id], queryFn: () => get<{ display_name: string; email: string; joined_at: string; is_active: boolean; enrollments: Enr[]; activity: { lesson_id: string; lesson_title: string; last_opened_at: string; time_spent_seconds: number; completed: boolean }[] }>(`/teach/students/${id}`) })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <Page><Empty title="Student not found" action={<Link className="btn" to="/teach/students">Back to students</Link>} /></Page>
  const s = q.data
  return (
    <Page>
      <Link to="/teach/students" className="mb-1 inline-block text-xs text-muted hover:text-fg">← Students</Link>
      <PageHeader title={s.display_name} subtitle={`${s.email} · joined ${shortDate(s.joined_at.slice(0, 10))}`} />
      <h2 className="h-section mb-2">Enrollments (your courses)</h2>
      <div className="card overflow-x-auto"><table className="w-full min-w-[680px] text-sm"><thead><tr className="border-b border-line text-left text-xs text-muted"><th className="px-4 py-2 font-medium">Course</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Access</th><th className="px-4 py-2 font-medium">Progress</th><th className="px-4 py-2 text-right font-medium">Time</th></tr></thead>
        <tbody>{s.enrollments.map((e) => <tr key={e.id} className="border-b border-line last:border-0"><td className="px-4 py-2"><Link to={`/teach/courses/${e.course_id}`} className="font-medium hover:underline">{e.course_title}</Link><div className="text-xs text-muted">{e.source}</div></td><td className="px-4 py-2"><Badge tone={TONE[e.status]} className="capitalize">{e.status}</Badge></td><td className="px-4 py-2 text-xs text-muted">{e.expires_at ? `until ${shortDate(e.expires_at.slice(0, 10))}` : 'lifetime'}</td><td className="px-4 py-2"><div className="flex items-center gap-2"><span className="w-24"><ProgressBar value={e.progress.percent / 100} label="Progress" /></span><span className="text-xs tabnum">{e.progress.completed_lessons}/{e.progress.total_lessons}</span></div></td><td className="px-4 py-2 text-right tabnum">{duration(e.progress.time_spent_seconds)}</td></tr>)}</tbody></table></div>
      <h2 className="h-section mb-2 mt-6">Recent learning activity</h2>
      {s.activity.length === 0 ? <p className="text-sm text-muted">No lessons opened yet.</p> : <ul className="card divide-y divide-line">{s.activity.map((a) => <li key={a.lesson_id} className="flex items-center gap-3 px-4 py-2 text-sm"><span className="min-w-0 flex-1 truncate">{a.lesson_title}</span>{a.completed && <Badge tone="good">completed</Badge>}<span className="text-xs text-muted tabnum">{duration(a.time_spent_seconds)}</span><span className="w-20 text-right text-xs text-muted">{relTime(a.last_opened_at)}</span></li>)}</ul>}
      <p className="mt-6 text-xs text-muted">Quiz results, assignments and payments will appear here as those features are released.</p>
    </Page>
  )
}

/** Enrollment management for one course (used as a tab of the course editor). */
export function CourseStudents({ courseId }: { courseId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [email, setEmail] = useState('')
  const [expires, setExpires] = useState('')
  const [notes, setNotes] = useState('')
  const list = useQuery({ queryKey: ['teach-course-enrollments', courseId], queryFn: () => get<Enr[]>(`/teach/courses/${courseId}/enrollments`) })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['teach-course-enrollments', courseId] }); qc.invalidateQueries({ queryKey: ['teach-course', courseId] }); qc.invalidateQueries({ queryKey: ['teach-students'] }) }
  const err = (e: unknown) => toast.err(e instanceof Error ? e.message : 'Failed')
  const add = useMutation({
    mutationFn: async () => {
      const s = await get<{ id: string; display_name: string }>('/teach/students/lookup', { email })
      return post('/teach/enrollments', { student_id: s.id, course_id: courseId, notes, expires_at: expires ? new Date(expires + 'T23:59:59').toISOString() : null })
    },
    onSuccess: () => { refresh(); setEmail(''); setNotes(''); setExpires(''); toast.ok('Student enrolled') }, onError: err,
  })
  const upd = useMutation({ mutationFn: (v: { id: string; body: Record<string, unknown> }) => patch(`/teach/enrollments/${v.id}`, v.body), onSuccess: refresh, onError: err })
  return (
    <div className="space-y-5">
      <form className="card grid gap-3 p-4 sm:grid-cols-[1fr_11rem_1fr_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); if (email.trim()) add.mutate() }}>
        <Field label="Student email"><input type="email" required className="field" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="student@example.com" /></Field>
        <Field label="Access until (optional)"><input type="date" className="field" value={expires} min={new Date().toISOString().slice(0, 10)} onChange={(e) => setExpires(e.target.value)} /></Field>
        <Field label="Note (optional)"><input className="field" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} placeholder="e.g. paid cash" /></Field>
        <Button type="submit" className="btn-primary" loading={add.isPending}>Enroll</Button>
        <p className="text-xs text-muted sm:col-span-4">The student must have registered an account. Enrolling gives access immediately; if the course has an access duration, the expiry is set automatically.</p>
      </form>
      {list.isLoading ? <Loading /> : !list.data?.length ? <div className="card"><Empty title="No students enrolled" icon={<Users size={26} />} /></div> : (
        <div className="card overflow-x-auto"><table className="w-full min-w-[720px] text-sm"><thead><tr className="border-b border-line text-left text-xs text-muted"><th className="px-4 py-2 font-medium">Student</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Expires</th><th className="px-4 py-2 font-medium">Progress</th><th className="px-4 py-2 text-right font-medium">Actions</th></tr></thead>
          <tbody>{list.data.map((e) => (
            <tr key={e.id} className="border-b border-line last:border-0">
              <td className="px-4 py-2"><Link to={`/teach/students/${e.student_id}`} className="font-medium hover:underline">{e.student?.display_name}</Link><div className="text-xs text-muted">{e.student?.email}{e.notes ? ` · ${e.notes}` : ''}</div></td>
              <td className="px-4 py-2"><Badge tone={TONE[e.status]} className="capitalize">{e.status}</Badge></td>
              <td className="px-4 py-2 text-xs text-muted">{e.expires_at ? shortDate(e.expires_at.slice(0, 10)) : 'never'}</td>
              <td className="px-4 py-2"><div className="flex items-center gap-2"><span className="w-20"><ProgressBar value={e.progress.percent / 100} label="Progress" /></span><span className="text-xs tabnum">{e.progress.percent}%</span></div></td>
              <td className="px-4 py-2 text-right"><div className="flex justify-end gap-1">
                {['active', 'completed'].includes(e.status) ? <button className="btn h-7" onClick={() => upd.mutate({ id: e.id, body: { status: 'suspended' } })}>Suspend</button> : <button className="btn h-7" onClick={() => upd.mutate({ id: e.id, body: { status: 'active' } })}>Activate</button>}
                {e.status !== 'cancelled' && <button className="btn btn-danger h-7" onClick={() => confirm(`Revoke access for ${e.student?.display_name}? They lose access immediately.`) && upd.mutate({ id: e.id, body: { status: 'cancelled' } })}>Revoke</button>}
                {e.expires_at && <button className="btn h-7" onClick={() => upd.mutate({ id: e.id, body: { clear_expiry: true } })}>No expiry</button>}
              </div></td>
            </tr>))}</tbody></table></div>
      )}
    </div>
  )
}
