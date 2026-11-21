import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Check, ChevronLeft, ChevronRight, Clock, Flag, X } from 'lucide-react'
import { ApiError, get, post } from '@/api/client'
import { Markdown } from '@/components/Markdown'
import { Badge, Button, Empty, ErrorState, Loading, Modal, ProgressBar } from '@/components/ui'
import { tt, tl } from '@/i18n'

interface AttemptRow { id: string; attempt_no: number; status: string; submitted_at: string | null; released: boolean; percent: number | null; passed: boolean | null }
interface Summary {
  id: string; course_id: string; course_title: string; title: string; description: string; instructions: string; difficulty: string; status: string; question_count: number; total_points: number
  time_limit_minutes: number | null; passing_score: number; max_attempts: number | null; attempts_used: number; attempts_left: number | null; opens_at: string | null; closes_at: string | null
  allow_back: boolean; one_per_page: boolean; in_progress_attempt_id: string | null; attempts: AttemptRow[]; can_start: boolean
}
type Ans = { option_ids?: string[]; text?: string } | null
interface Q { id: string; type: string; title: string; content: string; points: number; options: { id: string; text: string }[]; multiple: boolean; answer: Ans; flagged: boolean }
interface State { id: string; exam_id: string; status: string; server_now: string; deadline_at: string | null; remaining_seconds: number | null; title: string; instructions: string; one_per_page: boolean; allow_back: boolean; allow_change_answers: boolean; time_limit_minutes: number | null; questions: Q[] }

