import { useMemo, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, GraduationCap, LogOut, Moon, PlayCircle, Sun } from 'lucide-react'
import { get, post } from '@/api/client'
import { CourseViewer, type StudentProgress } from '@/components/lms/CourseViewer'
import { FileUrlContext } from '@/components/Markdown'
import { Badge, Button, Empty, ErrorState, Field, Loading, ProgressBar } from '@/components/ui'
import { useAuth } from '@/contexts/auth'
import { useTheme } from '@/contexts/theme'
import { useToast } from '@/contexts/toast'
import { t } from '@/i18n'
import { duration, shortDate } from '@/lib/format'

const NAV: [string, string, boolean][] = [['/my', 'nav.dashboard', true], ['/courses', 'nav.myCourses', false], ['/practice', 'nav.practice', false], ['/explore', 'nav.explore', false], ['/account', 'nav.account', false]]

/** Student portal shell: right-to-left, full width, its own navigation. */
export function StudentLayout() {
  const { user, logout } = useAuth()
  const { dark, setPref } = useTheme()
  const nav = useNavigate()
  // students may only fetch course files through the enrollment-checked endpoint
  const mapUrl = useMemo(() => (src: string) => src.replace(/^\/api\/attachments\/([0-9a-f-]{36})\/file/, '/api/student/files/$1'), [])
  return (
    <FileUrlContext.Provider value={mapUrl}>
      <div className="student-portal min-h-full bg-bg" dir="rtl" lang="he">
        <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
          <div className="flex h-16 items-center gap-4 px-4 sm:gap-8 sm:px-8 lg:px-12">
            <Link to="/my" className="flex items-center gap-2 font-semibold"><span className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-accent-fg"><GraduationCap size={17} /></span><span className="hidden text-lg sm:inline">Recall</span></Link>
            <nav className="flex min-w-0 gap-1 overflow-x-auto" aria-label="ניווט תלמיד">
              {NAV.map(([to, key, end]) => <NavLink key={to} to={to} end={end} className={({ isActive }) => `whitespace-nowrap rounded px-3.5 py-2 text-base font-medium ${isActive ? 'bg-raised' : 'text-muted hover:text-fg'}`}>{t(key)}</NavLink>)}
            </nav>
            <div className="me-auto flex items-center gap-1">
              <span className="hidden max-w-40 truncate text-sm text-muted md:inline">{user?.display_name}</span>
              <button className="btn btn-ghost btn-icon" aria-label={t('common.theme')} onClick={() => setPref(dark ? 'light' : 'dark')}>{dark ? <Sun size={16} /> : <Moon size={16} />}</button>
              <button className="btn btn-ghost btn-icon sm:w-auto sm:px-3" aria-label={t('common.signOut')} onClick={() => { logout(); nav('/') }}><LogOut size={14} className="rtl:-scale-x-100" /> <span className="hidden sm:inline">{t('common.signOut')}</span></button>
            </div>
          </div>
        </header>
        <main className="px-4 py-6 sm:px-8 lg:px-12"><Outlet /></main>
      </div>
    </FileUrlContext.Provider>
  )
}

interface CourseCardData { id: string; title: string; subtitle: string; instructor_name: string; category: string; enrollment_status: string | null; has_access: boolean; expires_at?: string | null; progress?: StudentProgress & { last_activity_at?: string | null } }

function ProgressCard({ c }: { c: CourseCardData }) {
  const p = c.progress
  return (
    <Link to={`/courses/${c.id}`} className="card block p-5 hover:border-faint">
      <div className="flex items-start justify-between gap-2"><h2 dir="auto" className="text-lg font-semibold">{c.title}</h2>{c.enrollment_status === 'completed' && <Badge tone="good">{t('student.completed')}</Badge>}</div>
      {c.subtitle && <p dir="auto" className="mt-1 line-clamp-2 text-sm text-muted">{c.subtitle}</p>}
      {p && <div className="mt-4"><div className="mb-1 flex justify-between text-sm text-muted tabnum"><span>{t('student.lessonsOf', { a: p.completed_lessons, b: p.total_lessons })}</span><span>{p.percent}%</span></div><ProgressBar value={p.percent / 100} tone="accent" label={c.title} /></div>}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted">{c.instructor_name && <span dir="auto">{c.instructor_name}</span>}{c.expires_at && <span>{t('student.accessUntil', { d: shortDate(c.expires_at.slice(0, 10)) })}</span>}</div>
      <span className="btn btn-primary mt-4 w-full text-base">{p && p.completed_lessons > 0 && p.percent < 100 ? t('student.continue') : p && p.percent >= 100 ? t('student.reviewCourse') : t('student.startCourse')}</span>
    </Link>
  )
}

interface Dash { continue_learning: { course_id: string; course_title: string; lesson_id: string; lesson_title: string | null; percent: number } | null; courses: CourseCardData[]; totals: { courses: number; completed_courses: number; lessons_completed: number; time_spent_seconds: number } }

