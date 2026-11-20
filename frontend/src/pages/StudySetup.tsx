import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Brain, Calculator, CheckSquare, Layers, Library, PenLine, Shuffle, Target, Zap } from 'lucide-react'
import { get, post } from '@/api/client'
import { QUESTION_TYPES, type SessionSummary } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { TopicPicker } from '@/components/TopicPicker'
import { Badge, Button, Field, Loading, PageHeader, cx } from '@/components/ui'
import { Page } from '@/components/Layout'
import { useAiStatus, useTree } from '@/hooks/queries'
import { duration, relTime } from '@/lib/format'
import { useToast } from '@/contexts/toast'

const MODES = [
  { id: 'quick_recall', label: 'Quick Recall', desc: 'See the question, reveal the answer, rate yourself.', Icon: Zap },
  { id: 'written_recall', label: 'Written Recall', desc: 'Write a full answer first, then compare with the solution.', Icon: PenLine },
  { id: 'multiple_choice', label: 'Multiple Choice', desc: 'Choose from options; wrong answers are scheduled for relearning.', Icon: CheckSquare },
  { id: 'calculation', label: 'Calculation', desc: 'Work the problem, then compare your calculation.', Icon: Calculator },
  { id: 'topic', label: 'Topic Study', desc: 'Only questions from one topic (and its subtopics).', Icon: Layers },
  { id: 'subject', label: 'Subject Study', desc: 'Questions from an entire subject.', Icon: Library },
  { id: 'mixed', label: 'Mixed Study', desc: 'Interleave questions from all your subjects.', Icon: Shuffle },
  { id: 'weakness', label: 'Weakness Mode', desc: 'Focus on questions you keep getting wrong.', Icon: Target },
] as const
type ModeId = (typeof MODES)[number]['id']

const SELECTIONS = [
  ['mixed', 'Smart mix — due reviews first, then new'], ['due', 'Review questions only (due now)'], ['new', 'New questions only'],
  ['weak', 'Weak questions only'], ['all', 'Everything, ignoring schedule'],
]