const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleString('he-IL', { dateStyle: 'medium', timeStyle: 'short' }) : '')
const clock = (s: number) => `${Math.floor(s / 3600) ? `${Math.floor(s / 3600)}:` : ''}${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
const ST_TONE: Record<string, 'good' | 'warn' | 'bad' | 'neutral' | 'accent'> = { open: 'good', scheduled: 'warn', closed: 'bad' }

// ------------------------------------------------------------------ list & intro
export function ExamsHome() {
  const q = useQuery({ queryKey: ['student-exams'], queryFn: () => get<Summary[]>('/student/exams'), staleTime: 0 })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  return (
    <div className="space-y-6">
      <div><h1 className="text-3xl font-semibold tracking-tight">{tt("Exams")}</h1><p className="mt-1 text-lg text-muted">{tt("Timed exams for the courses you are enrolled in.")}</p></div>
      {q.data.length === 0 ? <div className="card"><Empty title={tt("No exams available")}>{tt("Exams published for your courses will appear here.")}</Empty></div> : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{q.data.map((e) => (
          <Link key={e.id} to={`/exams/${e.id}`} className="card block p-5 hover:border-faint">
            <div className="flex items-start justify-between gap-2"><h3 dir="auto" className="text-lg font-semibold">{e.title}</h3><Badge tone={ST_TONE[e.status]}>{tl(e.status)}</Badge></div>
            <p className="mt-1 text-sm text-muted">{e.course_title}</p>
            <p className="mt-3 text-sm text-muted tabnum">{e.question_count} {tt("questions")}{e.time_limit_minutes ? ` · ${e.time_limit_minutes} ${tt("min")}` : ''}</p>
            <span className="btn btn-primary mt-4 w-full text-base">{e.in_progress_attempt_id ? tt("Continue exam") : e.can_start ? tt("Open") : tt("View")}</span>
          </Link>))}</div>
      )}
    </div>
  )
}

export function ExamIntro() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['student-exam', id], queryFn: () => get<Summary>(`/student/exams/${id}`), staleTime: 0 })
  const start = useMutation({ mutationFn: () => post<State>(`/student/exams/${id}/start`), onSuccess: (s) => nav(`/exam/${s.id}`) })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const e = q.data
  const rows: [string, string][] = [
    [tt("Questions"), String(e.question_count)], [tt("Maximum score"), `${e.total_points} ${tt("pts")}`], [tt("Time limit"), e.time_limit_minutes ? `${e.time_limit_minutes} ${tt("min")}` : tt("No limit")],
    [tt("Passing score"), `${e.passing_score}%`], [tt("Attempts remaining"), e.attempts_left === null ? tt("Unlimited") : String(e.attempts_left)],
    ...(e.opens_at ? [[tt("Opens"), fmtDate(e.opens_at)] as [string, string]] : []), ...(e.closes_at ? [[tt("Closes"), fmtDate(e.closes_at)] as [string, string]] : []),
  ]
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <Link to="/exams" className="text-sm text-muted hover:text-fg">{tt("← Exams")}</Link>
      <div><h1 dir="auto" className="text-3xl font-semibold tracking-tight">{e.title}</h1><p className="mt-1 text-muted">{e.course_title}</p></div>
      {e.description && <p dir="auto" className="whitespace-pre-wrap text-base">{e.description}</p>}
      <dl className="card divide-y divide-line">{rows.map(([k, v]) => <div key={k} className="flex justify-between px-4 py-2.5 text-base"><dt className="text-muted">{k}</dt><dd className="font-medium tabnum">{v}</dd></div>)}</dl>
      <div className="card space-y-2 p-4 text-sm"><h2 className="font-semibold">{tt("Important rules")}</h2>
        <ul className="list-disc space-y-1 ps-5 text-muted"><li>{tt("The timer is controlled by the server. Refreshing the page or closing it does not stop or reset it.")}</li><li>{tt("Your answers are saved automatically.")}</li><li>{tt("When time runs out the exam is submitted automatically.")}</li>{!e.allow_back && <li>{tt("You cannot return to previous questions.")}</li>}</ul>
        {e.instructions && <p dir="auto" className="whitespace-pre-wrap border-t border-line pt-2 text-fg">{e.instructions}</p>}</div>
      {start.error && <p role="alert" className="text-sm text-bad">{start.error instanceof Error ? start.error.message : ''}</p>}
      {e.can_start ? <Button className="btn-primary w-full text-lg" loading={start.isPending} onClick={() => start.mutate()}>{e.in_progress_attempt_id ? tt("Continue exam") : tt("Start exam")}</Button>
        : <p className="rounded border border-line p-3 text-center text-sm text-muted">{e.status === 'scheduled' ? tt("This exam is not open yet.") : e.status === 'closed' ? tt("This exam is closed.") : tt("You have no attempts left.")}</p>}
      {e.attempts.length > 0 && <div><h2 className="mb-2 font-semibold">{tt("Your attempts")}</h2><ul className="card divide-y divide-line">{e.attempts.map((a) => (
        <li key={a.id} className="flex items-center gap-3 px-4 py-2.5 text-sm"><span className="tabnum">#{a.attempt_no}</span><Badge>{tl(a.status)}</Badge>{a.released && a.percent !== null && <span className="tabnum">{a.percent}%</span>}{a.released && a.passed !== undefined && a.passed !== null && (a.passed ? <Badge tone="good">{tt("Passed")}</Badge> : <Badge tone="bad">{tt("Failed")}</Badge>)}
          <span className="ms-auto">{a.status === 'in_progress' ? <Link className="btn h-8" to={`/exam/${a.id}`}>{tt("Continue exam")}</Link> : <Link className="btn h-8" to={`/exam-result/${a.id}`}>{tt("Results")}</Link>}</span></li>))}</ul></div>}
    </div>
  )
}

// ------------------------------------------------------------------ the exam itself (distraction free, full screen)
type Save = 'saved' | 'saving' | 'error'

export function ExamRun() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['exam-run', id], queryFn: () => get<State | { status: string }>(`/student/exam-attempts/${id}`), staleTime: Infinity, refetchOnWindowFocus: false, retry: false })
  const data = q.data && (q.data as State).questions ? (q.data as State) : null
  useEffect(() => { if (q.data && !data) nav(`/exam-result/${id}`, { replace: true }) }, [q.data, data, id, nav])
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <div className="p-6"><ErrorState error={q.error} retry={q.refetch} /></div>
  if (!data) return <Loading />
  return <Runner s={data} />
}

function Runner({ s }: { s: State }) {
  const nav = useNavigate()
  const offset = useRef(new Date(s.server_now).getTime() - Date.now()) // server clock minus local clock: the local clock is never trusted
  const deadline = s.deadline_at ? new Date(s.deadline_at).getTime() : null
  const [now, setNow] = useState(Date.now())
  const [answers, setAnswers] = useState<Record<string, Ans>>(() => Object.fromEntries(s.questions.map((x) => [x.id, x.answer])))
  const [flags, setFlags] = useState<Record<string, boolean>>(() => Object.fromEntries(s.questions.map((x) => [x.id, x.flagged])))
  const [idx, setIdx] = useState(0)
  const [save, setSave] = useState<Save>('saved')
  const [confirming, setConfirming] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const dirty = useRef(new Set<string>())
  const [version, setVersion] = useState(0)
  const live = useRef({ answers, flags })
  live.current = { answers, flags }
  const finished = useRef(false)

  const remaining = deadline === null ? null : Math.max(0, Math.floor((deadline - (now + offset.current)) / 1000))
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t) }, [])

  const payload = useCallback((ids: string[]) => ids.map((qid) => ({ exam_question_id: qid, answer: live.current.answers[qid] ?? null, flagged: !!live.current.flags[qid] })), [])
  const goResult = useCallback(() => { finished.current = true; nav(`/exam-result/${s.id}`, { replace: true }) }, [nav, s.id])

  const flush = useCallback(async () => {
    const ids = [...dirty.current]
    if (!ids.length || finished.current) return true
    setSave('saving')
    try {
      const r = await post<{ server_now: string }>(`/student/exam-attempts/${s.id}/answers`, { answers: payload(ids) })
      offset.current = new Date(r.server_now).getTime() - Date.now()
      ids.forEach((i) => dirty.current.delete(i))
      setSave(dirty.current.size ? 'saving' : 'saved')
      return true
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 404)) { goResult(); return true } // time is over / attempt closed on the server
      setSave('error') // the local answer is kept and retried
      return false
    }
  }, [s.id, payload, goResult])

  const touch = (qid: string) => { dirty.current.add(qid); setSave('saving'); setVersion((v) => v + 1) }
  useEffect(() => { if (!version) return; const t = setTimeout(flush, 600); return () => clearTimeout(t) }, [version, flush])
  useEffect(() => { const t = setInterval(() => { if (dirty.current.size) flush() }, 4000); return () => clearInterval(t) }, [flush]) // retry after failures
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty.current.size && !finished.current) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', h); return () => window.removeEventListener('beforeunload', h)
  }, [])

  const submit = useCallback(async () => {
    if (finished.current || submitting) return
    setSubmitting(true)
    try {
      await post(`/student/exam-attempts/${s.id}/submit`, { answers: payload(s.questions.map((x) => x.id)) })
      goResult()
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) goResult()
      else { setSubmitting(false); setSave('error') }
    }
  }, [s.id, s.questions, payload, goResult, submitting])

  const autoDone = useRef(false)
  useEffect(() => { if (remaining === 0 && !autoDone.current) { autoDone.current = true; submit() } }, [remaining, submit])

  const setAnswer = (qid: string, a: Ans) => {
    if (!s.allow_change_answers && answers[qid]) return
    setAnswers((p) => ({ ...p, [qid]: a })); touch(qid)
  }
  const answered = (x: Q) => { const a = answers[x.id]; return !!a && ((a.option_ids?.length ?? 0) > 0 || !!a.text?.trim()) }
  const unanswered = s.questions.filter((x) => !answered(x))
  const done = s.questions.length - unanswered.length
  const warn = remaining !== null && remaining <= 120

  const list = s.one_per_page ? [s.questions[idx]] : s.questions
  const go = (i: number) => { if (!s.allow_back && i < idx) return; if (s.one_per_page) setIdx(i); else document.getElementById(`q-${s.questions[i].id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }

  return (
    <div className="min-h-screen bg-bg">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-4 py-3">
          <h1 dir="auto" className="min-w-0 flex-1 truncate text-lg font-semibold">{s.title}</h1>
          <span className={`text-xs ${save === 'error' ? 'font-medium text-bad' : 'text-muted'}`} role="status" aria-live="polite">{save === 'saving' ? tt("Saving…") : save === 'saved' ? tt("Saved") : tt("Not saved — retrying")}</span>
          {remaining !== null && <div className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-lg font-semibold tabnum ${warn ? 'animate-pulse border-bad bg-bad/10 text-bad' : 'border-line'}`} dir="ltr" aria-label={tt("Time left")}><Clock size={16} /> {clock(remaining)}</div>}
          <button className="btn btn-primary" onClick={() => setConfirming(true)} disabled={submitting}>{tt("Submit exam")}</button>
        </div>
        <div className="mx-auto max-w-5xl px-4 pb-2"><div className="mb-1 flex justify-between text-xs text-muted tabnum"><span>{s.one_per_page ? tt("Question {a} of {b}", { a: idx + 1, b: s.questions.length }) : tt("{n} questions", { n: s.questions.length })}</span><span>{Math.round((done / s.questions.length) * 100)}% {tt("completed")}</span></div><ProgressBar value={done / s.questions.length} tone="accent" label={tt("Progress")} /></div>
      </header>
      {save === 'error' && <div role="alert" className="bg-bad/10 px-4 py-2 text-center text-sm text-bad">{tt("Your latest answers are not saved yet. Check your connection — they are kept on this page and will be retried.")}</div>}
      <div className="mx-auto grid max-w-5xl gap-5 px-4 py-5 lg:grid-cols-[1fr_16rem]">
        <main className="space-y-5">
          {list.map((x) => {
            const i = s.questions.indexOf(x)
            const a = answers[x.id]
            const chosen = new Set(a?.option_ids ?? [])
            return (
              <section key={x.id} id={`q-${x.id}`} className="card p-5">
                <div className="mb-3 flex items-center gap-2 text-sm text-muted"><span className="font-semibold text-fg">{tt("Question {a} of {b}", { a: i + 1, b: s.questions.length })}</span><span>· {x.points} {tt("pts")}</span>
                  <button className={`btn ms-auto h-8 ${flags[x.id] ? 'border-warn text-warn' : ''}`} aria-pressed={!!flags[x.id]} onClick={() => { setFlags((p) => ({ ...p, [x.id]: !p[x.id] })); touch(x.id) }}><Flag size={13} /> {flags[x.id] ? tt("Flagged") : tt("Flag for review")}</button></div>
                <div dir="auto" className="prose-recall text-lg font-medium"><Markdown>{x.content}</Markdown></div>
                {x.options.length > 0 ? (
                  <div className="mt-4 space-y-2" role={x.multiple ? 'group' : 'radiogroup'}>
                    {x.multiple && <p className="text-xs text-muted">{tt("Select all that apply.")}</p>}
                    {x.options.map((o) => {
                      const on = chosen.has(o.id)
                      return <label key={o.id} className={`flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 text-base ${on ? 'border-accent bg-accent/10' : 'border-line hover:bg-raised/60'}`}>
                        <input type={x.multiple ? 'checkbox' : 'radio'} name={x.id} checked={on} onChange={() => setAnswer(x.id, { option_ids: x.multiple ? (on ? [...chosen].filter((c) => c !== o.id) : [...chosen, o.id]) : [o.id] })} />
                        <span dir="auto" className="flex-1"><Markdown>{o.text}</Markdown></span></label>
                    })}
                  </div>
                ) : <textarea dir="auto" className="field mt-4 min-h-32" rows={x.type === 'calculation' ? 2 : 6} placeholder={tt("Write your answer…")} value={a?.text ?? ''} onChange={(e) => setAnswer(x.id, { text: e.target.value })} aria-label={tt("Your answer")} />}
              </section>)
          })}
          {s.one_per_page && <div className="flex justify-between gap-3">
            <button className="btn text-base" disabled={idx === 0 || !s.allow_back} onClick={() => go(idx - 1)}><ChevronRight size={16} className="ltr:hidden" /><ChevronLeft size={16} className="rtl:hidden" /> {tt("Previous question")}</button>
            <button className="btn btn-primary text-base" disabled={idx === s.questions.length - 1} onClick={() => go(idx + 1)}>{tt("Next question")} <ChevronLeft size={16} className="ltr:hidden" /><ChevronRight size={16} className="rtl:hidden" /></button></div>}
        </main>
        <aside className="lg:sticky lg:top-32 lg:self-start">
          <div className="card p-4"><h2 className="mb-3 text-sm font-semibold">{tt("Questions")}</h2>
            <div className="grid grid-cols-6 gap-1.5 lg:grid-cols-5">{s.questions.map((x, i) => (
              <button key={x.id} onClick={() => go(i)} disabled={!s.allow_back && i < idx} aria-label={`${tt("Question")} ${i + 1}: ${flags[x.id] ? tt("Flagged") : answered(x) ? tt("Answered") : tt("Unanswered")}`}
                className={`relative h-9 rounded border text-sm tabnum ${s.one_per_page && i === idx ? 'ring-2 ring-accent' : ''} ${answered(x) ? 'border-accent bg-accent/15 font-medium' : 'border-line'} disabled:opacity-40`}>{i + 1}{flags[x.id] && <Flag size={9} className="absolute end-0.5 top-0.5 text-warn" />}</button>))}</div>
            <dl className="mt-3 space-y-1 text-xs text-muted"><div className="flex items-center gap-2"><span className="h-3 w-3 rounded border border-accent bg-accent/15" />{tt("Answered")}</div><div className="flex items-center gap-2"><span className="h-3 w-3 rounded border border-line" />{tt("Unanswered")}</div><div className="flex items-center gap-2"><Flag size={11} className="text-warn" />{tt("Flagged")}</div></dl>
            <p className="mt-3 text-xs text-muted tabnum">{unanswered.length} {tt("unanswered")}</p></div>
        </aside>
      </div>
      <Modal open={confirming} onClose={() => setConfirming(false)} title={tt("Submit exam?")} footer={<><button className="btn" onClick={() => setConfirming(false)}>{tt("Back to exam")}</button><Button className="btn-primary" loading={submitting} onClick={submit}>{tt("Submit exam")}</Button></>}>
        <p className="text-sm">{unanswered.length > 0 ? tt("{n} questions are unanswered.", { n: unanswered.length }) : tt("All questions are answered.")} {Object.values(flags).some(Boolean) && tt("Some questions are flagged for review.")}</p>
        <p className="mt-2 text-sm text-muted">{tt("After submitting you cannot change your answers.")}</p>
      </Modal>
    </div>
  )
}

// ------------------------------------------------------------------ result
interface RQ { id: string; number: number; type: string; content: string; options: { id: string; text: string }[]; your_answer: Ans; answered: boolean; grading_status: string; points?: number; points_awarded?: number | null; is_correct?: boolean | null; feedback?: string; correct_option_ids?: string[]; correct_answer?: string; explanation?: string }
interface Result { id: string; exam_id: string; title: string; attempt_no: number; status: string; submitted_at: string | null; auto_submitted: boolean; released: boolean; pending_manual: boolean; score?: number; max_score?: number; percent?: number; passed?: boolean; passing_score?: number; questions?: RQ[] }

export function ExamResult() {
  const { id = '' } = useParams()
  const q = useQuery({ queryKey: ['exam-result', id], queryFn: () => get<Result>(`/student/exam-attempts/${id}/result`), staleTime: 0 })
  const exam = useMemo(() => q.data?.exam_id, [q.data])
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const r = q.data
  if (r.status === 'in_progress') return <div className="mx-auto max-w-xl"><Empty title={tt("This attempt is still in progress")} action={<Link className="btn btn-primary" to={`/exam/${r.id}`}>{tt("Continue exam")}</Link>} /></div>
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Link to={exam ? `/exams/${exam}` : '/exams'} className="text-sm text-muted hover:text-fg">{tt("← Exam")}</Link>
      <h1 dir="auto" className="text-3xl font-semibold tracking-tight">{r.title}</h1>
      <div className="card p-5 text-center">
        <p className="text-sm text-muted">{tt("Submitted")}: {fmtDate(r.submitted_at)}{r.auto_submitted ? ` · ${tt("submitted automatically when time ran out")}` : ''}</p>
        {!r.released ? <p className="mt-3 text-lg">{r.pending_manual ? tt("Your exam was submitted and is waiting for the teacher to grade it.") : tt("Your exam was submitted. Results have not been published yet.")}</p> : <>
          {r.percent !== undefined && <p className="mt-2 text-5xl font-semibold tabnum" dir="ltr">{r.percent}%</p>}
          {r.score !== undefined && <p className="text-muted tabnum">{r.score} / {r.max_score} {tt("pts")}</p>}
          {r.passed !== undefined && <p className="mt-2"><Badge tone={r.passed ? 'good' : 'bad'}>{r.passed ? tt("Passed") : tt("Failed")}</Badge> <span className="text-xs text-muted">{tt("Passing score")} {r.passing_score}%</span></p>}
          {r.pending_manual && <p className="mt-2 text-sm text-warn">{tt("Some answers are still waiting for manual grading — the score may change.")}</p>}</>}
      </div>
      {r.questions?.map((x) => {
        const mine = new Set(x.your_answer?.option_ids ?? [])
        const right = new Set(x.correct_option_ids ?? [])
        return (
          <section key={x.id} className="card p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-muted"><span className="font-semibold text-fg">{tt("Question")} {x.number}</span>
              {x.is_correct === true && <Badge tone="good"><Check size={12} /> {tt("Correct")}</Badge>}{x.is_correct === false && x.grading_status !== 'pending' && <Badge tone="bad"><X size={12} /> {tt("Incorrect")}</Badge>}{!x.answered && <Badge>{tt("Unanswered")}</Badge>}{x.grading_status === 'pending' && <Badge tone="warn">{tt("Pending grading")}</Badge>}
              {x.points !== undefined && <span className="ms-auto tabnum">{x.points_awarded ?? '—'} / {x.points}</span>}</div>
            <div dir="auto" className="prose-recall font-medium"><Markdown>{x.content}</Markdown></div>
            {x.options.length > 0 ? <ul className="mt-2 space-y-1">{x.options.map((o) => <li key={o.id} dir="auto" className={`rounded border px-3 py-1.5 text-sm ${right.has(o.id) ? 'border-good/50 bg-good/10' : mine.has(o.id) && x.correct_option_ids ? 'border-bad/50 bg-bad/10' : 'border-line'}`}>{mine.has(o.id) ? '● ' : '○ '}{o.text}</li>)}</ul>
              : <p dir="auto" className="mt-2 whitespace-pre-wrap rounded border border-line bg-raised/50 p-2 text-sm">{x.your_answer?.text || <span className="text-muted">{tt("No answer")}</span>}</p>}
            {x.correct_answer && <p dir="auto" className="mt-2 text-sm"><b>{tt("Correct answer")}:</b> {x.correct_answer}</p>}
            {x.explanation && <div dir="auto" className="prose-recall mt-2 rounded bg-raised/60 p-3 text-sm"><Markdown>{x.explanation}</Markdown></div>}
            {x.feedback && <p dir="auto" className="mt-2 rounded border border-accent/30 bg-accent/5 p-2 text-sm"><b>{tt("Teacher feedback")}:</b> {x.feedback}</p>}
          </section>)
      })}
    </div>
  )
}
