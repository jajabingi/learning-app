import { useMemo, useState } from 'react'
import { Link, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, BookOpenText, Building2, ChevronDown, ChevronLeft, ChevronRight, FileText, GraduationCap, Lock, Moon, PencilLine, PlayCircle, Sun } from 'lucide-react'
import { get, post } from '@/api/client'
import type { Block } from '@/api/types'
import { BlockView } from '@/components/lms/BlockView'
import { Markdown } from '@/components/Markdown'
import { Badge, Button, Empty, ErrorState, Loading, Modal, cx } from '@/components/ui'
import { useAuth } from '@/contexts/auth'
import { useTheme } from '@/contexts/theme'
import { useToast } from '@/contexts/toast'
import { t } from '@/i18n'

export const homePath = (role?: string) => (role === 'student' ? '/my' : '/teach')

interface Inst { id: string; slug: string; name: string; description: string; course_count: number }
interface Card { id: string; title: string; subtitle: string; instructor_name: string; category: string; difficulty: string; language: string; estimated_minutes: number; enrollment_type: 'free' | 'paid' | 'manual'; price_amount: number | null; discount_amount: number | null; currency: string; access_days: number | null; has_cover: boolean; institution: { id: string; slug: string; name: string } | null }
interface OutlineLesson { id: string; title: string; is_free_preview: boolean; estimated_minutes: number; kinds: string[] }
interface Detail extends Card { description: string; objectives: string[]; requirements: string[]; target_audience: string; free_lessons: number; lesson_count: number; outline: { title: string; description: string; lessons: OutlineLesson[] }[] }
interface StudentState { has_access: boolean; can_self_enroll: boolean; enrollment_status: string | null }

const SYMBOL: Record<string, string> = { ILS: '₪', USD: '$', EUR: '€', GBP: '£' }
const money = (v: number, cur: string) => `${SYMBOL[cur] ?? cur + ' '}${v.toLocaleString('he-IL')}`
const LEVEL: Record<string, string> = { beginner: 'common.levelBeginner', intermediate: 'common.levelIntermediate', advanced: 'common.levelAdvanced', all: 'common.levelAll' }
const accessLabel = (days: number | null) => (!days ? t('home.accessForever') : days >= 28 ? (Math.round(days / 30) <= 1 ? t('home.accessMonth') : t('home.accessMonths', { n: Math.round(days / 30) })) : t('home.accessDays', { n: days }))

function Price({ c, big }: { c: Card; big?: boolean }) {
  if (c.enrollment_type === 'free') return <Badge tone="good">{t('common.free')}</Badge>
  if (c.enrollment_type === 'manual' || c.price_amount == null) return <span className="text-sm text-muted">{t('common.byEnrollment')}</span>
  return (
    <span className={cx('tabnum font-bold', big ? 'text-2xl' : 'text-lg')}>
      {c.discount_amount != null ? <><span className="me-2 text-sm font-normal text-muted line-through">{money(c.price_amount, c.currency)}</span>{money(c.discount_amount, c.currency)}</> : money(c.price_amount, c.currency)}
    </span>
  )
}

function Cover({ c, className }: { c: Card; className?: string }) {
  return c.has_cover
    ? <img src={`/api/public/courses/${c.id}/cover`} alt="" loading="lazy" className={cx('w-full object-cover', className)} />
    : <div className={cx('flex w-full items-center justify-center bg-gradient-to-br from-[#0b1b4d] to-accent text-5xl font-bold text-white/80', className)} aria-hidden>{c.title.slice(0, 1)}</div>
}

