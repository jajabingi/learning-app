import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { get } from '@/api/client'
import type { Analytics } from '@/api/types'
import { AccuracyChart, ActivityChart, MasteryBySubject, MinutesChart, RetentionChart } from '@/components/charts'
import { Badge, ErrorState, Loading, PageHeader, ProgressBar, Segmented, Stat } from '@/components/ui'
import { Page } from '@/components/Layout'
import { REASONS, pct } from '@/lib/format'
import { tt } from '@/i18n'

const DEFS: [string, string, string][] = [
  ['accuracy', tt("Accuracy"), 'text-accent'], ['retention', tt("Retention"), 'text-warn'], ['mastery', tt("Mastery"), 'text-good'], ['completion', tt("Completion"), 'text-fg'], ['activity', tt("Activity"), 'text-muted'],
]

export default function AnalyticsPage() {
  const [days, setDays] = useState(30)
  const q = useQuery({ queryKey: ['analytics', days], queryFn: () => get<Analytics>('/analytics', { days }) })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const a = q.data
  const s = a.summary

  return (
    <Page>
      <PageHeader title={tt("Analytics")} subtitle={tt("Each metric below measures something different — they are deliberately kept apart.")}
        actions={<Segmented label={tt("Period")} value={String(days)} onChange={(v) => setDays(Number(v))} options={[{ value: '7', label: tt("7 days") }, { value: '30', label: tt("30 days") }, { value: '90', label: tt("90 days") }, { value: '365', label: tt("1 year") }]} />} />

      <Group title={tt("Knowledge")} hint={tt("How much you currently know, regardless of when you studied.")}>
        <Stat label={tt("Total questions")} value={s.total_questions} /><Stat label={tt("Mastery")} value={pct(s.mastery)} hint={tt("Recall × maturity, all questions")} /><Stat label={tt("Mastered questions")} value={s.mastered} hint={s.total_questions ? tt("{pct} of bank", { pct: pct(s.mastered / s.total_questions) }) : undefined} tone="good" /><Stat label={tt("Strength by state")} value={<span className="text-sm font-normal">{a.status_distribution.new} {tt("new ·")} {a.status_distribution.learning} {tt("learning ·")} {a.status_distribution.reviewing} {tt("reviewing")}</span>} />
      </Group>
      <Group title={tt("Accuracy & retention")} hint={tt("Last {days} days.", { days })}>
        <Stat label={tt("Overall accuracy")} value={pct(s.accuracy)} hint={tt("{n} answers", { n: s.reviews })} /><Stat label={tt("Retention")} value={pct(s.retention)} hint={s.retention_sample ? tt("{n} reviews of learned questions", { n: s.retention_sample }) : tt("Needs reviews of learned questions")} /><Stat label={tt("Questions answered")} value={s.questions_answered} hint={tt("Distinct questions")} /><Stat label={tt("Review completion")} value={pct(s.completion_rate)} hint={tt("Due reviews actually done")} />
      </Group>
      <Group title={tt("Activity")} hint={tt("Effort only — not a measure of knowledge.")}>
        <Stat label={tt("Current streak")} value={tt(s.streak === 1 ? "{n} day" : "{n} days", { n: s.streak })} hint={tt("Longest {n}", { n: s.longest_streak })} /><Stat label={tt("Study time")} value={`${s.study_minutes < 60 ? Math.round(s.study_minutes) + ' ' + tt('min') : (s.study_minutes / 60).toFixed(1) + ' ' + tt('h')}`} /><Stat label={tt("Active days")} value={`${s.active_days} / ${days}`} /><Stat label={tt("Answers per active day")} value={s.active_days ? Math.round(s.reviews / s.active_days) : '—'} />
      </Group>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <ActivityChart data={a.daily} /><AccuracyChart data={a.daily} /><RetentionChart data={a.retention_trend} /><MinutesChart data={a.daily} />
        <MasteryBySubject data={a.subjects} />
      </div>

      <section className="card mt-6 overflow-x-auto">
        <h2 className="h-section px-4 pt-4">{tt("Subject performance")}</h2>
        <table className="mt-2 w-full min-w-[640px] text-sm">
          <thead><tr className="border-b border-line text-start text-xs text-muted"><Th>{tt("Subject")}</Th><Th r>{tt("Questions")}</Th><Th r>{tt("Mastery")}</Th><Th r>{tt("Accuracy")}</Th><Th r>{tt("Retention")}</Th><Th r>{tt("Reviews")}</Th><Th r>{tt("Due")}</Th></tr></thead>
          <tbody>{a.subjects.map((x) => <tr key={x.id} className="border-b border-line last:border-0"><td className="px-4 py-2"><Link to={`/library/subject/${x.id}`} className="flex items-center gap-2 font-medium hover:underline"><span className="h-2 w-2 rounded-full" style={{ background: x.color }} />{x.name}</Link></td><Td>{x.questions}</Td><Td><span className="inline-flex items-center gap-2"><span className="w-14"><ProgressBar value={x.mastery} label={tt("Mastery")} /></span>{pct(x.mastery)}</span></Td><Td>{pct(x.accuracy)}</Td><Td>{pct(x.retention)}</Td><Td>{x.reviews}</Td><Td>{x.due}</Td></tr>)}
            {a.subjects.length === 0 && <tr><td colSpan={7} className="px-4 py-6 text-center text-muted">{tt("No subjects yet.")}</td></tr>}</tbody>
        </table>
      </section>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Rank title={tt("Strongest subjects")} items={a.strongest_subjects} />
        <Rank title={tt("Weakest subjects")} items={a.weakest_subjects} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <section className="card p-4"><h2 className="h-section mb-2">{tt("Topic performance (weakest first)")}</h2>
          {a.topics.length === 0 ? <p className="text-sm text-muted">{tt("Link questions to topics to see topic-level performance.")}</p> : (
            <ul className="max-h-96 divide-y divide-line overflow-y-auto">{a.topics.map((t) => <li key={t.topic_id} className="flex items-center gap-3 py-2 text-sm"><Link to={`/library/topic/${t.topic_id}`} className="min-w-0 flex-1 truncate hover:underline">{t.name}</Link><span className="w-12 text-xs text-muted tabnum">{t.questions} Q</span><span className="w-24"><ProgressBar value={t.mastery} label={tt("Mastery")} /></span><span className="w-10 text-end text-xs tabnum">{pct(t.mastery)}</span></li>)}</ul>
          )}
        </section>
        <section className="card p-4"><h2 className="h-section mb-2">{tt("Most frequently forgotten")}</h2>
          {a.most_forgotten.length === 0 ? <p className="text-sm text-muted">{tt("No lapses yet — that’s a good sign.")}</p> : (
            <ul className="divide-y divide-line">{a.most_forgotten.map((m) => <li key={m.question_id} className="flex items-center gap-3 py-2 text-sm"><Link to={`/questions/${m.question_id}`} className="min-w-0 flex-1 truncate hover:underline">{m.title || tt("Untitled question")}</Link><Badge tone="bad">{m.lapses} {tt("lapse")}{m.lapses === 1 ? '' : 's'}</Badge><span className="w-16 text-end text-xs text-muted tabnum">{m.reviews} {tt("reviews")}</span></li>)}</ul>
          )}
        </section>
      </div>

      {a.weak_topics.length > 0 && (
        <section className="card mt-6 p-4"><h2 className="h-section mb-2">{tt("Weak topics")}</h2>
          <ul className="divide-y divide-line">{a.weak_topics.map((w) => <li key={w.topic_id} className="flex flex-wrap items-center gap-2 py-2 text-sm"><Link to={`/library/topic/${w.topic_id}`} className="font-medium hover:underline">{w.name}</Link>{w.reasons.map((r) => <Badge key={r} tone="warn">{REASONS[r] ?? r}</Badge>)}<Link to={`/study?topic=${w.topic_id}`} className="ml-auto text-xs text-accent underline">{tt("Practice")}</Link></li>)}</ul>
        </section>
      )}

      <section className="card mt-6 p-4">
        <h2 className="h-section mb-2">{tt("What the metrics mean")}</h2>
        <dl className="grid gap-x-6 gap-y-2 text-sm md:grid-cols-2">{DEFS.map(([k, label, c]) => <div key={k}><dt className={`font-medium ${c}`}>{label}</dt><dd className="text-muted">{tt(a.definitions[k])}</dd></div>)}</dl>
      </section>
    </Page>
  )
}

