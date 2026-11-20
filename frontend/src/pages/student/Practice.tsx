import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronLeft, ChevronRight, Eye, RotateCcw, X } from 'lucide-react'
import { get, post } from '@/api/client'
import { Markdown } from '@/components/Markdown'
import { Badge, Button, Empty, ErrorState, Loading, ProgressBar, cx } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { t } from '@/i18n'

interface SetCard { id: string; title: string; description: string; kind: 'practice' | 'exam'; total: number; revealed: number; correct: number }
interface Overview { course_id: string; course_title: string; sets: SetCard[] }
interface Solution { answer: string; explanation: string; correct_option_ids: string[] }
interface Item { item_id: string; position: number; question: { id: string; title: string; content: string; question_type: string; options: { id: string; text: string }[] }; revealed: boolean; selected_option_ids: string[] | null; is_correct: boolean | null; solution: Solution | null }
interface SetData { id: string; title: string; description: string; kind: string; course_id: string; course_title: string; items: Item[] }

export function PracticeHome() {
  const q = useQuery({ queryKey: ['student-practice'], queryFn: () => get<Overview[]>('/student/practice') })
  if (q.isLoading) return <Loading label={t('common.loading')} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  return (
    <div className="space-y-8">
      <div><h1 className="text-3xl font-semibold tracking-tight">{t('practice.title')}</h1><p className="mt-1 text-lg text-muted">{t('practice.subtitle')}</p></div>
      {q.data.length === 0 ? <div className="card"><Empty title={t('practice.none')}>{t('practice.noneHint')}</Empty></div> : q.data.map((c) => (
        <section key={c.course_id}>
          <h2 dir="auto" className="mb-3 text-lg font-semibold">{c.course_title}</h2>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {c.sets.map((s) => (
              <Link key={s.id} to={`/practice/${s.id}`} className="card block p-5 hover:border-faint">
                <div className="flex items-start justify-between gap-2"><h3 dir="auto" className="text-lg font-semibold">{s.title}</h3><Badge tone={s.kind === 'exam' ? 'warn' : 'accent'}>{s.kind === 'exam' ? t('practice.exam') : t('practice.practiceKind')}</Badge></div>
                {s.description && <p dir="auto" className="mt-1 line-clamp-2 text-sm text-muted">{s.description}</p>}
                <div className="mt-4"><div className="mb-1 flex justify-between text-sm text-muted tabnum"><span>{s.revealed} / {s.total}</span><span>{t('practice.questionsCount', { n: s.total })}</span></div><ProgressBar value={s.total ? s.revealed / s.total : 0} tone="accent" label={s.title} /></div>
                <span className="btn btn-primary mt-4 w-full text-base">{s.revealed ? t('practice.continue') : t('practice.start')}</span>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

export function PracticeSet() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['student-practice-set', id], queryFn: () => get<SetData>(`/student/practice/sets/${id}`), staleTime: 0 })
  const [idx, setIdx] = useState(0)
  const [picked, setPicked] = useState<string[]>([])
  const [mine, setMine] = useState('')
  const items = q.data?.items ?? []
  const cur = items[idx]
  useEffect(() => { setPicked(cur?.selected_option_ids ?? []); setMine('') }, [cur?.item_id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const first = items.findIndex((i) => !i.revealed); if (q.isSuccess && first > 0 && idx === 0) setIdx(first) }, [q.isSuccess]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => { qc.invalidateQueries({ queryKey: ['student-practice-set', id] }); qc.invalidateQueries({ queryKey: ['student-practice'] }) }
  const reveal = useMutation({ mutationFn: () => post(`/student/practice/items/${cur.item_id}/reveal`, { selected_option_ids: cur.question.options.length ? picked : null }), onSuccess: refresh, onError: (e) => toast.err(e instanceof Error ? e.message : t('common.somethingWrong')) })
  const reset = useMutation({ mutationFn: () => post(`/student/practice/items/${cur.item_id}/reset`), onSuccess: refresh })

  if (q.isLoading) return <Loading label={t('common.loading')} />
  if (q.error || !q.data) return <div className="card"><Empty title={t('practice.notAvailable')} action={<Link className="btn" to="/practice">{t('practice.back')}</Link>}>{t('practice.notAvailableHint')}</Empty></div>
  const d = q.data
  if (!cur) return <div className="card"><Empty title={t('practice.noQuestions')} action={<button className="btn" onClick={() => nav('/practice')}>{t('common.back')}</button>} /></div>
  const done = items.filter((i) => i.revealed).length
  const multi = cur.question.options.length > 0
  const isMulti = multi && cur.question.options.filter((o) => cur.solution?.correct_option_ids.includes(o.id)).length > 1
  const sol = cur.solution

  return (
    <div>
      <Link to="/practice" className="mb-3 inline-block text-sm text-muted hover:text-fg"><span className="inline-block rtl:-scale-x-100">←</span> {t('practice.back')}</Link>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div><h1 dir="auto" className="text-3xl font-semibold tracking-tight">{d.title}</h1><p dir="auto" className="text-base text-muted">{d.course_title}</p></div>
        <div className="w-56"><div className="mb-1 flex justify-between text-sm text-muted tabnum"><span>{t('practice.done')}</span><span>{done} / {items.length}</span></div><ProgressBar value={done / items.length} tone="accent" label={d.title} /></div>
      </div>

      <div className="mb-4 flex flex-wrap gap-1.5" role="tablist" aria-label={t('common.questions')}>
        {items.map((it, i) => (
          <button key={it.item_id} role="tab" aria-selected={i === idx} aria-label={`${t('common.questions')} ${i + 1}`} onClick={() => setIdx(i)}
            className={cx('flex h-9 w-9 items-center justify-center rounded border text-base font-medium tabnum', i === idx ? 'border-accent bg-accent text-accent-fg' : it.revealed ? (it.is_correct === false ? 'border-bad/50 bg-bad/10 text-bad' : 'border-good/50 bg-good/10 text-good') : 'border-line hover:bg-raised')}>{i + 1}</button>
        ))}
      </div>

      <article className="card p-5 sm:p-6" key={cur.item_id}>
        <div className="mb-3 flex items-center justify-between"><span className="text-sm font-medium text-muted tabnum">{t('practice.questionOf', { a: idx + 1, b: items.length })}</span>{cur.question.title && <Badge>{cur.question.title}</Badge>}</div>
        <Markdown>{cur.question.content}</Markdown>

        {multi && (
          <ul className="mt-4 space-y-2" role="radiogroup">
            {cur.question.options.map((o) => {
              const on = picked.includes(o.id)
              const right = cur.revealed && sol?.correct_option_ids.includes(o.id)
              const wrong = cur.revealed && on && !right
              return (
                <li key={o.id}>
                  <button disabled={cur.revealed} role="radio" aria-checked={on} onClick={() => setPicked(isMulti ? (on ? picked.filter((x) => x !== o.id) : [...picked, o.id]) : [o.id])}
                    className={cx('flex min-h-12 w-full items-center gap-3 rounded-lg border px-4 py-3 text-start text-base', on && !cur.revealed && 'border-accent bg-accent/5', right && 'border-good bg-good/10', wrong && 'border-bad bg-bad/10', !on && !right && 'bg-surface hover:bg-raised')}>
                    <span className={cx('flex h-5 w-5 shrink-0 items-center justify-center rounded-full border', on ? 'border-accent bg-accent text-accent-fg' : 'border-faint')}>{on && <Check size={12} />}</span>
                    <span dir="auto" className="flex-1"><Markdown>{o.text}</Markdown></span>{right && <Check size={16} className="text-good" />}{wrong && <X size={16} className="text-bad" />}
                  </button>
                </li>
              )
            })}
          </ul>
        )}

        {!multi && !cur.revealed && (
          <div className="mt-4"><label className="label text-sm" htmlFor="mine">{t('practice.yourAttempt')}</label><textarea id="mine" dir="auto" className="field min-h-28 text-base" rows={4} value={mine} onChange={(e) => setMine(e.target.value)} placeholder={t('practice.attemptPlaceholder')} /></div>
        )}

        {!cur.revealed ? (
          <Button className="btn-primary btn-lg mt-5 w-full sm:w-auto" loading={reveal.isPending} disabled={multi && picked.length === 0} onClick={() => reveal.mutate()}><Eye size={16} /> {t('practice.showAnswer')}</Button>
        ) : sol && (
          <section className="mt-6 space-y-4" aria-live="polite">
            {cur.is_correct !== null && <div className={cx('rounded-lg border px-4 py-2.5 text-base font-medium', cur.is_correct ? 'border-good/40 bg-good/10 text-good' : 'border-bad/40 bg-bad/10 text-bad')}>{cur.is_correct ? t('practice.correct') : t('practice.notQuite')}</div>}
            <div className="rounded-lg border border-good/40 bg-good/5 p-4"><h2 className="mb-1 text-sm font-semibold text-good">{t('practice.answer')}</h2><Markdown>{sol.answer || '—'}</Markdown></div>
            {sol.explanation && <div className="rounded-lg border border-line p-4"><h2 className="mb-2 text-sm font-semibold text-muted">{t('practice.fullSolution')}</h2><Markdown>{sol.explanation}</Markdown></div>}
            <button className="btn" onClick={() => reset.mutate()}><RotateCcw size={14} /> {t('practice.tryAgain')}</button>
          </section>
        )}
      </article>

      <div className="mt-4 flex justify-between">
        <button className="btn text-base" disabled={idx === 0} onClick={() => setIdx(idx - 1)}><ChevronRight size={14} className="ltr:hidden" /><ChevronLeft size={14} className="rtl:hidden" /> {t('practice.prev')}</button>
        <button className="btn btn-primary text-base" disabled={idx >= items.length - 1} onClick={() => setIdx(idx + 1)}>{t('practice.next')} <ChevronRight size={14} className="ltr:hidden" /><ChevronLeft size={14} className="rtl:hidden" /></button>
      </div>
    </div>
  )
}
