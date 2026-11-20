import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CalendarCheck, Play } from 'lucide-react'
import { get, post } from '@/api/client'
import type { ReviewQueue as Queue } from '@/api/types'
import { Badge, Button, Empty, ErrorState, Loading, PageHeader, ProgressBar, Stat, StatusBadge } from '@/components/ui'
import { Page } from '@/components/Layout'
import { useToast } from '@/contexts/toast'
import { duration, relTime, shortDate } from '@/lib/format'
import { tt, tl } from '@/i18n'

export default function ReviewQueue() {
  const nav = useNavigate()
  const toast = useToast()
  const q = useQuery({ queryKey: ['review-queue'], queryFn: () => get<Queue>('/review/queue', { limit: 100 }), refetchInterval: 60_000 })
  const start = useMutation({
    mutationFn: (count: number) => post<{ id: string }>('/study/sessions', { mode: 'quick_recall', selection: 'due', count, shuffle: false }),
    onSuccess: (s) => nav(`/study/session/${s.id}`),
    onError: (e) => toast.err(e instanceof Error ? e.message : tt("Could not start")),
  })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const d = q.data
  const nextUp = d.upcoming.find((u) => u.count > 0)

  return (
    <Page>
      <PageHeader title={tt("Review Queue")} subtitle={tt("Questions the scheduler says you are about to forget. Reviewing them on time keeps memory strong with the least effort.")} />
      <section className="card mb-5 flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
        <div className="flex-1">
          <div className="tabnum text-4xl font-semibold tracking-tight">{d.due_now}</div>
          <div className="text-sm text-muted">{d.due_now === 1 ? tt("question") : tt("questions")} {tt("due now")}{d.overdue > 0 && <> · <span className="text-warn">{d.overdue} {tt("overdue")}</span></>}{d.due_now > 0 && <> {tt("· about")} {duration(d.estimated_seconds)}</>}</div>
          {d.due_now === 0 && <p className="mt-1 text-sm text-muted">{nextUp ? tt("Next reviews: {n} on {date}.", { n: nextUp.count, date: shortDate(nextUp.date) }) : tt("Nothing scheduled yet — study some new questions to get started.")}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button className="btn-primary btn-lg" disabled={!d.due_now} loading={start.isPending} onClick={() => start.mutate(Math.min(d.due_now, 200))}><Play size={16} /> {tt("Start review")}</Button>
          {d.due_now > 25 && <Button className="btn-lg" disabled={start.isPending} onClick={() => start.mutate(25)}>{tt("Do 25")}</Button>}
          {d.due_now === 0 && d.new_available > 0 && <Link className="btn btn-lg" to="/study">{tt("Learn new questions")}</Link>}
        </div>
      </section>

      {d.open_sessions.length > 0 && (
        <section className="card mb-5 p-4">
          <h2 className="h-section mb-2">{tt("Unfinished sessions")}</h2>
          <ul className="divide-y divide-line">{d.open_sessions.map((s) => (
            <li key={s.id} className="flex items-center gap-3 py-2 text-sm"><div className="min-w-0 flex-1"><span className="font-medium capitalize">{tl(s.mode.replace('_', ' '))}</span> <Badge tone={s.status === 'paused' ? 'warn' : 'neutral'}>{s.status}</Badge><div className="text-xs text-muted">{s.answered} {tt("of")} {s.total} {tt("answered · last activity")} {relTime(s.last_activity_at)}</div></div><Link className="btn btn-primary" to={`/study/session/${s.id}`}>{tt("Resume")}</Link></li>
          ))}</ul>
        </section>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={tt("Reviewed today")} value={d.reviewed_today} hint={`Goal ${d.daily_goal}`} />
        <Stat label={tt("Review completion today")} value={`${Math.round(d.completion_today * 100)}%`} hint={tt("Done ÷ (done + still due)")} />
        <Stat label={tt("Overdue")} value={d.overdue} tone={d.overdue ? 'warn' : undefined} />
        <Stat label={tt("New available today")} value={d.new_available} hint={tt("Within your daily new limit")} />
      </div>
      <ProgressBar value={Math.min(1, d.reviewed_today / Math.max(1, d.daily_goal))} tone="accent" className="mb-6" label={tt("Daily goal progress")} />

      <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
        <section>
          <h2 className="h-section mb-2">{tt("Due now")}</h2>
          {d.items.length === 0 ? <div className="card"><Empty title={tt("You’re all caught up")} icon={<CalendarCheck size={28} />}>{tt("No reviews are due. Come back later or study new material.")}</Empty></div> : (
            <ul className="card divide-y divide-line">
              {d.items.map((i) => (
                <li key={i.question_id}><Link to={`/questions/${i.question_id}`} className="flex items-center gap-3 px-3 py-2.5 hover:bg-raised/60">
                  <span className="min-w-0 flex-1 truncate text-sm">{i.title || tt("Untitled question")}</span>
                  {i.overdue_days > 0 ? <Badge tone="warn">{i.overdue_days}{tt("d overdue")}</Badge> : <span className="text-xs text-muted">{tt("due")} {relTime(i.due_at)}</span>}
                  <StatusBadge status={i.status} compact />
                </Link></li>
              ))}
            </ul>
          )}
          {d.due_now > d.items.length && <p className="mt-2 text-xs text-muted">{tt("Showing the")} {d.items.length} {tt("most overdue of")} {d.due_now}.</p>}
        </section>
        <section>
          <h2 className="h-section mb-2">{tt("Upcoming (14 days)")}</h2>
          <div className="card p-3"><div className="h-52"><ResponsiveContainer><BarChart data={d.upcoming.map((u) => ({ ...u, label: shortDate(u.date) }))}>
            <CartesianGrid vertical={false} stroke="rgb(var(--line))" /><XAxis dataKey="label" interval={1} tick={{ fontSize: 10, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} /><YAxis allowDecimals={false} width={24} tick={{ fontSize: 10, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ background: 'rgb(var(--surface))', border: '1px solid rgb(var(--line))', borderRadius: 6, fontSize: 12 }} cursor={{ fill: 'rgb(var(--raised))' }} /><Bar dataKey="count" name="Reviews due" fill="rgb(var(--accent))" radius={[3, 3, 0, 0]} />
          </BarChart></ResponsiveContainer></div></div>
          <p className="mt-2 text-xs text-muted">{tt("Estimated")} {d.seconds_per_review}{tt("s per review, based on your own history.")}</p>
        </section>
      </div>
    </Page>
  )
}
