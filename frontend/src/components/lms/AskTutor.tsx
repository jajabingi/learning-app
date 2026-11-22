import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { MessageCircle, Send } from 'lucide-react'
import { post } from '@/api/client'
import { Markdown } from '@/components/Markdown'
import { Button } from '@/components/ui'
import { tt } from '@/i18n'

interface Turn { role: 'student' | 'tutor'; text: string }

/** Student-facing AI tutor for ONE lesson. It answers from the lesson only, keeps a short conversation, and has a daily limit. */
export function AskTutor({ lessonId }: { lessonId: string }) {
  const [open, setOpen] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const [q, setQ] = useState('')
  const [remaining, setRemaining] = useState<number | null>(null)
  const [error, setError] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const ask = useMutation({
    mutationFn: (question: string) => post<{ answer: string; remaining: number }>(`/student/lessons/${lessonId}/ask`, { question, history: turns.slice(-6) }),
    onSuccess: (r, question) => { setTurns((t) => [...t, { role: 'student', text: question }, { role: 'tutor', text: r.answer }]); setRemaining(r.remaining); setQ(''); setError(''); setTimeout(() => end.current?.scrollIntoView({ behavior: 'smooth' }), 50) },
    onError: (e) => setError(e instanceof Error ? e.message : tt("Failed")),
  })
  if (!open) return <button className="btn gap-2" onClick={() => setOpen(true)}><MessageCircle size={15} /> {tt("Ask the AI tutor about this lesson")}</button>
  return (
    <section className="rounded-lg border border-accent/40 bg-surface p-4" aria-label={tt("AI tutor")}>
      <div className="mb-2 flex items-center justify-between"><h3 className="flex items-center gap-2 text-sm font-semibold"><MessageCircle size={15} className="text-accent" /> {tt("AI tutor")}</h3><button className="text-xs text-muted hover:text-fg" onClick={() => setOpen(false)}>{tt("Close")}</button></div>
      <p className="mb-3 text-xs text-muted">{tt("Ask about what is written in this lesson. Answers come from the lesson and may contain mistakes: check them against the material or ask your teacher.")}</p>
      <div className="max-h-96 space-y-3 overflow-y-auto" aria-live="polite">
        {turns.map((t, i) => t.role === 'student'
          ? <div key={i} dir="auto" className="ms-8 rounded-lg bg-accent/10 px-3 py-2 text-sm">{t.text}</div>
          : <div key={i} dir="auto" className="me-8 rounded-lg bg-raised px-3 py-2 text-sm"><div className="prose-recall"><Markdown>{t.text}</Markdown></div></div>)}
        {ask.isPending && <p className="text-sm text-muted">{tt("Thinking…")}</p>}
        <div ref={end} />
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim().length >= 2 && !ask.isPending) ask.mutate(q.trim()) }}>
        <input className="field flex-1" dir="auto" value={q} onChange={(e) => setQ(e.target.value)} maxLength={2000} placeholder={tt("Type your question…")} aria-label={tt("Your question")} />
        <Button type="submit" className="btn-primary" loading={ask.isPending} disabled={q.trim().length < 2}><Send size={14} className="rtl:-scale-x-100" /> {tt("Send")}</Button>
      </form>
      {remaining !== null && remaining < 10 && <p className="mt-1 text-xs text-muted">{tt("Questions left today: {n}", { n: remaining })}</p>}
    </section>
  )
}