/** Public shell: used by everyone (visitors and signed-in users). The site root always lands here. */
export function PublicLayout() {
  const { dark, setPref } = useTheme()
  const { user, logout } = useAuth()
  const nav = useNavigate()
  return (
    <div className="student-portal flex min-h-full flex-col bg-bg" dir="rtl" lang="he">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        <div className="flex h-16 items-center gap-4 px-4 sm:gap-8 sm:px-8 lg:px-12">
          <Link to="/" className="flex items-center gap-2 font-semibold"><span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-accent-fg"><BookOpenText size={18} /></span><span className="text-xl">Recall</span></Link>
          <nav className="hidden gap-1 sm:flex"><Link to="/explore" className="rounded px-3.5 py-2 text-base font-medium hover:text-accent">{t('nav.courses')}</Link><a href="/#faq" className="rounded px-3.5 py-2 text-base font-medium hover:text-accent">{t('nav.faq')}</a></nav>
          <div className="me-auto flex items-center gap-2">
            <button className="btn btn-ghost btn-icon" aria-label={t('common.theme')} onClick={() => setPref(dark ? 'light' : 'dark')}>{dark ? <Sun size={16} /> : <Moon size={16} />}</button>
            {user ? (
              <><Link to={homePath(user.role)} className="btn btn-primary text-base">{t('home.myArea')}</Link><button className="btn text-base" onClick={() => { logout(); nav('/') }}>{t('common.signOut')}</button></>
            ) : (
              <><Link to="/login" className="px-3 text-base font-medium text-accent hover:underline">{t('common.signIn')}</Link><Link to="/register" className="btn btn-primary text-base">{t('common.signUp')}</Link></>
            )}
          </div>
        </div>
      </header>
      <main className="flex-1"><Outlet /></main>
      <footer className="border-t border-line bg-surface px-4 py-6 text-sm text-muted sm:px-8 lg:px-12">
        <div className="flex flex-wrap items-center justify-between gap-3"><span>© Recall · {t('home.rights')}</span><span className="flex gap-4"><Link to="/terms" className="hover:text-fg">תנאי שימוש</Link><Link to="/privacy" className="hover:text-fg">מדיניות פרטיות</Link></span><Link to="/teachers" className="hover:text-fg">{t('home.teachersLogin')}</Link></div>
      </footer>
    </div>
  )
}

function CourseCard({ c }: { c: Card }) {
  return (
    <Link to={`/course/${c.id}`} className="card group flex flex-col overflow-hidden hover:border-accent">
      <div className="relative">
        <Cover c={c} className="aspect-[16/9]" />
        <span className="absolute start-3 top-3 rounded bg-accent px-2 py-1 text-xs font-semibold text-accent-fg">{accessLabel(c.access_days)}</span>
      </div>
      <div className="flex flex-1 flex-col p-5">
        <h3 dir="auto" className="text-xl font-bold leading-snug text-fg">{c.title}</h3>
        {c.subtitle && <p dir="auto" className="mt-2 line-clamp-3 text-sm leading-6 text-muted">{c.subtitle}</p>}
        <div className="mt-4 flex items-center gap-2 text-sm text-muted">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/10 text-sm font-semibold text-accent">{(c.instructor_name || c.institution?.name || '?').slice(0, 1)}</span>
          <span dir="auto" className="truncate">{c.instructor_name || c.institution?.name}</span>
        </div>
        <div className="mt-auto flex items-center justify-between gap-3 pt-5"><Price c={c} /><span className="btn btn-primary text-base group-hover:opacity-90">{t('home.details')}</span></div>
      </div>
    </Link>
  )
}

