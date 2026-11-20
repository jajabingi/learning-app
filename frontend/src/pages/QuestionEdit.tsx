import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Pencil } from 'lucide-react'
import { del, get, patch, post } from '@/api/client'
import type { Question } from '@/api/types'
import { QUESTION_TYPES } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { QuestionForm } from '@/components/QuestionForm'
import { Tutor } from '@/components/Tutor'
import { Page } from '@/components/Layout'
import { Badge, ConfirmDialog, ErrorState, Loading, StatusBadge, TagList, Tabs, cx } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { interval, pct, relTime } from '@/lib/format'

interface Hist { id: string; reviewed_at: string; rating: number; correct: boolean; study_mode: string; time_ms: number; stability_after: number; scheduled_days: number; response_text: string }
const RATING = ['', 'Again', 'Hard', 'Good', 'Easy']

export default function QuestionEditPage() {
  const { id = '' } = useParams()
  const [editing, setEditing] = useState(false)
  const [side, setSide] = useState<'progress' | 'history' | 'tutor'>('progress')
  const [confirm, setConfirm] = useState<'delete' | 'reset' | null>(null)
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['question', id], queryFn: () => get<Question>(`/questions/${id}`) })
  const hist = useQuery({ queryKey: ['question-history', id], queryFn: () => get<Hist[]>(`/questions/${id}/history`), enabled: side === 'history' })

  const act = useMutation({
    mutationFn: async (a: 'delete' | 'reset' | 'suspend' | 'unsuspend' | 'archive' | 'unarchive') => {
      if (a === 'delete') return del(`/questions/${id}`)
      if (a === 'reset') return post(`/questions/${id}/progress/reset`)
      if (a === 'suspend' || a === 'unsuspend') return post(`/questions/${id}/suspend?suspended=${a === 'suspend'}`)
      return patch(`/questions/${id}`, { archived: a === 'archive' })
    },
    onSuccess: (_r, a) => { qc.invalidateQueries(); setConfirm(null); if (a === 'delete') { toast.ok('Question deleted'); nav('/questions') } },
    onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed'),
  })
  const setConfidence = useMutation({ mutationFn: (c: number) => patch(`/questions/${id}`, { confidence: c }), onSuccess: () => qc.invalidateQueries() })

  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const d = q.data
  const p = d.progress

  return (
    <Page>
      <Link to="/questions" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ArrowLeft size={14} /> Questions</Link>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          {editing ? (
            <div className="card p-4"><QuestionForm initial={d} onSaved={() => setEditing(false)} onCancel={() => setEditing(false)} /></div>
          ) : (
            <article className="card p-5">
              <div className="mb-3 flex flex-wrap items-center gap-1.5">
                <StatusBadge status={p.status} />
                <Badge>{QUESTION_TYPES.find((t) => t.value === d.question_type)?.label}</Badge>
                <Badge className="capitalize" tone={d.difficulty === 'hard' ? 'bad' : d.difficulty === 'easy' ? 'good' : 'neutral'}>{d.difficulty}</Badge>
                {d.archived && <Badge>Archived</Badge>}
                <button className="btn ml-auto" onClick={() => setEditing(true)}><Pencil size={14} /> Edit</button>
              </div>
              {d.title && <h1 className="mb-2 text-lg font-semibold">{d.title}</h1>}
              <Markdown>{d.content}</Markdown>
              {d.options.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {d.options.map((o) => <li key={o.id} className={cx('rounded border px-3 py-1.5 text-sm', o.is_correct ? 'border-good/50 bg-good/5' : 'border-line')}>{o.is_correct ? '✓ ' : ''}{o.text}</li>)}
                </ul>
              )}
              <h2 className="h-section mb-1 mt-6 text-muted">Answer</h2>
              {d.answer.answer ? <Markdown>{d.answer.answer}</Markdown> : <p className="text-sm text-faint">No answer written yet.</p>}
              {d.answer.explanation && (<><h2 className="h-section mb-1 mt-5 text-muted">Explanation</h2><Markdown>{d.answer.explanation}</Markdown></>)}
              <div className="mt-6 space-y-1.5 border-t border-line pt-3 text-xs text-muted">
                {d.topics.length > 0 && <div>Topics: {d.topics.map((t, i) => <span key={t.id}>{i > 0 && ', '}<Link className="text-accent underline" to={`/library/topic/${t.id}`}>{t.name}</Link></span>)}</div>}
                {d.tags.length > 0 && <div><TagList tags={d.tags} /></div>}
                {d.source && <div>Source: {/^https?:\/\//.test(d.source) ? <a className="text-accent underline" href={d.source} target="_blank" rel="noopener noreferrer">{d.source}</a> : d.source}</div>}
                <div>Created {relTime(d.created_at)} · Updated {relTime(d.updated_at)}</div>
              </div>
            </article>
          )}
        </div>

        <aside className="min-w-0 space-y-3">
          <div className="card p-4">
            <Tabs<'progress' | 'history' | 'tutor'> value={side} onChange={setSide} tabs={[{ id: 'progress', label: 'Learning' }, { id: 'history', label: 'History' }, { id: 'tutor', label: 'AI tutor' }]} />
            <div className="pt-3">
              {side === 'progress' && (
                <div className="space-y-3 text-sm">
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
                    <Fact k="Status" v={<StatusBadge status={p.status} />} />
                    <Fact k="Next review" v={p.due_at && !p.suspended ? (new Date(p.due_at) <= new Date() ? 'Due now' : relTime(p.due_at)) : '—'} />
                    <Fact k="Recall now" v={pct(p.retrievability)} />
                    <Fact k="Stability" v={p.reps ? interval(p.stability) : '—'} />
                    <Fact k="Reviews" v={p.reps} />
                    <Fact k="Lapses" v={p.lapses} />
                    <Fact k="Difficulty" v={p.reps ? `${p.difficulty.toFixed(1)} / 10` : '—'} />
                    <Fact k="Last reviewed" v={p.last_review_at ? relTime(p.last_review_at) : '—'} />
                  </dl>
                  <div>
                    <span className="label">Your confidence</span>
                    <div className="flex gap-1" role="radiogroup" aria-label="Confidence level">
                      {[1, 2, 3, 4, 5].map((c) => <button key={c} role="radio" aria-checked={p.confidence === c} onClick={() => setConfidence.mutate(c)} className={cx('btn h-7 w-8 px-0', p.confidence === c && 'border-accent bg-accent/10 text-accent')}>{c}</button>)}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 border-t border-line pt-3">
                    <button className="btn" onClick={() => act.mutate(p.suspended ? 'unsuspend' : 'suspend')}>{p.suspended ? 'Unsuspend' : 'Suspend'}</button>
                    <button className="btn" onClick={() => act.mutate(d.archived ? 'unarchive' : 'archive')}>{d.archived ? 'Unarchive' : 'Archive'}</button>
                    <button className="btn" disabled={!p.reps} onClick={() => setConfirm('reset')}>Reset progress</button>
                    <button className="btn btn-danger" onClick={() => setConfirm('delete')}>Delete</button>
                  </div>
                </div>
              )}
              {side === 'history' && (hist.isLoading ? <Loading /> : !hist.data?.length ? <p className="text-sm text-muted">Not reviewed yet.</p> : (
                <ul className="max-h-96 space-y-2 overflow-y-auto text-sm">
                  {hist.data.map((h) => (
                    <li key={h.id} className="rounded border border-line p-2">
                      <div className="flex items-center justify-between"><Badge tone={h.rating === 1 ? 'bad' : h.rating === 2 ? 'warn' : 'good'}>{RATING[h.rating]}</Badge><span className="text-xs text-muted">{relTime(h.reviewed_at)}</span></div>
                      <div className="mt-1 text-xs text-muted">Next in {interval(h.scheduled_days)} · stability {interval(h.stability_after)}{h.time_ms ? ` · ${Math.round(h.time_ms / 1000)}s` : ''}</div>
                      {h.response_text && <p className="mt-1 line-clamp-3 text-xs italic">“{h.response_text}”</p>}
                    </li>
                  ))}
                </ul>
              ))}
              {side === 'tutor' && <Tutor questionId={id} />}
            </div>
          </div>
        </aside>
      </div>
      <ConfirmDialog open={confirm === 'delete'} onClose={() => setConfirm(null)} onConfirm={() => act.mutate('delete')} title="Delete this question?" message="It and its review history will be permanently deleted. You can archive it instead." />
      <ConfirmDialog open={confirm === 'reset'} onClose={() => setConfirm(null)} onConfirm={() => act.mutate('reset')} danger={false} confirmLabel="Reset" title="Reset learning progress?" message="This question returns to “New”. Review history is kept." />
    </Page>
  )
}

function Fact({ k, v }: { k: string; v: React.ReactNode }) {
  return <div><dt className="text-xs text-muted">{k}</dt><dd className="font-medium tabnum">{v}</dd></div>
}
