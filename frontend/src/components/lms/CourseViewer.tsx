import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CheckCircle2, ChevronLeft, ChevronRight, Circle, Menu as MenuIcon } from 'lucide-react'
import { get, post } from '@/api/client'
import type { Block, LessonBrief, LessonDetail, ModuleNode } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { Badge, Button, ErrorState, Loading, ProgressBar, cx } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { duration } from '@/lib/format'
import { t } from '@/i18n'
import { BlockView } from './BlockView'

type L = LessonBrief & { completed?: boolean }
type M = Omit<ModuleNode, 'lessons'> & { lessons: L[] }
export interface StudentProgress { percent: number; completed_lessons: number; total_lessons: number; resume_lesson_id: string | null; next_lesson_id: string | null; time_spent_seconds: number }
interface CourseLike { id?: string; title: string; subtitle?: string; description?: string; summary?: string; objectives?: string[]; requirements?: string[]; target_audience?: string; instructor_name?: string; curriculum: M[]; progress?: StudentProgress }

/** Course view (curriculum sidebar + lesson content). Used by the teacher preview (no tracking) and the student
 * portal (`student` = true: progress is saved on the server and lessons can be marked complete). */
export function CourseViewer({ course, lessonPath, showDraftFlags, student, initialLesson }: { course: CourseLike; lessonPath: (id: string) => string; showDraftFlags?: boolean; student?: boolean; initialLesson?: string | null }) {
  const flat = useMemo(() => course.curriculum.flatMap((m) => m.lessons.map((l) => ({ ...l, module: m.title }))), [course])
  const [sel, setSel] = useState<string | null>(initialLesson ?? null)
  const [nav, setNav] = useState(false)
  const idx = flat.findIndex((l) => l.id === sel)
  useEffect(() => { if (sel && !flat.some((l) => l.id === sel)) setSel(null) }, [flat, sel])
  const go = (l?: { id: string }) => { if (l) { setSel(l.id); setNav(false); window.scrollTo?.(0, 0) } }
  const p = course.progress

  const menu = (
    <nav aria-label={t('viewer.curriculumBtn')} className="space-y-3">
      {student && p && <div className="px-2"><div className="mb-1 flex justify-between text-xs text-muted tabnum"><span>{t('viewer.progress')}</span><span>{p.percent}%</span></div><ProgressBar value={p.percent / 100} tone="accent" label="Course progress" /></div>}
      <button className={cx('block w-full rounded px-2.5 py-2 text-start text-[16px] leading-6 font-medium', !sel ? 'bg-raised' : 'hover:bg-raised/70')} onClick={() => { setSel(null); setNav(false) }}>{t('viewer.overview')}</button>
      {course.curriculum.map((m) => (
        <div key={m.id}>
          <div className="px-2.5 text-sm font-semibold tracking-wide text-muted">{m.title}{showDraftFlags && m.is_published === false && <Badge tone="warn" className="ms-1.5 normal-case">{t('viewer.draft')}</Badge>}</div>
          <ul className="mt-1">{m.lessons.map((l) => (
            <li key={l.id}><button onClick={() => go(l)} className={cx('flex w-full items-center gap-2 rounded px-2.5 py-2 text-start text-[16px] leading-6', sel === l.id ? 'bg-raised font-medium' : 'hover:bg-raised/70')}>
              {student && (l.completed ? <CheckCircle2 size={14} className="shrink-0 text-good" aria-label={t('viewer.completed')} /> : <Circle size={14} className="shrink-0 text-faint" aria-label={t('viewer.notCompleted')} />)}
              <span className="min-w-0 flex-1 truncate">{l.title}</span>{showDraftFlags && l.is_published === false && <Badge tone="warn">{t('viewer.draft')}</Badge>}
            </button></li>
          ))}</ul>
        </div>
      ))}
    </nav>
  )

  return (
    <div className="flex gap-6">
      <aside className="hidden w-80 shrink-0 lg:block">{menu}</aside>
      {nav && <div className="fixed inset-0 z-40 lg:hidden"><div className="absolute inset-0 bg-black/40" onClick={() => setNav(false)} /><div className="absolute inset-y-0 start-0 w-80 max-w-[88%] overflow-y-auto bg-surface p-4 shadow-xl">{menu}</div></div>}
      <div className="min-w-0 flex-1">
        <button className="btn mb-3 lg:hidden" onClick={() => setNav(true)}><MenuIcon size={14} /> {t('viewer.curriculumBtn')}</button>
        {!sel ? <Overview course={course} student={student} onStart={(id) => go(id ? { id } : flat[0])} /> : <Lesson key={sel} id={sel} path={lessonPath(sel)} student={student} courseId={course.id} nextId={flat[idx + 1]?.id} onNext={() => go(flat[idx + 1])} />}
        {sel && (
          <div className="mt-8 flex justify-between border-t border-line pt-4">
            <button className="btn" disabled={idx <= 0} onClick={() => go(flat[idx - 1])}><ChevronRight size={14} className="ltr:hidden" /><ChevronLeft size={14} className="rtl:hidden" /> {t('viewer.previous')}</button>
            <button className="btn btn-primary" disabled={idx >= flat.length - 1} onClick={() => go(flat[idx + 1])}>{t('viewer.next')} <ChevronRight size={14} className="ltr:hidden" /><ChevronLeft size={14} className="rtl:hidden" /></button>
          </div>
        )}
      </div>
    </div>
  )
}