export default function StudySetup() {
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const toast = useToast()
  const { data: tree = [] } = useTree()
  const [mode, setMode] = useState<ModeId>(sp.get('topic') ? 'topic' : sp.get('subject') ? 'subject' : 'quick_recall')
  const [count, setCount] = useState(20)
  const [subject, setSubject] = useState(sp.get('subject') ?? '')
  const [topic, setTopic] = useState<string[]>(sp.get('topic') ? [sp.get('topic')!] : [])
  const [difficulty, setDifficulty] = useState('')
  const [qtype, setQtype] = useState('')
  const [selection, setSelection] = useState('mixed')
  const [written, setWritten] = useState(false)

  useEffect(() => { setSelection(mode === 'weakness' ? 'weak' : 'mixed') }, [mode])
  const body = { mode, count, subject_id: mode === 'topic' ? null : subject || null, topic_id: mode === 'topic' ? topic[0] ?? null : null, difficulty: difficulty || null, question_type: qtype || null, selection }
  const needsScope = (mode === 'topic' && !topic[0]) || (mode === 'subject' && !subject)

  const preview = useQuery({ queryKey: ['study-preview', body], queryFn: () => post<{ available: number; estimated_seconds: number }>('/study/preview', body), enabled: !needsScope })
  const open = useQuery({ queryKey: ['open-sessions'], queryFn: () => get<SessionSummary[]>('/study/sessions', { status_: 'open' }) })
  const start = useMutation({
    mutationFn: () => post<{ id: string }>('/study/sessions', body),
    onSuccess: (s) => nav(`/study/session/${s.id}${written ? '?style=written' : ''}`),
    onError: (e) => toast.err(e instanceof Error ? e.message : 'Could not start'),
  })
  const avail = preview.data?.available ?? 0

  return (
    <Page>
      <PageHeader title="Study" subtitle="Active recall beats re-reading. Pick a mode and test yourself." />
      {open.data && open.data.length > 0 && (
        <section className="card mb-5 p-4">
          <h2 className="h-section mb-2">Resume a session</h2>
          <ul className="divide-y divide-line">
            {open.data.map((s) => (
              <li key={s.id} className="flex items-center gap-3 py-2">
                <div className="min-w-0 flex-1 text-sm"><span className="font-medium capitalize">{s.mode.replace('_', ' ')}</span> <Badge>{s.status}</Badge><div className="text-xs text-muted">{s.answered} of {s.total} answered · {relTime(s.last_activity_at)}</div></div>
                <Link className="btn btn-primary" to={`/study/session/${s.id}`}>Resume</Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" role="radiogroup" aria-label="Study mode">
        {MODES.map((m) => (
          <button key={m.id} role="radio" aria-checked={mode === m.id} onClick={() => setMode(m.id)} className={cx('card p-3.5 text-left hover:border-faint', mode === m.id && 'border-accent ring-1 ring-accent')}>
            <m.Icon size={18} className={mode === m.id ? 'text-accent' : 'text-muted'} />
            <div className="mt-2 text-sm font-medium">{m.label}</div>
            <p className="mt-0.5 text-xs text-muted">{m.desc}</p>
          </button>
        ))}
      </div>

      <section className="card mt-5 p-4">
        <h2 className="h-section mb-3">Session settings</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Number of questions"><input type="number" min={1} max={200} className="field" value={count} onChange={(e) => setCount(Math.max(1, Math.min(200, Number(e.target.value) || 1)))} /></Field>
          {mode === 'topic' ? (
            <div className="sm:col-span-2"><span className="label">Topic</span><TopicPicker single value={topic} onChange={setTopic} /></div>
          ) : (
            <Field label={mode === 'subject' ? 'Subject (required)' : 'Subject'}><select className="field" value={subject} onChange={(e) => setSubject(e.target.value)}><option value="">{mode === 'subject' ? 'Choose…' : 'All subjects'}</option>{tree.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
          )}
          <Field label="Difficulty"><select className="field" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}><option value="">Any</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select></Field>
          {!['multiple_choice', 'calculation'].includes(mode) && <Field label="Question type"><select className="field" value={qtype} onChange={(e) => setQtype(e.target.value)}><option value="">Any</option>{QUESTION_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</select></Field>}
          <Field label="Which questions"><select className="field" value={selection} onChange={(e) => setSelection(e.target.value)}>{SELECTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
          {['topic', 'subject', 'mixed', 'weakness'].includes(mode) && (
            <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={written} onChange={(e) => setWritten(e.target.checked)} /> Write my answers before revealing</label>
          )}
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Button className="btn-primary btn-lg" loading={start.isPending} disabled={needsScope || avail === 0} onClick={() => start.mutate()}>Start session</Button>
          <span className="text-sm text-muted" aria-live="polite">
            {needsScope ? 'Choose a ' + (mode === 'topic' ? 'topic' : 'subject') + ' to continue' : preview.isLoading ? 'Checking…' : avail === 0 ? 'No questions match these settings' : `${Math.min(avail, count)} question${Math.min(avail, count) === 1 ? '' : 's'} · about ${duration((preview.data!.estimated_seconds * Math.min(avail, count)) / Math.max(avail, 1))}`}
          </span>
        </div>
      </section>
      <StudyPlan />
    </Page>
  )
}

function StudyPlan() {
  const ai = useAiStatus()
  const [goal, setGoal] = useState('')
  const [minutes, setMinutes] = useState(30)
  const [days, setDays] = useState(7)
  const [plan, setPlan] = useState('')
  const toast = useToast()
  const gen = useMutation({ mutationFn: () => post<{ plan: string }>('/ai/study-plan', { goal, minutes_per_day: minutes, days }), onSuccess: (r) => setPlan(r.plan), onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed') })
  if (ai.isLoading) return <Loading />
  return (
    <section className="card mt-5 p-4">
      <h2 className="h-section mb-1 flex items-center gap-1.5"><Brain size={14} /> AI study plan</h2>
      {!ai.data?.enabled ? <p className="text-sm text-muted">Available once an AI key is configured on the server.</p> : (
        <>
          <p className="mb-3 text-sm text-muted">Uses your goals, available time, mastery, upcoming reviews and weak areas.</p>
          <div className="grid gap-3 sm:grid-cols-[1fr_8rem_8rem]">
            <Field label="Goal"><input className="field" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. Pass the CFA Level 1 exam in 6 weeks" maxLength={1000} /></Field>
            <Field label="Minutes / day"><input type="number" min={5} max={600} className="field" value={minutes} onChange={(e) => setMinutes(Number(e.target.value) || 30)} /></Field>
            <Field label="Days"><input type="number" min={1} max={90} className="field" value={days} onChange={(e) => setDays(Number(e.target.value) || 7)} /></Field>
          </div>
          <Button className="btn-primary mt-3" loading={gen.isPending} disabled={goal.trim().length < 3} onClick={() => gen.mutate()}>Create plan</Button>
          {plan && <div className="mt-4 rounded-lg border border-line bg-bg p-4"><Markdown>{plan}</Markdown></div>}
        </>
      )}
    </section>
  )
}