const Th = ({ children, r }: { children: React.ReactNode; r?: boolean }) => <th className={`px-4 py-2 font-medium ${r ? 'text-end' : ''}`}>{children}</th>
const Td = ({ children }: { children: React.ReactNode }) => <td className="px-4 py-2 text-end tabnum">{children}</td>

function Group({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return <section className="mt-5 first:mt-0"><div className="mb-2 flex items-baseline gap-2"><h2 className="h-section">{title}</h2><span className="text-xs text-muted">{hint}</span></div><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div></section>
}

function Rank({ title, items }: { title: string; items: Analytics['strongest_subjects'] }) {
  return (
    <section className="card p-4"><h2 className="h-section mb-2">{title}</h2>
      {items.length === 0 ? <p className="text-sm text-muted">{tt("Study a few questions to see a ranking.")}</p> : <ul className="space-y-2">{items.map((s) => <li key={s.id} className="flex items-center gap-3 text-sm"><span className="h-2 w-2 rounded-full" style={{ background: s.color }} /><span className="flex-1 truncate">{s.name}</span><span className="w-24"><ProgressBar value={s.mastery} label={tt("Mastery")} /></span><span className="w-10 text-end tabnum">{pct(s.mastery)}</span></li>)}</ul>}
    </section>
  )
}
