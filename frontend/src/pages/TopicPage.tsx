import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Pencil, Plus, Sparkles, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '@/api/client'
import { RELATIONS, type Note } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { MarkdownEditor } from '@/components/MarkdownEditor'
import { QuestionTable } from '@/components/QuestionTable'
import { useQuickCreate } from '@/components/QuickCreate'
import { Tutor } from '@/components/Tutor'
import { TopicPicker } from '@/components/TopicPicker'
import { Badge, Button, Empty, ErrorState, Loading, Menu, PageHeader, ProgressBar, Stat, Tabs } from '@/components/ui'
import { Page } from '@/components/Layout'
import { useToast } from '@/contexts/toast'
import { pct, relTime, shortDate } from '@/lib/format'
import { useLibraryActions } from './Library'

interface TopicDetail {
  id: string; name: string; description: string; subject_id: string; chapter_id: string | null; parent_id: string | null; archived: boolean
  breadcrumb: { subject: { id: string; name: string }; course: { id: string; name: string } | null; chapter: { id: string; name: string } | null; ancestors: { id: string; name: string }[] }
  children: { id: string; name: string }[]
  related: { id: string; relation_type: string; direction: 'in' | 'out'; topic: { id: string; name: string } }[]
  progress: { direct_questions: number; questions: number; mastery: number; accuracy: number | null; due: number; mastered: number; new: number; lapses: number; reviews: number }
  history: { per_day: { date: string; reviews: number; correct: number }[]; recent: { question_id: string; title: string; rating: number; correct: boolean; reviewed_at: string; study_mode: string }[] }
  note_counts: Record<string, number>
}
type Tab = 'overview' | 'notes' | 'questions' | 'definitions' | 'formulas' | 'related' | 'progress' | 'history'
const RATING = ['', 'Again', 'Hard', 'Good', 'Easy']

export default function TopicPage() {
  const { id = '' } = useParams()
  const [tab, setTab] = useState<Tab>('overview')
  const nav = useNavigate()
  const qc = useQuickCreate()
  const a = useLibraryActions()
  const t = useQuery({ queryKey: ['topic', id], queryFn: () => get<TopicDetail>(`/topics/${id}`) })
  if (t.isLoading) return <Loading />
  if (t.error || !t.data) return <ErrorState error={t.error} retry={t.refetch} />
  const d = t.data
  const b = d.breadcrumb
  const nc = d.note_counts

  return (
    <Page>
      <nav className="mb-1 flex flex-wrap items-center gap-1 text-xs text-muted" aria-label="Breadcrumb">
        <Link to="/library" className="hover:text-fg">Library</Link><span>/</span>
        <Link to={`/library/subject/${b.subject.id}`} className="hover:text-fg">{b.subject.name}</Link>
        {b.course && <><span>/</span><Link to={`/library/course/${b.course.id}`} className="hover:text-fg">{b.course.name}</Link></>}
        {b.chapter && <><span>/</span><Link to={`/library/chapter/${b.chapter.id}`} className="hover:text-fg">{b.chapter.name}</Link></>}
        {b.ancestors.map((x) => <span key={x.id} className="flex items-center gap-1"><span>/</span><Link to={`/library/topic/${x.id}`} className="hover:text-fg">{x.name}</Link></span>)}
      </nav>
      <PageHeader title={<>{d.name}{d.archived && <span className="ml-2 text-sm font-normal text-muted">(archived)</span>}</>}
        subtitle={`${d.progress.questions} questions · ${pct(d.progress.mastery)} mastery${d.progress.due ? ` · ${d.progress.due} due` : ''}`}
        actions={<>
          <button className="btn btn-primary" disabled={!d.progress.questions} onClick={() => nav(`/study?topic=${id}`)}>Study topic</button>
          <button className="btn" onClick={() => qc.open('question', { question: { subject_id: d.subject_id, topic_ids: [id] } })}>New question</button>
          <Menu items={[
            { label: 'Rename / edit…', onClick: () => setTab('overview') },
            { label: 'Add subtopic', onClick: () => qc.open('topic', { topic: { parent_id: id, subject_id: d.subject_id } }) },
            { label: 'Generate questions with AI', onClick: () => qc.open('ai', { ai: { topic_id: id } }) },
            { label: 'Move…', onClick: () => a.moveTopic(id) },
            { label: d.archived ? 'Restore' : 'Archive', onClick: () => a.archive('topic', id, !d.archived) }, 'sep',
            { label: 'Delete…', danger: true, onClick: () => a.remove('topic', id, d.name) },
          ]} />
        </>} />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: 'overview', label: 'Overview' }, { id: 'notes', label: `Notes${nc.note ? ` · ${nc.note}` : ''}` }, { id: 'questions', label: `Questions · ${d.progress.questions}` },
        { id: 'definitions', label: `Definitions${nc.definition ? ` · ${nc.definition}` : ''}` }, { id: 'formulas', label: `Formulas${nc.formula ? ` · ${nc.formula}` : ''}` },
        { id: 'related', label: `Related · ${d.related.length}` }, { id: 'progress', label: 'Progress' }, { id: 'history', label: 'History' },
      ]} />
      <div className="pt-5">
        {tab === 'overview' && <Overview d={d} />}
        {tab === 'notes' && <InlineNotes topicId={id} subjectId={d.subject_id} kind="note" />}
        {tab === 'definitions' && <InlineNotes topicId={id} subjectId={d.subject_id} kind="definition" />}
        {tab === 'formulas' && <InlineNotes topicId={id} subjectId={d.subject_id} kind="formula" />}
        {tab === 'questions' && (
          <div>
            <div className="mb-3 flex justify-end gap-2"><button className="btn" onClick={() => qc.open('ai', { ai: { topic_id: id } })}><Sparkles size={14} /> Generate with AI</button></div>
            <QuestionTable fixed={{ topic_id: id }} compact empty={<Empty title="No questions for this topic yet" action={<button className="btn btn-primary" onClick={() => qc.open('question', { question: { subject_id: d.subject_id, topic_ids: [id] } })}>Create the first one</button>}>Questions linked to this topic or its subtopics appear here.</Empty>} />
          </div>
        )}
        {tab === 'related' && <Related d={d} />}
        {tab === 'progress' && <ProgressTab d={d} />}
        {tab === 'history' && <HistoryTab d={d} />}
      </div>
    </Page>
  )
}