export function StudentHome() {
  const { user } = useAuth()
  const q = useQuery({ queryKey: ['student-dashboard'], queryFn: () => get<Dash>('/student/dashboard') })
  if (q.isLoading) return <Loading label={t('common.loading')} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const d = q.data
  return (
    <div className="space-y-6">
      <div><h1 className="text-3xl font-semibold tracking-tight">{user?.display_name ? t('student.welcomeName', { name: user.display_name }) : t('student.welcome')}</h1><p className="mt-1 text-lg text-muted">{t('student.pickUp')}</p></div>
      {d.continue_learning && (
        <section className="card flex flex-wrap items-center gap-4 border-accent/40 bg-accent/5 p-5">
          <PlayCircle size={32} className="text-accent" />
          <div className="min-w-0 flex-1"><div className="text-sm font-medium text-muted">{t('student.continueLearning')}</div><div dir="auto" className="truncate text-xl font-semibold">{d.continue_learning.lesson_title ?? d.continue_learning.course_title}</div><div dir="auto" className="text-sm text-muted">{d.continue_learning.course_title} · {d.continue_learning.percent}%</div></div>
          <Link to={`/courses/${d.continue_learning.course_id}?lesson=${d.continue_learning.lesson_id}`} className="btn btn-primary btn-lg">{t('student.resume')}</Link>
        </section>
      )}
      {d.courses.length === 0 ? <div className="card"><Empty title={t('student.noCourses')} icon={<BookOpen size={28} />} action={<Link className="btn btn-primary" to="/explore">{t('student.browse')}</Link>}>{t('student.noCoursesHint')}</Empty></div> : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            {[[t('student.courses'), d.totals.courses], [t('student.lessonsDone'), d.totals.lessons_completed], [t('student.timeStudied'), duration(d.totals.time_spent_seconds)]].map(([l, v]) => <div key={l as string} className="card p-4"><div className="text-sm text-muted">{l}</div><div className="mt-1 text-2xl font-semibold tabnum">{v}</div></div>)}
          </div>
          <section><h2 className="mb-3 text-lg font-semibold">{t('student.myCourses')}</h2><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{d.courses.map((c) => <ProgressCard key={c.id} c={c} />)}</div></section>
        </>
      )}
    </div>
  )
}

export function MyCourses() {
  const q = useQuery({ queryKey: ['student-courses'], queryFn: () => get<CourseCardData[]>('/student/courses') })
  if (q.isLoading) return <Loading label={t('common.loading')} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  return (
    <div><h1 className="mb-4 text-3xl font-semibold tracking-tight">{t('student.myCourses')}</h1>
      {q.data.length === 0 ? <div className="card"><Empty title={t('student.noCourses')} icon={<BookOpen size={28} />} action={<Link className="btn btn-primary" to="/explore">{t('student.browse')}</Link>}>{t('student.noCoursesHint')}</Empty></div> : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{q.data.map((c) => <ProgressCard key={c.id} c={c} />)}</div>}
    </div>
  )
}

export function StudentCourse() {
  const { id = '' } = useParams()
  const [sp] = useSearchParams()
  const q = useQuery({ queryKey: ['student-course', id], queryFn: () => get<{ title: string; curriculum: never[]; progress: StudentProgress } & Record<string, any>>(`/student/courses/${id}`), staleTime: 0 })
  if (q.isLoading) return <Loading label={t('common.loading')} />
  if (q.error || !q.data) return <div className="card"><Empty title={t('student.courseUnavailable')} action={<Link className="btn" to="/courses">{t('student.backToMyCourses')}</Link>}>{t('student.courseUnavailableHint')}</Empty></div>
  return (
    <div>
      <Link to="/courses" className="mb-3 inline-block text-sm text-muted hover:text-fg"><span className="inline-block rtl:-scale-x-100">←</span> {t('student.myCourses')}</Link>
      <CourseViewer course={q.data as never} student initialLesson={sp.get('lesson')} lessonPath={(lid) => `/student/lessons/${lid}`} />
    </div>
  )
}

export function StudentAccount() {
  const { user, updateUser } = useAuth()
  const toast = useToast()
  const [name, setName] = useState(user?.display_name ?? '')
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState('')
  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => { setBusy(key); try { await fn(); toast.ok(ok) } catch (e) { toast.err(e instanceof Error ? e.message : t('common.somethingWrong')) } finally { setBusy('') } }
  return (
    <div className="max-w-xl space-y-5">
      <h1 className="text-3xl font-semibold tracking-tight">{t('student.account')}</h1>
      <section className="card space-y-3 p-5"><Field label={t('student.name')}><input className="field text-base" dir="auto" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} /></Field><Field label={t('student.email')}><input className="field text-base" dir="ltr" value={user?.email ?? ''} disabled /></Field><Button className="btn-primary" loading={busy === 'p'} onClick={() => run('p', () => updateUser({ display_name: name }), t('student.saved'))}>{t('common.save')}</Button></section>
      <section className="card space-y-3 p-5"><h2 className="text-base font-semibold">{t('student.changePassword')}</h2><Field label={t('student.currentPassword')}><input type="password" dir="ltr" className="field text-base" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" /></Field><Field label={t('student.newPassword')} hint={t('auth.passwordHint')}><input type="password" dir="ltr" className="field text-base" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" /></Field><Button loading={busy === 'w'} disabled={!cur || next.length < 8} onClick={() => run('w', async () => { await post('/auth/change-password', { current_password: cur, new_password: next }); setCur(''); setNext('') }, t('student.passwordChanged'))}>{t('student.changePassword')}</Button></section>
    </div>
  )
}
