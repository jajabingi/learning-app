import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { shortDate } from '@/lib/format'
import type { DailyPoint, SubjectStat } from '@/api/types'
import { tt } from '@/i18n'

const tick = { fontSize: 11, fill: 'rgb(var(--muted))' }
const tip = { contentStyle: { background: 'rgb(var(--surface))', border: '1px solid rgb(var(--line))', borderRadius: 6, fontSize: 12 }, labelStyle: { color: 'rgb(var(--muted))' }, cursor: { stroke: 'rgb(var(--line))' } }
const Grid = () => <CartesianGrid vertical={false} stroke="rgb(var(--line))" />

export function ChartBox({ title, note, children, empty }: { title: string; note?: string; children: React.ReactNode; empty?: boolean }) {
  return (
    <section className="card p-4">
      <h3 className="h-section">{title}</h3>
      {note && <p className="mb-2 text-xs text-muted">{note}</p>}
      <div className="mt-2 h-48">{empty ? <div className="flex h-full items-center justify-center text-sm text-muted">{tt("Not enough data yet")}</div> : <ResponsiveContainer width="100%" height="100%">{children as React.ReactElement}</ResponsiveContainer>}</div>
    </section>
  )
}

const withLabel = (d: DailyPoint[]) => d.map((x) => ({ ...x, label: shortDate(x.date), accuracyPct: x.accuracy === null ? null : Math.round(x.accuracy * 100) }))

export function ActivityChart({ data }: { data: DailyPoint[] }) {
  return (
    <ChartBox title={tt("Questions answered per day")} note={tt("Activity — volume only, not a measure of knowledge")} empty={!data.some((d) => d.reviews)}>
      <AreaChart data={withLabel(data)} margin={{ left: -16, right: 4 }}><Grid /><XAxis dataKey="label" tick={tick} tickLine={false} axisLine={false} minTickGap={24} /><YAxis allowDecimals={false} tick={tick} tickLine={false} axisLine={false} /><Tooltip {...tip} />
        <Area type="monotone" dataKey="reviews" name="Answered" stroke="rgb(var(--accent))" fill="rgb(var(--accent))" fillOpacity={0.12} strokeWidth={2} /></AreaChart>
    </ChartBox>
  )
}

export function AccuracyChart({ data }: { data: DailyPoint[] }) {
  return (
    <ChartBox title={tt("Accuracy over time")} note={tt("Share of answers not rated “Again”, by day")} empty={!data.some((d) => d.accuracy !== null)}>
      <LineChart data={withLabel(data)} margin={{ left: -16, right: 4 }}><Grid /><XAxis dataKey="label" tick={tick} tickLine={false} axisLine={false} minTickGap={24} /><YAxis domain={[0, 100]} unit="%" tick={tick} tickLine={false} axisLine={false} /><Tooltip {...tip} formatter={(v: number) => `${v}%`} />
        <Line type="monotone" dataKey="accuracyPct" name="Accuracy" stroke="rgb(var(--good))" strokeWidth={2} dot={{ r: 2 }} connectNulls /></LineChart>
    </ChartBox>
  )
}

export function RetentionChart({ data }: { data: { week_start: string; reviews: number; retention: number | null }[] }) {
  const rows = data.map((d) => ({ ...d, label: shortDate(d.week_start), pct: d.retention === null ? null : Math.round(d.retention * 100) }))
  return (
    <ChartBox title={tt("Retention trend")} note={tt("Recall rate on already-learned questions, by week")} empty={!rows.some((r) => r.pct !== null)}>
      <LineChart data={rows} margin={{ left: -16, right: 4 }}><Grid /><XAxis dataKey="label" tick={tick} tickLine={false} axisLine={false} /><YAxis domain={[0, 100]} unit="%" tick={tick} tickLine={false} axisLine={false} /><Tooltip {...tip} formatter={(v: number, _n, p) => [`${v}% (${p.payload.reviews} reviews)`, 'Retention']} />
        <Line type="monotone" dataKey="pct" name="Retention" stroke="rgb(var(--warn))" strokeWidth={2} dot={{ r: 3 }} connectNulls /></LineChart>
    </ChartBox>
  )
}

export function MasteryBySubject({ data }: { data: SubjectStat[] }) {
  const rows = data.map((s) => ({ name: s.name, mastery: Math.round(s.mastery * 100), color: s.color }))
  return (
    <ChartBox title={tt("Mastery by subject")} note={tt("Recall probability × memory maturity, across all questions")} empty={!rows.length}>
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16 }}><CartesianGrid horizontal={false} stroke="rgb(var(--line))" /><XAxis type="number" domain={[0, 100]} unit="%" tick={tick} tickLine={false} axisLine={false} /><YAxis type="category" dataKey="name" width={90} tick={tick} tickLine={false} axisLine={false} /><Tooltip {...tip} cursor={{ fill: 'rgb(var(--raised))' }} formatter={(v: number) => `${v}%`} />
        <Bar dataKey="mastery" name="Mastery" fill="rgb(var(--accent))" radius={[0, 3, 3, 0]} barSize={14} /></BarChart>
    </ChartBox>
  )
}

export function MinutesChart({ data }: { data: DailyPoint[] }) {
  return (
    <ChartBox title={tt("Study time per day")} note={tt("Minutes spent answering questions")} empty={!data.some((d) => d.minutes)}>
      <BarChart data={withLabel(data)} margin={{ left: -16, right: 4 }}><Grid /><XAxis dataKey="label" tick={tick} tickLine={false} axisLine={false} minTickGap={24} /><YAxis tick={tick} tickLine={false} axisLine={false} /><Tooltip {...tip} cursor={{ fill: 'rgb(var(--raised))' }} />
        <Bar dataKey="minutes" name="Minutes" fill="rgb(var(--accent))" radius={[3, 3, 0, 0]} /></BarChart>
    </ChartBox>
  )
}