function Overview({ course, onStart, student }: { course: CourseLike; onStart(id?: string): void; student?: boolean }) {
  const p = course.progress
  const list = (title: string, items?: string[]) => items && items.length > 0 && <div><h3 dir="auto" className="h-section mb-1">{title}</h3><ul className="list-disc space-y-0.5 pl-5 text-sm">{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
  return (
    <div className="space-y-5">
      <div><h2 dir="auto" className="text-2xl font-semibold tracking-tight">{course.title}</h2>{course.subtitle && <p className="mt-1 text-muted">{course.subtitle}</p>}{course.instructor_name && <p dir="auto" className="mt-1 text-sm text-muted">{t('course.by')} {course.instructor_name}</p>}</div>
      {student && p && (
        <div className="card p-4"><div className="mb-1 flex justify-between text-sm"><span className="font-medium">{t('viewer.percentDone', { n: p.percent })}</span><span className="text-muted tabnum">{t('viewer.lessonsStudied', { a: p.completed_lessons, b: p.total_lessons, t: duration(p.time_spent_seconds) })}</span></div><ProgressBar value={p.percent / 100} tone="accent" label="Course progress" />
          {p.percent >= 100 && <p className="mt-2 text-sm text-good">{t('viewer.courseCompleted')}</p>}</div>
      )}
      {course.description && <Markdown>{course.description}</Markdown>}
      <div className="grid gap-4 sm:grid-cols-2">{list(t('viewer.whatYouLearn'), course.objectives)}{list(t('viewer.requirements'), course.requirements)}</div>
      {course.target_audience && <div><h3 dir="auto" className="h-section mb-1">{t('viewer.audience')}</h3><p className="text-sm">{course.target_audience}</p></div>}
      {course.summary && <section className="rounded-lg border border-accent/30 bg-accent/5 p-4"><h3 dir="auto" className="h-section mb-1 text-accent">{t('viewer.courseSummary')}</h3><Markdown>{course.summary}</Markdown></section>}
      <button className="btn btn-primary btn-lg" onClick={() => onStart(student ? (p?.resume_lesson_id ?? undefined) : undefined)}>{student && p && p.completed_lessons > 0 && p.percent < 100 ? t('viewer.continueWhere') : t('viewer.startFirst')}</button>
    </div>
  )
}

function Lesson({ id, path, student, courseId, onNext, nextId }: { id: string; path: string; student?: boolean; courseId?: string; onNext(): void; nextId?: string }) {
  const q = useQuery({ queryKey: ['lesson-view', path], queryFn: () => get<LessonDetail & { completed?: boolean }>(path) })
  const qc = useQueryClient()
  const toast = useToast()
  const [done, setDone] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const loaded = !!q.data

  // Save progress: mark as opened immediately, then add active study time every 30s while the tab is visible.
  const last = useRef(Date.now())
  useEffect(() => {
    if (!student || !loaded) return
    const send = (s: number) => post(`/student/lessons/${id}/progress`, { seconds: Math.min(120, s) }).catch(() => {})
    send(0)
    last.current = Date.now()
    const t = setInterval(() => {
      if (document.visibilityState !== 'visible') { last.current = Date.now(); return }
      const s = Math.round((Date.now() - last.current) / 1000)
      last.current = Date.now()
      send(s)
    }, 30_000)
    return () => { clearInterval(t); if (document.visibilityState === 'visible') send(Math.min(120, Math.round((Date.now() - last.current) / 1000))) ; qc.invalidateQueries({ queryKey: ['student-course'] }); qc.invalidateQueries({ queryKey: ['student-dashboard'] }) }
  }, [student, loaded, id, qc])

  async function toggle() {
    setBusy(true)
    try {
      const next = !(done ?? q.data?.completed)
      const r = await post<{ course_completed: boolean; course_percent: number }>(`/student/lessons/${id}/complete`, { completed: next })
      setDone(next)
      qc.invalidateQueries({ queryKey: ['student-course', courseId] })
      qc.invalidateQueries({ queryKey: ['student-courses'] })
      if (next) toast.ok(r.course_completed ? t('viewer.courseDone') : t('viewer.lessonDone', { n: r.course_percent }))
    } catch (e) { toast.err(e instanceof Error ? e.message : t('common.somethingWrong')) } finally { setBusy(false) }
  }

  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const l = q.data
  const completed = done ?? !!l.completed
  return (
    <article className="space-y-6" data-lesson={id}>
      <header><h2 dir="auto" className="text-2xl font-semibold tracking-tight">{l.title}</h2>{l.estimated_minutes > 0 && <p className="text-sm text-muted">{l.estimated_minutes} {t('viewer.min')}</p>}</header>
      {l.blocks.length === 0 && <p className="text-sm text-muted">{t('viewer.noContent')}</p>}
      {l.blocks.map((b: Block) => <BlockView key={b.id} block={b} />)}
      {l.summary && <section className="rounded-lg border border-accent/30 bg-accent/5 p-4"><h3 dir="auto" className="h-section mb-1 text-accent">{t('viewer.lessonSummary')}</h3><Markdown>{l.summary}</Markdown></section>}
      {student && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface p-3">
          <Button className={completed ? '' : 'btn-primary'} loading={busy} onClick={toggle}>{completed ? <><Check size={14} /> {t('viewer.completedUndo')}</> : t('viewer.markComplete')}</Button>
          {completed && nextId && <button className="btn btn-primary" onClick={onNext}>{t('viewer.next')} <ChevronRight size={14} className="ltr:hidden" /><ChevronLeft size={14} className="rtl:hidden" /></button>}
          <span className="text-xs text-muted">{t('viewer.autosaved')}</span>
        </div>
      )}
    </article>
  )
}