function Overview({ d }: { d: TopicDetail }) {
  const [edit, setEdit] = useState(false)
  const [name, setName] = useState(d.name)
  const [desc, setDesc] = useState(d.description)
  const qc = useQueryClient()
  const toast = useToast()
  const save = useMutation({ mutationFn: () => patch(`/topics/${d.id}`, { name, description: desc }), onSuccess: () => { qc.invalidateQueries(); setEdit(false); toast.ok('Saved') }, onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed') })
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="space-y-5">
        <section className="card p-4">
          <div className="mb-2 flex items-center justify-between"><h2 className="h-section">Overview</h2>{!edit && <button className="btn btn-ghost" onClick={() => setEdit(true)}><Pencil size={14} /> Edit</button>}</div>
          {edit ? (
            <div className="space-y-3">
              <input className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} aria-label="Topic name" />
              <MarkdownEditor value={desc} onChange={setDesc} label="Description" minRows={8} placeholder="Describe the topic: key ideas, why it matters, how it connects…" />
              <div className="flex justify-end gap-2"><button className="btn" onClick={() => { setEdit(false); setName(d.name); setDesc(d.description) }}>Cancel</button><Button className="btn-primary" loading={save.isPending} onClick={() => name.trim() && save.mutate()}>Save</Button></div>
            </div>
          ) : d.description ? <Markdown>{d.description}</Markdown> : <p className="text-sm text-muted">No description yet. Use Edit to write an overview of this topic.</p>}
        </section>
        <section>
          <h2 className="h-section mb-2">Subtopics</h2>
          {d.children.length === 0 ? <p className="text-sm text-muted">No subtopics.</p> : <div className="card divide-y divide-line">{d.children.map((c) => <Link key={c.id} to={`/library/topic/${c.id}`} className="block px-3 py-2 text-sm font-medium hover:bg-raised/60">{c.name}</Link>)}</div>}
        </section>
      </div>
      <aside className="card h-fit p-4"><h2 className="h-section mb-3">AI tutor</h2><Tutor topicId={d.id} /></aside>
    </div>
  )
}

