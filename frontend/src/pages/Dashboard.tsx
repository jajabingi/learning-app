import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Flame, Play } from 'lucide-react'
import { get, post } from '@/api/client'
import type { Dashboard as D } from '@/api/types'
import { AccuracyChart, ActivityChart, MasteryBySubject, RetentionChart } from '@/components/charts'
import { useQuickCreate } from '@/components/QuickCreate'
import { Badge, Button, Empty, ErrorState, Loading, PageHeader, ProgressBar, Stat, cx } from '@/components/ui'
import { Page } from '@/components/Layout'
import { useAuth } from '@/contexts/auth'
import { useToast } from '@/contexts/toast'
import { REASONS, duration, pct, relTime } from '@/lib/format'
import { tt } from '@/i18n'

const ICON: Record<string, string> = { question: tt("Question"), note: tt("Note"), topic: tt("Topic"), session: tt("Session") }
const LINK: Record<string, (id: string) => string> = { question: (id) => `/questions/${id}`, note: (id) => `/notes/${id}`, topic: (id) => `/library/topic/${id}`, session: () => '/review' }

export default function Dashboard() {
  const { user } = useAuth()
  const nav = useNavigate()
  const qc = useQuickCreate()
  const toast = useToast()
  const q = useQuery({ queryKey: ['dashboard'], queryFn: () => get<D>('/dashboard') })
  const start = useMutation({
    mutationFn: () => post<{ id: string }>('/study/sessions', { mode: 'quick_recall', selection: 'due', count: 200, shuffle: false }),
    onSuccess: (s) => nav(`/study/session/${s.id}`), onError: (e) => toast.err(e instanceof Error ? e.message : tt("Could not start")),
  })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const d = q.data
  const t = d.totals
  const hour = new Date().getHours()
  const greet = hour < 12 ? tt('Good morning') : hour < 18 ? tt('Good afternoon') : tt('Good evening')

  if (t.subjects === 0 && t.questions === 0) {
    return (
      <Page narrow>
        <PageHeader title={tt("Welcome, {name}", { name: user?.display_name || tt('there') })} subtitle={tt("Everything you learn becomes organized knowledge. Everything you know can be tested. Everything you forget can be reviewed.")} />
        <ol className="space-y-3">
          {[[tt('Create a subject'), tt('e.g. “Finance” or “History” — the top level of your library.'), () => qc.open('subject'), tt('New subject')], [tt('Add topics'), tt('Break the subject into topics and subtopics.'), () => qc.open('topic'), tt('New topic')], [tt('Write questions'), tt('Add your first questions and answers, then start studying.'), () => qc.open('question'), tt('New question')]].map(([title, desc, fn, cta], i) => (
            <li key={i} className="card flex items-center gap-4 p-4"><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/10 text-sm font-semibold text-accent">{i + 1}</span><div className="min-w-0 flex-1"><div className="text-sm font-medium">{title as string}</div><div className="text-sm text-muted">{desc as string}</div></div><button className="btn" onClick={fn as () => void}>{cta as string}</button></li>
          ))}
        </ol>
      </Page>
    )
  }

  const goal = Math.min(1, t.reviewed_today / Math.max(1, t.daily_goal))
  return (
    <Page>
      <PageHeader title={`${greet}${user?.display_name ? `, ${user.display_name}` : ''}`} subtitle={tt("Here is where your knowledge stands today.")} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={tt("Subjects")} value={t.subjects} /><Stat label={tt("Topics")} value={t.topics} /><Stat label={tt("Questions")} value={t.questions} />
        <Stat label={tt("Mastered")} value={t.mastered} hint={t.questions ? tt("{pct} of questions", { pct: pct(t.mastered / t.questions) }) : undefined} tone="good" />
        <Stat label={tt("Needs review")} value={t.needs_review} hint={tt("Due or still learning")} tone={t.needs_review ? 'warn' : undefined} />
        <Stat label={tt("Reviews due today")} value={t.due_today} tone={t.due_today ? 'warn' : undefined} />
        <Stat label={tt("Learning streak")} value={<span className="inline-flex items-center gap-1.5"><Flame size={20} className={t.streak ? 'text-warn' : 'text-faint'} />{t.streak}</span>} hint={tt(t.longest_streak === 1 ? "Longest {n} day" : "Longest {n} days", { n: t.longest_streak })} />
        <Stat label={tt("Overall mastery")} value={pct(t.mastery)} hint={tt("Across all questions")} />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <section className="card flex flex-col p-5 lg:col-span-1">
          <h2 className="h-section text-muted">{tt("Review today")}</h2>
          <div className="mt-2 tabnum text-4xl font-semibold tracking-tight">{d.review_today.due}</div>
          <p className="text-sm text-muted">{d.review_today.due ? tt("due · about {estimated_seconds}", { estimated_seconds: duration(d.review_today.estimated_seconds) }) : tt("nothing due — you’re caught up")}</p>
          <div className="mt-4"><div className="mb-1 flex justify-between text-xs text-muted"><span>{tt("Daily goal")}</span><span className="tabnum">{t.reviewed_today} / {t.daily_goal}</span></div><ProgressBar value={goal} tone="accent" label={tt("Daily goal")} /></div>
          <div className="mt-auto flex flex-wrap gap-2 pt-5">
            <Button className="btn-primary btn-lg flex-1" disabled={!d.review_today.due} loading={start.isPending} onClick={() => start.mutate()}><Play size={16} /> {tt("Start review")}</Button>
            {d.review_today.new_available > 0 && <Link to="/study" className="btn btn-lg">{tt("Learn new (")}{d.review_today.new_available})</Link>}
          </div>
        </section>

        <section className="card p-5 lg:col-span-2">
          <h2 className="h-section mb-3">{tt("Continue learning")}</h2>
          {d.continue_learning.length === 0 ? <Empty title={tt("Nothing studied yet")}>{tt("Topics you study will show up here so you can jump back in.")}</Empty> : (
            <ul className="divide-y divide-line">
              {d.continue_learning.map((c) => (
                <li key={c.topic_id} className="flex items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1"><Link to={`/library/topic/${c.topic_id}`} className="block truncate text-sm font-medium hover:underline">{c.name}</Link><div className="mt-1 flex items-center gap-2"><div className="w-28"><ProgressBar value={c.mastery} label={tt("{name} mastery", { name: c.name })} /></div><span className="text-xs text-muted tabnum">{pct(c.mastery)} · {c.questions} {tt("Q · studied")} {relTime(c.last_studied)}</span></div></div>
                  {c.due > 0 && <Badge tone="warn">{c.due} {tt("due")}</Badge>}
                  <Link to={`/study?topic=${c.topic_id}`} className="btn">{tt("Resume")}</Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <section className="card p-5">
          <h2 className="h-section mb-3">{tt("Knowledge overview")}</h2>
          {d.subjects.length === 0 ? <p className="text-sm text-muted">{tt("No subjects yet.")}</p> : (
            <ul className="space-y-3">
              {d.subjects.map((s) => (
                <li key={s.id}><div className="mb-1 flex items-center justify-between text-sm"><Link to={`/library/subject/${s.id}`} className="flex items-center gap-2 font-medium hover:underline"><span className="h-2 w-2 rounded-full" style={{ background: s.color }} />{s.name}</Link><span className="text-xs text-muted tabnum">{s.questions} Q · {pct(s.mastery)}</span></div>
                  <Distribution s={s} /></li>
              ))}
              <li className="flex flex-wrap gap-x-3 gap-y-1 pt-1 text-xs text-muted">{[['bg-faint/40', 'New'], ['bg-warn', 'Learning'], ['bg-accent', 'Reviewing'], ['bg-good', 'Mastered']].map(([c, l]) => <span key={l} className="inline-flex items-center gap-1"><span className={cx('h-2 w-2 rounded-sm', c)} />{l}</span>)}</li>
            </ul>
          )}
        </section>

        <section className="card p-5">
          <h2 className="h-section mb-1">{tt("Weak areas")}</h2>
          <p className="mb-3 text-xs text-muted">{tt("Topics with low accuracy, low mastery, repeated mistakes, forgotten answers or too little practice.")}</p>
          {d.weak_areas.length === 0 ? <p className="text-sm text-muted">{tt("No weak areas detected yet. They appear once you have enough review history.")}</p> : (
            <ul className="divide-y divide-line">
              {d.weak_areas.map((w) => (
                <li key={w.topic_id} className="py-2.5"><div className="flex items-center justify-between gap-2"><Link to={`/library/topic/${w.topic_id}`} className="truncate text-sm font-medium hover:underline">{w.name}</Link><Link to={`/study?topic=${w.topic_id}`} className="text-xs text-accent underline">{tt("Practice")}</Link></div>
                  <div className="mt-1 flex flex-wrap gap-1">{w.reasons.map((r) => <Badge key={r} tone={r === 'insufficient_practice' ? 'neutral' : 'warn'}>{REASONS[r] ?? r}</Badge>)}</div>
                  <div className="mt-1 text-xs text-muted tabnum">{tt("Mastery")} {pct(w.mastery)} {tt("· accuracy")} {pct(w.accuracy)} · {w.reviews} {tt("reviews")}</div></li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <h2 className="h-section mb-2 mt-6">{tt("Learning progress")}</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <ActivityChart data={d.activity_series} /><AccuracyChart data={d.activity_series} /><MasteryBySubject data={d.subjects} /><RetentionChart data={d.retention_trend} />
      </div>

      <section className="card mt-5 p-5">
        <h2 className="h-section mb-3">{tt("Recent activity")}</h2>
        {d.recent_activity.length === 0 ? <p className="text-sm text-muted">{tt("Nothing yet.")}</p> : (
          <ul className="divide-y divide-line">{d.recent_activity.map((a) => (
            <li key={`${a.type}-${a.id}`}><Link to={LINK[a.type](a.id)} className="flex items-center gap-3 py-2 text-sm hover:bg-raised/60"><Badge>{ICON[a.type]}</Badge><span className="min-w-0 flex-1 truncate">{a.title}</span><span className="shrink-0 text-xs text-muted">{relTime(a.at)}</span></Link></li>
          ))}</ul>
        )}
      </section>
    </Page>
  )
}

function Distribution({ s }: { s: D['subjects'][number] }) {
  const total = Math.max(1, s.questions)
  const seg = [['bg-faint/40', s.new + s.suspended], ['bg-warn', s.learning], ['bg-accent', s.reviewing], ['bg-good', s.mastered]] as const
  return <div className="flex h-2 overflow-hidden rounded-full bg-raised" role="img" aria-label={tt("{new} new, {learning} learning, {reviewing} reviewing, {mastered} mastered", { new: s.new, learning: s.learning, reviewing: s.reviewing, mastered: s.mastered })}>{seg.map(([c, n], i) => n > 0 && <div key={i} className={c} style={{ width: `${(n / total) * 100}%` }} />)}</div>
}