export function Landing() {
  const inst = useQuery({ queryKey: ['public-institutions'], queryFn: () => get<Inst[]>('/public/institutions') })
  const courses = useQuery({ queryKey: ['public-courses', ''], queryFn: () => get<Card[]>('/public/courses') })
  const [instId, setInstId] = useState('')
  const [cat, setCat] = useState('')
  const list = (courses.data ?? []).filter((c) => (!instId || c.institution?.id === instId) && (!cat || c.category === cat))
  const cats = useMemo(() => [...new Set((courses.data ?? []).filter((c) => !instId || c.institution?.id === instId).map((c) => c.category).filter(Boolean))], [courses.data, instId])
  const faq = [1, 2, 3, 4, 5]
  return (
    <div>
      <section className="bg-[#0b1b4d] px-4 py-14 text-center text-white sm:px-8">
        <h1 className="text-3xl font-bold tracking-tight sm:text-5xl">{t('home.heroTitle')}</h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg leading-8 text-white/80">{t('home.heroSub')}</p>
      </section>

      <section className="px-4 sm:px-8 lg:px-12">
        <div className="-mx-1 flex gap-1 overflow-x-auto border-b border-line" role="tablist" aria-label={t('landing.institutions')}>
          {[{ id: '', name: t('home.allInstitutions') }, ...(inst.data ?? [])].map((i) => (
            <button key={i.id} role="tab" aria-selected={instId === i.id} onClick={() => { setInstId(i.id); setCat('') }} dir="auto"
              className={cx('-mb-px whitespace-nowrap border-b-4 px-5 py-4 text-lg font-semibold', instId === i.id ? 'border-[#0b1b4d] text-fg dark:border-accent' : 'border-transparent text-muted hover:text-fg')}>{i.name}</button>
          ))}
        </div>

        {instId && <p dir="auto" className="mx-auto mt-5 max-w-3xl text-center text-base leading-7 text-muted">{inst.data?.find((i) => i.id === instId)?.description}</p>}

        {cats.length > 0 && (
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2"><span className="text-sm font-semibold text-accent">{t('home.filterBy')}</span>
            {['', ...cats].map((c) => <button key={c} onClick={() => setCat(c)} aria-pressed={cat === c} className={cx('rounded px-4 py-1.5 text-sm font-medium', cat === c ? 'bg-accent text-accent-fg' : 'bg-accent/10 text-accent hover:bg-accent/20')}>{c || t('home.allSubjects')}</button>)}</div>
        )}

        <div className="py-8">
          {courses.isLoading || inst.isLoading ? <Loading label={t('common.loading')} /> : courses.error ? <ErrorState error={courses.error} retry={courses.refetch} /> : list.length === 0 ? <div className="card"><Empty title={t('home.noCoursesHere')} icon={<Building2 size={28} />} /></div> : (
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">{list.map((c) => <CourseCard key={c.id} c={c} />)}</div>
          )}
        </div>
      </section>

      <section className="bg-surface px-4 py-12 sm:px-8 lg:px-12">
        <h2 className="mb-6 text-center text-2xl font-bold">{t('landing.howTitle')}</h2>
        <ol className="mx-auto grid max-w-4xl gap-6 sm:grid-cols-3">{['landing.how1', 'landing.how2', 'landing.how3'].map((k, i) => <li key={k} className="text-center"><span className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-[#0b1b4d] text-lg font-semibold text-white">{i + 1}</span><p className="mt-3 text-lg">{t(k)}</p></li>)}</ol>
      </section>

      <section id="faq" className="mx-auto max-w-3xl px-4 py-12">
        <h2 className="mb-6 text-center text-2xl font-bold">{t('home.faqTitle')}</h2>
        <div className="space-y-2">{faq.map((n) => <details key={n} className="card group p-4"><summary className="flex cursor-pointer list-none items-center justify-between text-lg font-semibold">{t(`home.q${n}`)}<ChevronDown size={18} className="text-muted transition-transform group-open:rotate-180" /></summary><p className="mt-3 text-base leading-7 text-muted">{t(`home.a${n}`)}</p></details>)}</div>
      </section>
    </div>
  )
}

export function ExploreAll() {
  const [q, setQ] = useState('')
  const res = useQuery({ queryKey: ['public-courses', q], queryFn: () => get<Card[]>('/public/courses', { q }) })
  return (
    <div className="px-4 py-8 sm:px-8 lg:px-12">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><h1 className="text-3xl font-bold tracking-tight">{t('explore.allTitle')}</h1><input className="field w-full text-base sm:w-72" dir="auto" placeholder={t('explore.search')} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t('explore.search')} /></div>
      {res.isLoading ? <Loading label={t('common.loading')} /> : res.error ? <ErrorState error={res.error} retry={res.refetch} /> : !res.data?.length ? <div className="card"><Empty title={t('explore.noCourses')} /></div> : <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">{res.data.map((c) => <CourseCard key={c.id} c={c} />)}</div>}
    </div>
  )
}

export function ExploreInstitution() {
  const { slug = '' } = useParams()
  const q = useQuery({ queryKey: ['public-institution', slug], queryFn: () => get<{ name: string; description: string; courses: Card[] }>(`/public/institutions/${slug}`) })
  if (q.isLoading) return <Loading label={t('common.loading')} />
  if (q.error || !q.data) return <div className="p-8"><div className="card"><Empty title={t('explore.institutionNotFound')} action={<Link className="btn" to="/">{t('explore.backToAll')}</Link>} /></div></div>
  const d = q.data
  return (
    <div className="px-4 py-8 sm:px-8 lg:px-12">
      <Link to="/" className="mb-3 inline-block text-sm text-muted hover:text-fg"><span className="inline-block rtl:-scale-x-100">←</span> {t('explore.backToAll')}</Link>
      <div className="mb-6 flex items-start gap-4"><span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent"><Building2 size={28} /></span><div><h1 dir="auto" className="text-3xl font-bold tracking-tight">{d.name}</h1>{d.description && <p dir="auto" className="mt-1 max-w-3xl text-lg leading-8 text-muted">{d.description}</p>}</div></div>
      {d.courses.length === 0 ? <div className="card"><Empty title={t('explore.noCourses')} /></div> : <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">{d.courses.map((c) => <CourseCard key={c.id} c={c} />)}</div>}
    </div>
  )
}

const KIND_ICON: Record<string, typeof PlayCircle> = { video: PlayCircle, quiz: PencilLine, file: FileText }

/** Public course page: free lessons are readable by anyone; everything else triggers the purchase dialog. */
export function PublicCourse() {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [sel, setSel] = useState<string | null>(null)
  const [open, setOpen] = useState<number | null>(0)
  const [paywall, setPaywall] = useState(false)
  const isStudent = user?.role === 'student'
  const q = useQuery({ queryKey: ['public-course', id], queryFn: () => get<Detail>(`/public/courses/${id}`) })
  const st = useQuery({ queryKey: ['student-catalog-course', id], queryFn: () => get<StudentState>(`/student/catalog/${id}`), enabled: isStudent })
  const lesson = useQuery({ queryKey: ['public-lesson', id, sel], queryFn: () => get<{ title: string; summary: string; blocks: Block[] }>(`/public/courses/${id}/preview/${sel}`), enabled: !!sel })
  const flat = useMemo(() => (q.data?.outline ?? []).flatMap((m) => m.lessons), [q.data])
  const idx = flat.findIndex((l) => l.id === sel)
  const state: StudentState | undefined = st.data

  const openLesson = (l: { id: string; is_free_preview: boolean }) => { if (state?.has_access) return nav(`/courses/${id}?lesson=${l.id}`); l.is_free_preview ? setSel(l.id) : setPaywall(true) }
  const request = useMutation({ mutationFn: () => post(`/student/courses/${id}/request-access`), onSuccess: () => { qc.invalidateQueries({ queryKey: ['student-catalog-course', id] }); toast.ok(t('course.requestSent')) }, onError: (e) => toast.err(e instanceof Error ? e.message : t('common.somethingWrong')) })
  const enroll = useMutation({ mutationFn: () => post(`/student/courses/${id}/enroll`), onSuccess: () => { qc.invalidateQueries(); nav(`/courses/${id}`) }, onError: (e) => toast.err(e instanceof Error ? e.message : t('common.somethingWrong')) })

  if (q.isLoading) return <Loading label={t('common.loading')} />
  if (q.error || !q.data) return <div className="p-8"><div className="card"><Empty title={t('course.notFound')} action={<Link className="btn" to="/explore">{t('nav.allCourses')}</Link>} /></div></div>
  const c = q.data
  const locked = c.lesson_count - c.free_lessons
  const next = flat[idx + 1]
  const LessonRow = ({ l }: { l: OutlineLesson }) => {
    const Icon = KIND_ICON[l.kinds[0]] ?? BookOpen
    const free = l.is_free_preview || state?.has_access
    return (
      <li><button onClick={() => openLesson(l)} className={cx('flex w-full items-center gap-3 rounded px-2 py-2.5 text-start text-base hover:bg-raised/70', sel === l.id && 'bg-raised font-medium')}>
        <Icon size={18} className={free ? 'text-good' : 'text-muted'} />
        <span dir="auto" className="min-w-0 flex-1">{l.title}</span>
        {l.is_free_preview && !state?.has_access && <Badge tone="good">{t('common.free')}</Badge>}
        {l.estimated_minutes > 0 && <span className="text-sm text-muted tabnum">{l.estimated_minutes} {t('common.minutesShort')}</span>}
        {!free && <Lock size={14} className="text-faint" aria-label={t('course.locked')} />}
      </button></li>
    )
  }

  return (
    <div>
      <section className="relative bg-[#0b1b4d] text-white">
        <div className="grid items-center gap-6 px-4 py-10 sm:px-8 lg:grid-cols-[minmax(0,1fr)_28rem] lg:px-12">
          <div>
            {c.institution && <Link to="/" className="mb-3 inline-flex items-center gap-1 text-sm text-white/80 hover:text-white"><Building2 size={14} />{c.institution.name}</Link>}
            <h1 dir="auto" className="text-3xl font-bold tracking-tight sm:text-4xl">{c.title}</h1>
            {c.subtitle && <p dir="auto" className="mt-3 max-w-3xl text-lg leading-8 text-white/85">{c.subtitle}</p>}
            <p className="mt-4 text-sm text-white/75">{c.instructor_name && <span dir="auto">{t('course.by')} {c.instructor_name} · </span>}{t(LEVEL[c.difficulty] ?? 'common.levelAll')} · {c.language} · {t('course.lessonsCount', { n: c.lesson_count })}</p>
          </div>
          <div className="hidden overflow-hidden rounded-xl border border-white/20 shadow-xl lg:block"><Cover c={c} className="aspect-[16/9]" /></div>
        </div>
      </section>

      <div className="grid gap-8 px-4 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_24rem] lg:px-12">
        <div className="min-w-0 space-y-8">
          {!sel ? (
            <>
              {c.description && <section><Markdown>{c.description}</Markdown></section>}
              <div className="grid gap-6 sm:grid-cols-2">
                {c.objectives.length > 0 && <section><h2 className="mb-2 text-xl font-bold">{t('course.whatYouLearn')}</h2><ul dir="auto" className="list-disc space-y-1.5 ps-6 text-base leading-7">{c.objectives.map((o, i) => <li key={i}>{o}</li>)}</ul></section>}
                {c.requirements.length > 0 && <section><h2 className="mb-2 text-xl font-bold">{t('course.requirements')}</h2><ul dir="auto" className="list-disc space-y-1.5 ps-6 text-base leading-7">{c.requirements.map((o, i) => <li key={i}>{o}</li>)}</ul></section>}
              </div>
              {c.target_audience && <section><h2 className="mb-2 text-xl font-bold">{t('course.audience')}</h2><p dir="auto" className="text-base leading-7">{c.target_audience}</p></section>}
              <section>
                <h2 className="mb-3 text-xl font-bold">{t('course.contentTitle')}</h2>
                <div className="overflow-hidden rounded-lg border border-line bg-surface">
                  {c.outline.map((m, mi) => (
                    <div key={mi} className="border-b border-line last:border-0">
                      <button className="flex w-full items-center gap-4 px-5 py-5 text-start" aria-expanded={open === mi} onClick={() => setOpen(open === mi ? null : mi)}>
                        <span className="text-2xl font-light text-faint tabnum">{String(mi + 1).padStart(2, '0')}</span>
                        <span className="min-w-0 flex-1"><span dir="auto" className="block text-lg font-bold">{m.title}</span><span className="text-sm text-muted">{t('course.lessonOf', { n: m.lessons.length })}</span></span>
                        <ChevronDown size={22} className={cx('text-faint transition-transform', open === mi && 'rotate-180')} />
                      </button>
                      {open === mi && <div className="px-5 pb-5">{m.description && <p dir="auto" className="mb-2 text-sm leading-6 text-muted">{m.description}</p>}<ul>{m.lessons.map((l) => <LessonRow key={l.id} l={l} />)}</ul></div>}
                    </div>
                  ))}
                </div>
              </section>
            </>
          ) : (
            <article className="space-y-6">
              <button className="text-sm text-accent hover:underline" onClick={() => setSel(null)}><span className="inline-block rtl:-scale-x-100">←</span> {t('course.backToCourse')}</button>
              {lesson.isLoading ? <Loading label={t('common.loading')} /> : lesson.error || !lesson.data ? <ErrorState error={lesson.error} retry={lesson.refetch} /> : (
                <>
                  <div className="rounded-lg border border-accent/30 bg-accent/5 px-4 py-2.5 text-base">{t('course.previewNote')}</div>
                  <h2 dir="auto" className="text-3xl font-bold tracking-tight">{lesson.data.title}</h2>
                  {lesson.data.blocks.map((b) => <BlockView key={b.id} block={b} />)}
                  {lesson.data.summary && <section className="rounded-lg border border-accent/30 bg-accent/5 p-4"><h3 className="mb-1 text-sm font-semibold text-accent">{t('viewer.lessonSummary')}</h3><Markdown>{lesson.data.summary}</Markdown></section>}
                </>
              )}
              <div className="flex justify-between border-t border-line pt-4">
                <button className="btn text-base" disabled={idx <= 0} onClick={() => { const p = flat[idx - 1]; p && openLesson(p) }}><ChevronRight size={14} className="ltr:hidden" /><ChevronLeft size={14} className="rtl:hidden" /> {t('viewer.previous')}</button>
                <button className="btn btn-primary text-base" disabled={!next} onClick={() => next && openLesson(next)}>{t('viewer.next')} <ChevronRight size={14} className="ltr:hidden" /><ChevronLeft size={14} className="rtl:hidden" /></button>
              </div>
            </article>
          )}
        </div>

        <aside className="space-y-4 lg:sticky lg:top-24 lg:h-fit">
          <div className="card space-y-3 p-5">
            <div className="flex items-center justify-between"><Price c={c} big /><span className="rounded bg-accent/10 px-2 py-1 text-xs font-semibold text-accent">{accessLabel(c.access_days)}</span></div>
            {state?.has_access ? <Link to={`/courses/${id}`} className="btn btn-primary btn-lg w-full text-lg">{t('course.goToCourse')}</Link>
              : <Button className="btn-primary btn-lg w-full text-lg" onClick={() => setPaywall(true)}>{c.enrollment_type === 'free' ? t('course.enrollFree') : state?.enrollment_status === 'pending' ? t('course.pending') : t('course.requestPurchase')}</Button>}
            <p className="text-sm text-muted">{t('course.freeLessons', { n: c.free_lessons })} · {t('course.lessonsCount', { n: c.lesson_count })}</p>
          </div>
          {sel && (
            <nav className="card p-3"><h2 className="px-2 pb-2 pt-1 text-base font-semibold">{t('course.curriculum')}</h2>
              {c.outline.map((m, mi) => <div key={mi} className="mt-2"><div dir="auto" className="px-2 text-sm font-semibold text-muted">{m.title}</div><ul className="mt-1">{m.lessons.map((l) => <LessonRow key={l.id} l={l} />)}</ul></div>)}
            </nav>
          )}
        </aside>
      </div>

      <Modal open={paywall} onClose={() => setPaywall(false)} dir="rtl" title={<span className="inline-flex items-center gap-2"><GraduationCap size={16} /> {t('paywall.title')}</span>}
        footer={<button className="btn" onClick={() => setPaywall(false)}>{t('common.close')}</button>}>
        <div className="space-y-4 text-base leading-7">
          <p dir="auto" className="font-semibold">{c.title}</p>
          <p>{t('paywall.body', { n: locked })}</p>
          <p className="flex items-center gap-2"><span className="text-muted">{t('paywall.price')}:</span><Price c={c} big /></p>
          {!user ? (
            <>
              <p className="text-muted">{t('paywall.anonInfo')}</p>
              <div className="flex flex-wrap gap-2"><Link className="btn btn-primary btn-lg" to={`/register?next=${encodeURIComponent(`/course/${id}`)}`}>{t('course.registerToContinue')}</Link><Link className="btn btn-lg" to={`/login?next=${encodeURIComponent(`/course/${id}`)}`}>{t('course.loginToContinue')}</Link></div>
            </>
          ) : !isStudent ? <p className="text-muted">חשבון מורה אינו יכול לרכוש קורסים. התחברו כתלמיד כדי להמשיך.</p>
            : state?.has_access ? <Link className="btn btn-primary btn-lg" to={`/courses/${id}`}>{t('course.goToCourse')}</Link>
            : c.enrollment_type === 'free' ? (
              <><p className="text-muted">{t('paywall.freeInfo')}</p><Button className="btn-primary btn-lg" loading={enroll.isPending} onClick={() => enroll.mutate()}>{t('course.enrollFree')}</Button></>
            ) : state?.enrollment_status === 'pending' ? <p className="rounded-lg border border-good/40 bg-good/10 p-3 text-good">{request.isSuccess ? t('paywall.sentInfo') : t('paywall.pendingInfo')}</p>
            : state?.enrollment_status && !['expired'].includes(state.enrollment_status) ? <p className="text-muted">{t('course.statusChanged')}</p>
            : (
              <><p className="text-muted">{c.enrollment_type === 'manual' ? t('paywall.manualInfo') : t('paywall.requestInfo')}</p><Button className="btn-primary btn-lg" loading={request.isPending} onClick={() => request.mutate()}>{t('course.requestPurchase')}</Button></>
            )}
        </div>
      </Modal>
    </div>
  )
}