function InlineNotes({ topicId, subjectId, kind }: { topicId: string; subjectId: string; kind: Note['kind'] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const nav = useNavigate()
  const notes = useQuery({ queryKey: ['notes', { topicId, kind }], queryFn: () => get<Note[]>('/notes', { topic_id: topicId, kind }) })
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const label = { note: 'note', definition: 'definition', formula: 'formula' }[kind]
  const start = (n?: Note) => { setEditing(n?.id ?? 'new'); setTitle(n?.title ?? ''); setContent(n?.content ?? '') }
  const save = useMutation({
    mutationFn: () => (editing === 'new' ? post('/notes', { title, content, kind, topic_id: topicId, subject_id: subjectId }) : patch(`/notes/${editing}`, { title, content })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['notes'] }); setEditing(null); toast.ok('Saved') }, onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed'),
  })
  const rm = useMutation({ mutationFn: (id: string) => del(`/notes/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ['notes'] }) })
  if (notes.isLoading) return <Loading />
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><button className="btn btn-primary" onClick={() => start()}><Plus size={14} /> Add {label}</button></div>
      {editing && (
        <div className="card space-y-3 p-4">
          <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={kind === 'formula' ? 'Formula name, e.g. Sharpe ratio' : kind === 'definition' ? 'Term' : 'Title'} maxLength={300} autoFocus aria-label="Title" />
          <MarkdownEditor value={content} onChange={setContent} label="Content" minRows={kind === 'note' ? 8 : 4} placeholder={kind === 'formula' ? '$$ S = \\frac{R_p - R_f}{\\sigma_p} $$' : undefined} />
          <div className="flex justify-end gap-2"><button className="btn" onClick={() => setEditing(null)}>Cancel</button><Button className="btn-primary" loading={save.isPending} onClick={() => (title.trim() || content.trim()) && save.mutate()}>Save</Button></div>
        </div>
      )}
      {!notes.data?.length && !editing && <div className="card"><Empty title={`No ${label}s on this topic`}>{kind === 'note' ? 'Notes are free-form Markdown with LaTeX, tables and images.' : kind === 'formula' ? 'Store key formulas with LaTeX, e.g. $E[X]=\\sum x_i p_i$.' : 'Record precise definitions of key terms.'}</Empty></div>}
      {notes.data?.map((n) => (
        <article key={n.id} className="card p-4">
          <div className="mb-1 flex items-start justify-between gap-2"><h3 className="font-medium">{n.title || 'Untitled'}</h3><div className="flex shrink-0 gap-1">
            {kind === 'note' && <button className="btn btn-ghost h-7" onClick={() => nav(`/notes/${n.id}`)}>Open</button>}
            <button className="btn btn-ghost btn-icon h-7 w-7" aria-label="Edit" onClick={() => start(n)}><Pencil size={13} /></button>
            <button className="btn btn-ghost btn-icon h-7 w-7 text-bad" aria-label="Delete" onClick={() => rm.mutate(n.id)}><Trash2 size={13} /></button></div></div>
          <Markdown>{n.content}</Markdown>
          <div className="mt-2 text-xs text-faint">Updated {relTime(n.updated_at)}</div>
        </article>
      ))}
    </div>
  )
}

function Related({ d }: { d: TopicDetail }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [other, setOther] = useState<string[]>([])
  const [type, setType] = useState('related_to')
  const [dir, setDir] = useState<'out' | 'in'>('out')
  const add = useMutation({
    mutationFn: () => post('/relationships', dir === 'out' ? { source_topic_id: d.id, target_topic_id: other[0], relation_type: type } : { source_topic_id: other[0], target_topic_id: d.id, relation_type: type }),
    onSuccess: () => { qc.invalidateQueries(); setOther([]); toast.ok('Relationship added') }, onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed'),
  })
  const rm = useMutation({ mutationFn: (id: string) => del(`/relationships/${id}`), onSuccess: () => qc.invalidateQueries() })
  const label = (r: TopicDetail['related'][number]) => {
    const t = RELATIONS.find((x) => x.value === r.relation_type)?.label ?? r.relation_type
    return r.direction === 'out' ? `${t}` : `${t} (this topic is the target)`
  }
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <section>
        <h2 className="h-section mb-2">Connected topics</h2>
        {d.related.length === 0 ? <p className="text-sm text-muted">No relationships yet.</p> : (
          <ul className="card divide-y divide-line">
            {d.related.map((r) => (
              <li key={r.id} className="flex items-center gap-2 px-3 py-2">
                <div className="min-w-0 flex-1"><Link to={`/library/topic/${r.topic.id}`} className="block truncate text-sm font-medium hover:underline">{r.topic.name}</Link><span className="text-xs text-muted">{r.direction === 'out' ? '→' : '←'} {label(r)}</span></div>
                <button className="btn btn-ghost btn-icon text-bad" aria-label="Remove relationship" onClick={() => rm.mutate(r.id)}><Trash2 size={14} /></button>
              </li>
            ))}
          </ul>
        )}
        <Link to="/graph" className="mt-2 inline-block text-sm text-accent underline">View in knowledge graph</Link>
      </section>
      <section className="card h-fit space-y-3 p-4">
        <h2 className="h-section">Connect to another topic</h2>
        <div className="grid grid-cols-2 gap-2">
          <select className="field" value={dir} onChange={(e) => setDir(e.target.value as 'in' | 'out')} aria-label="Direction"><option value="out">This topic →</option><option value="in">← This topic is target</option></select>
          <select className="field" value={type} onChange={(e) => setType(e.target.value)} aria-label="Relationship type">{RELATIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select>
        </div>
        <TopicPicker single value={other} onChange={setOther} />
        <Button className="btn-primary" disabled={!other[0] || other[0] === d.id} loading={add.isPending} onClick={() => add.mutate()}>Add relationship</Button>
      </section>
    </div>
  )
}

function ProgressTab({ d }: { d: TopicDetail }) {
  const p = d.progress
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Mastery" value={pct(p.mastery)} hint="Recall × maturity, all questions" />
        <Stat label="Accuracy" value={pct(p.accuracy)} hint={`${p.reviews} reviews`} />
        <Stat label="Mastered" value={`${p.mastered} / ${p.questions}`} />
        <Stat label="Due now" value={p.due} tone={p.due ? 'warn' : undefined} hint={`${p.new} not yet studied`} />
      </div>
      <ProgressBar value={p.mastery} label="Topic mastery" />
      <section className="card p-4">
        <h2 className="h-section mb-3">Reviews per day (last 30 days)</h2>
        {d.history.per_day.length === 0 ? <p className="text-sm text-muted">No reviews yet.</p> : (
          <div className="h-48"><ResponsiveContainer><BarChart data={d.history.per_day.map((x) => ({ ...x, label: shortDate(x.date) }))}><CartesianGrid vertical={false} stroke="rgb(var(--line))" /><XAxis dataKey="label" tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} /><YAxis allowDecimals={false} width={28} tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} /><Tooltip contentStyle={{ background: 'rgb(var(--surface))', border: '1px solid rgb(var(--line))', borderRadius: 6, fontSize: 12 }} cursor={{ fill: 'rgb(var(--raised))' }} /><Bar dataKey="reviews" name="Reviews" fill="rgb(var(--accent))" radius={[3, 3, 0, 0]} /><Bar dataKey="correct" name="Recalled" fill="rgb(var(--good))" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></div>
        )}
      </section>
    </div>
  )
}

function HistoryTab({ d }: { d: TopicDetail }) {
  if (!d.history.recent.length) return <div className="card"><Empty title="No study history yet">Reviews of this topic’s questions will be listed here.</Empty></div>
  return (
    <ul className="card divide-y divide-line">
      {d.history.recent.map((h, i) => (
        <li key={i}><Link to={`/questions/${h.question_id}`} className="flex items-center gap-3 px-3 py-2.5 hover:bg-raised/60">
          <Badge tone={h.rating === 1 ? 'bad' : h.rating === 2 ? 'warn' : 'good'}>{RATING[h.rating]}</Badge>
          <span className="min-w-0 flex-1 truncate text-sm">{h.title || 'Untitled question'}</span>
          <span className="shrink-0 text-xs text-muted">{h.study_mode.replace('_', ' ')} · {relTime(h.reviewed_at)}</span>
        </Link></li>
      ))}
    </ul>
  )
}
