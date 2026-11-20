import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronUp, Pause, Sparkles, X } from 'lucide-react'
import { get, post } from '@/api/client'
import type { Evaluation, SessionDetail, SessionItem } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { Tutor } from '@/components/Tutor'
import { Badge, Button, ErrorState, Loading, ProgressBar, StatusBadge, cx } from '@/components/ui'
import { useAiStatus } from '@/hooks/queries'
import { useToast } from '@/contexts/toast'
import { interval, pct } from '@/lib/format'
import { QUESTION_TYPES } from '@/api/types'
import { tt, tl } from '@/i18n'

const STYLES = ['quick_recall', 'written_recall', 'multiple_choice', 'calculation']
const RATINGS = [
  { v: 1, label: tt("Again"), cls: 'border-bad/50 text-bad hover:bg-bad/10' },
  { v: 2, label: tt("Hard"), cls: 'border-warn/50 text-warn hover:bg-warn/10' },
  { v: 3, label: tt("Good"), cls: 'border-good/50 text-good hover:bg-good/10' },
  { v: 4, label: tt("Easy"), cls: 'border-accent/50 text-accent hover:bg-accent/10' },
]

export default function StudySession() {
  const { id = '' } = useParams()
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const ai = useAiStatus()
  const resumed = useRef(false)

  const session = useQuery({ queryKey: ['session', id], queryFn: () => get<SessionDetail>(`/study/sessions/${id}`), refetchOnMount: 'always', staleTime: 0 })
  const data = session.data
  const pending = useMemo(() => (data?.items ?? []).filter((i) => !i.answered), [data])
  const current = pending[0]
  const done = !!data && (data.status === 'completed' || pending.length === 0)

  // per-question UI state
  const [revealed, setRevealed] = useState(false)
  const [text, setText] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [checked, setChecked] = useState(false)
  const [evalResult, setEvalResult] = useState<Evaluation | null>(null)
  const [tutor, setTutor] = useState(false)
  const startedAt = useRef(Date.now())
  const qid = current?.question.id

  useEffect(() => {
    setRevealed(false); setText(''); setPicked([]); setChecked(false); setEvalResult(null); setTutor(false)
    startedAt.current = Date.now()
  }, [qid, current?.position])

  useEffect(() => {
    if (data?.status === 'paused' && !resumed.current) { resumed.current = true; post(`/study/sessions/${id}/resume`).then(() => session.refetch()) }
  }, [data?.status, id, session])

  const style = STYLES.includes(data?.mode ?? '') ? data!.mode : sp.get('style') === 'written' ? 'written_recall' : 'quick_recall'
  const q = current?.question
  const isMcq = !!q && q.options.length > 0 && (style === 'multiple_choice' || (style === 'quick_recall' && ['multiple_choice', 'true_false'].includes(q.question_type)))
  const multi = !!q && q.options.filter((o) => o.is_correct).length > 1
  const correctIds = useMemo(() => new Set(q?.options.filter((o) => o.is_correct).map((o) => o.id!)), [q])
  const gotRight = isMcq && picked.length === correctIds.size && picked.every((p) => correctIds.has(p))
  const writing = !isMcq && (style === 'written_recall' || style === 'calculation')

  const answer = useMutation({
    mutationFn: (rating: number) => post<{ remaining: number; completed: boolean }>(`/study/sessions/${id}/answer`, {
      question_id: q!.id, rating, time_ms: Date.now() - startedAt.current, response_text: text,
      selected_option_ids: isMcq ? picked : undefined, ai_score: evalResult?.score,
    }),
    onSuccess: async () => { await session.refetch(); qc.invalidateQueries({ queryKey: ['due-badge'] }) },
    onError: (e) => toast.err(e instanceof Error ? e.message : tt("Could not save your answer")),
  })
  const evaluate = useMutation({
    mutationFn: () => post<Evaluation>('/ai/evaluate', { question_id: q!.id, answer: text }),
    onSuccess: setEvalResult,
    onError: (e) => toast.err(e instanceof Error ? e.message : tt("Evaluation failed")),
  })

  const reveal = useCallback(() => { if (isMcq && !picked.length) return; setRevealed(true); if (isMcq) setChecked(true) }, [isMcq, picked.length])
  const rate = useCallback((r: number) => { if (!answer.isPending && revealed) answer.mutate(r) }, [answer, revealed])

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      const typing = el.tagName === 'TEXTAREA' || el.tagName === 'INPUT'
      if (!current || done) return
      if (!revealed) {
        if ((e.key === 'Enter' && (e.ctrlKey || e.metaKey)) || (!typing && (e.key === ' ' || e.key === 'Enter'))) { e.preventDefault(); reveal() }
      } else if (!typing && ['1', '2', '3', '4'].includes(e.key)) {
        if (isMcq && !gotRight && e.key !== '1') return
        if (isMcq && gotRight && e.key === '1') return
        rate(Number(e.key))
      } else if (!typing && e.key === 'Enter' && isMcq && !gotRight) rate(1)
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [current, done, revealed, isMcq, gotRight, reveal, rate])

  const pause = async () => { try { await post(`/study/sessions/${id}/pause`) } catch { /* ignore */ } qc.invalidateQueries(); nav('/review') }

  if (session.isLoading) return <Loading />
  if (session.error || !data) return <ErrorState error={session.error} retry={session.refetch} />
  if (done) return <Summary id={id} />

  const total = data.items.length
  const answered = data.items.filter((i) => i.answered).length
  const item = current as SessionItem

  return (
    <div className="flex h-full flex-col bg-bg">
      <header className="flex shrink-0 items-center gap-3 border-b border-line bg-surface px-3 py-2 sm:px-5">
        <button className="btn btn-ghost btn-icon" onClick={pause} aria-label={tt("Pause and exit")}><X size={18} /></button>
        <div className="flex-1"><ProgressBar value={answered / total} tone="accent" label={tt("Session progress")} /></div>
        <span className="tabnum text-sm text-muted">{answered + 1} / {total}</span>
        <button className="btn" onClick={pause}><Pause size={14} /> <span className="hidden sm:inline">{tt("Pause")}</span></button>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl px-4 py-5 sm:py-8">
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            <StatusBadge status={q!.progress.status} />
            <Badge>{QUESTION_TYPES.find((t) => t.value === q!.question_type)?.label}</Badge>
            <Badge className="capitalize">{tl(q!.difficulty)}</Badge>
            {q!.topics[0] && <span className="text-xs text-muted">{q!.topics[0].name}</span>}
          </div>
          <article className="card p-4 sm:p-6">
            {q!.title && !q!.content.trim() ? <h1 className="text-lg font-medium">{q!.title}</h1> : <>{q!.title && <h1 className="mb-2 text-sm font-medium text-muted">{q!.title}</h1>}<Markdown className="text-[15px]">{q!.content}</Markdown></>}
          </article>

          {isMcq && (
            <ul className="mt-4 space-y-2" role={multi ? 'group' : 'radiogroup'} aria-label={tt("Answer options")}>
              {q!.options.map((o) => {
                const on = picked.includes(o.id!)
                const showRight = checked && o.is_correct
                const showWrong = checked && on && !o.is_correct
                return (
                  <li key={o.id}>
                    <button disabled={checked} role={multi ? 'checkbox' : 'radio'} aria-checked={on}
                      onClick={() => setPicked(multi ? (on ? picked.filter((x) => x !== o.id) : [...picked, o.id!]) : [o.id!])}
                      className={cx('flex min-h-12 w-full items-center gap-3 rounded-lg border px-4 py-3 text-start text-[15px]', on && !checked && 'border-accent bg-accent/5', showRight && 'border-good bg-good/10', showWrong && 'border-bad bg-bad/10', !on && !showRight && 'bg-surface hover:bg-raised')}>
                      <span className={cx('flex h-5 w-5 shrink-0 items-center justify-center border', multi ? 'rounded' : 'rounded-full', on ? 'border-accent bg-accent text-accent-fg' : 'border-faint')}>{on && <Check size={12} />}</span>
                      <span className="flex-1"><Markdown>{o.text}</Markdown></span>
                      {showRight && <Check size={16} className="text-good" />}{showWrong && <X size={16} className="text-bad" />}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}

          {writing && (
            <div className="mt-4">
              <label className="label" htmlFor="response">{style === 'calculation' ? tt("Your working and result") : tt("Your answer")}</label>
              <textarea id="response" className={cx('field min-h-36', style === 'calculation' && 'font-mono')} value={text} onChange={(e) => setText(e.target.value)} readOnly={revealed} rows={style === 'calculation' ? 8 : 6}
                placeholder={style === 'calculation' ? tt("Show your steps…") : tt("Write everything you remember before revealing the answer…")} autoFocus />
            </div>
          )}

          {revealed && (
            <section className="mt-5 space-y-4" aria-live="polite">
              <div className={cx('grid gap-4', writing && text.trim() && 'md:grid-cols-2')}>
                {writing && text.trim() && <div className="card p-4"><h2 className="h-section mb-1 text-muted">{tt("Your answer")}</h2><p className="whitespace-pre-wrap text-sm">{text}</p></div>}
                <div className="card border-good/40 p-4 sm:p-5">
                  <h2 className="h-section mb-1 text-good">{tt("Answer")}</h2>
                  {q!.answer.answer ? <Markdown>{q!.answer.answer}</Markdown> : isMcq ? <p className="text-sm text-muted">{gotRight ? tt("Correct.") : tt("The correct option is highlighted above.")}</p> : <p className="text-sm text-faint">{tt("No answer saved for this question.")}</p>}
                  {q!.answer.explanation && <div className="mt-3 border-t border-line pt-3"><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{tt("Explanation")}</h3><Markdown>{q!.answer.explanation}</Markdown></div>}
                </div>
              </div>

              {writing && text.trim() && ai.data?.enabled && !evalResult && <Button onClick={() => evaluate.mutate()} loading={evaluate.isPending}><Sparkles size={14} /> {tt("Evaluate my answer with AI")}</Button>}
              {evalResult && <EvalCard e={evalResult} />}

              <div>
                <button className="flex items-center gap-1 text-sm text-muted hover:text-fg" onClick={() => setTutor(!tutor)} aria-expanded={tutor}>{tutor ? <ChevronUp size={14} /> : <ChevronDown size={14} />} {tt("Ask the AI tutor about this question")}</button>
                {tutor && <div className="card mt-2 p-4"><Tutor questionId={q!.id} userAnswer={text} /></div>}
              </div>
            </section>
          )}
        </div>
      </main>

      <footer className="shrink-0 border-t border-line bg-surface px-3 py-3 safe-bottom sm:px-5">
        <div className="mx-auto max-w-2xl">
          {!revealed ? (
            <Button className="btn-primary btn-lg w-full" disabled={isMcq && !picked.length} onClick={reveal}>
              {isMcq ? tt("Check answer") : tt("Show answer")} <kbd className="ml-2 hidden rounded border border-white/30 px-1 text-xs opacity-80 sm:inline">Space</kbd>
            </Button>
          ) : isMcq && !gotRight ? (
            <Button className="btn-lg w-full" loading={answer.isPending} onClick={() => rate(1)}>{tt("Continue — this one will come back")} <kbd className="ml-2 hidden rounded border border-line px-1 text-xs text-muted sm:inline">Enter</kbd></Button>
          ) : (
            <div className={cx('grid gap-2', isMcq ? 'grid-cols-3' : 'grid-cols-4')} role="group" aria-label={tt("How well did you recall it?")}>
              {RATINGS.filter((r) => !(isMcq && r.v === 1)).map((r) => (
                <button key={r.v} disabled={answer.isPending} onClick={() => rate(r.v)} aria-label={tt("{label}, next review in {v}", { label: r.label, v: interval(item.intervals[r.v]) })}
                  className={cx('flex min-h-14 flex-col items-center justify-center rounded-lg border bg-surface px-1 py-2 font-medium disabled:opacity-50', r.cls, evalResult?.suggested_rating === r.v && 'ring-2 ring-accent')}>
                  <span className="text-sm">{r.label}</span>
                  <span className="text-xs font-normal opacity-80 tabnum">{interval(item.intervals[r.v])}</span>
                  <kbd className="hidden text-[10px] opacity-60 sm:block">{r.v}</kbd>
                </button>
              ))}
            </div>
          )}
          {revealed && evalResult && <p className="mt-1.5 text-center text-xs text-muted">{tt("AI suggests:")} {RATINGS[evalResult.suggested_rating - 1].label} {tt("— you decide.")}</p>}
        </div>
      </footer>
    </div>
  )
}

function EvalCard({ e }: { e: Evaluation }) {
  const list = (title: string, items: string[], tone: string) => items.length > 0 && (
    <div><h3 className={cx('text-xs font-semibold uppercase tracking-wide', tone)}>{title}</h3><ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
  )
  return (
    <div className="card space-y-3 p-4">
      <div className="flex items-center gap-3"><div className="tabnum text-2xl font-semibold">{Math.round(e.score)}<span className="text-sm text-muted">/100</span></div><p className="flex-1 text-sm">{e.explanation}</p></div>
      {list(tt('Correct concepts'), e.correct_concepts, 'text-good')}{list(tt('Missing concepts'), e.missing_concepts, 'text-warn')}{list(tt('Incorrect reasoning'), e.incorrect_reasoning, 'text-bad')}
      {e.improved_answer && <details><summary className="cursor-pointer text-sm font-medium">{tt("Suggested improved answer")}</summary><div className="mt-2"><Markdown>{e.improved_answer}</Markdown></div></details>}
    </div>
  )
}

function Summary({ id }: { id: string }) {
  const s = useQuery({ queryKey: ['session-summary', id], queryFn: () => get<{ reviews: number; correct: number; accuracy: number | null; ratings: Record<string, number>; time_seconds: number; missed: { question_id: string; title: string }[] }>(`/study/sessions/${id}/summary`) })
  const qc = useQueryClient()
  useEffect(() => { qc.invalidateQueries() }, [qc])
  if (s.isLoading) return <Loading />
  if (s.error || !s.data) return <ErrorState error={s.error} />
  const d = s.data
  return (
    <div className="flex min-h-full items-center justify-center bg-bg px-4 py-10">
      <div className="card w-full max-w-lg p-6">
        <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-good/10 text-good"><Check size={20} /></div>
        <h1 className="h-page">{tt("Session complete")}</h1>
        <p className="mt-1 text-sm text-muted">{d.reviews} {tt("answers in")} {Math.max(1, Math.round(d.time_seconds / 60))} {tt("min. Your review schedule has been updated.")}</p>
        <div className="mt-5 grid grid-cols-3 gap-3 text-center">
          <div className="rounded-lg bg-raised p-3"><div className="tabnum text-xl font-semibold">{pct(d.accuracy)}</div><div className="text-xs text-muted">{tt("Recalled")}</div></div>
          <div className="rounded-lg bg-raised p-3"><div className="tabnum text-xl font-semibold">{d.ratings['1'] ?? 0}</div><div className="text-xs text-muted">{tt("Again")}</div></div>
          <div className="rounded-lg bg-raised p-3"><div className="tabnum text-xl font-semibold">{(d.ratings['3'] ?? 0) + (d.ratings['4'] ?? 0)}</div><div className="text-xs text-muted">{tt("Good / Easy")}</div></div>
        </div>
        {d.missed.length > 0 && (
          <div className="mt-5"><h2 className="h-section mb-1">{tt("To revisit")}</h2>
            <ul className="space-y-0.5 text-sm">{[...new Map(d.missed.map((m) => [m.question_id, m])).values()].slice(0, 8).map((m) => <li key={m.question_id}><Link className="text-accent underline" to={`/questions/${m.question_id}`}>{m.title || tt("Untitled question")}</Link></li>)}</ul>
          </div>
        )}
        <div className="mt-6 flex flex-wrap gap-2"><Link className="btn btn-primary" to="/study">{tt("Study more")}</Link><Link className="btn" to="/">{tt("Dashboard")}</Link><Link className="btn" to="/review">{tt("Review queue")}</Link></div>
      </div>
    </div>
  )
}
