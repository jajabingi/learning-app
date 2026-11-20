import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles, Upload } from 'lucide-react'
import { post } from '@/api/client'
import { QUESTION_TYPES, type QuestionDraft, type QuestionType } from '@/api/types'
import { useAiStatus } from '@/hooks/queries'
import { useToast } from '@/contexts/toast'
import { Markdown } from './Markdown'
import { TopicPicker } from './TopicPicker'
import { Badge, Button, Field, Modal, cx } from './ui'

type Draft = QuestionDraft & { _keep: boolean; _edit: boolean }

export function AiGenerateDialog({ onClose, initial }: { onClose(): void; initial?: { topic_id?: string; text?: string; note_id?: string } }) {
  const status = useAiStatus()
  const toast = useToast()
  const qc = useQueryClient()
  const [text, setText] = useState(initial?.text ?? '')
  const [topic, setTopic] = useState<string[]>(initial?.topic_id ? [initial.topic_id] : [])
  const [count, setCount] = useState(5)
  const [level, setLevel] = useState('mixed')
  const [types, setTypes] = useState<QuestionType[]>([])
  const [drafts, setDrafts] = useState<Draft[] | null>(null)
  const [error, setError] = useState('')
  const file = useRef<HTMLInputElement>(null)

  const gen = useMutation({
    mutationFn: () => post<{ questions: QuestionDraft[] }>('/ai/generate-questions', { text, topic_id: topic[0] ?? null, note_id: initial?.note_id ?? null, count, level, types }),
    onSuccess: (r) => { setError(''); setDrafts(r.questions.map((q) => ({ ...q, _keep: true, _edit: false }))) },
    onError: (e) => setError(e instanceof Error ? e.message : 'Generation failed'),
  })
  const save = useMutation({
    mutationFn: () => post('/questions/batch', drafts!.filter((d) => d._keep).map(({ _keep, _edit, ...q }) => q)),
    onSuccess: () => { qc.invalidateQueries(); toast.ok('Questions saved to your question bank'); onClose() },
    onError: (e) => toast.err(e instanceof Error ? e.message : 'Could not save'),
  })

  const update = (i: number, p: Partial<Draft>) => setDrafts((d) => d!.map((x, j) => (j === i ? { ...x, ...p } : x)))
  const kept = drafts?.filter((d) => d._keep).length ?? 0

  async function readFile(f: File) {
    if (!/\.(txt|md|markdown|csv)$/i.test(f.name)) return toast.err('Text, Markdown or CSV files only. PDF and Word import are not available yet.')
    if (f.size > 500_000) return toast.err('File too large (500 KB max)')
    const body = await f.text()
    setText((t) => (t ? t + '\n\n' : '') + body)
  }

  return (
    <Modal open onClose={onClose} wide title={<span className="inline-flex items-center gap-2"><Sparkles size={15} /> Generate questions with AI</span>}
      footer={drafts ? (
        <>
          <button className="btn" onClick={() => setDrafts(null)}>Back</button>
          <Button className="btn-primary" disabled={!kept} loading={save.isPending} onClick={() => save.mutate()}>Save {kept} selected</Button>
        </>
      ) : (
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <Button className="btn-primary" loading={gen.isPending} disabled={!status.data?.enabled || (!text.trim() && !topic.length && !initial?.note_id)} onClick={() => { setError(''); gen.mutate() }}>
            <Sparkles size={14} /> Generate
          </Button>
        </>
      )}>
      {status.data && !status.data.enabled && (
        <p className="mb-3 rounded border border-warn/40 bg-warn/10 p-3 text-sm">AI is not configured on the server. Set <code className="font-mono">ANTHROPIC_API_KEY</code> in the backend environment and restart.</p>
      )}
      {!drafts ? (
        <div className="space-y-4">
          <div>
            <span className="label">Source material</span>
            <textarea className="field font-mono" rows={7} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste notes, an article or any text…" maxLength={60000} />
            <div className="mt-1.5 flex items-center justify-between">
              <button type="button" className="btn btn-ghost" onClick={() => file.current?.click()}><Upload size={14} /> Load .txt / .md file</button>
              <input ref={file} type="file" hidden accept=".txt,.md,.markdown,.csv,text/plain" onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f); e.target.value = '' }} />
              <span className="text-xs text-faint">{text.length.toLocaleString()} / 60,000</span>
            </div>
          </div>
          <div>
            <span className="label">Or base it on a topic (uses its description and notes)</span>
            <TopicPicker single value={topic} onChange={setTopic} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Number of questions"><input type="number" min={1} max={20} className="field" value={count} onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} /></Field>
            <Field label="Level">
              <select className="field" value={level} onChange={(e) => setLevel(e.target.value)}>
                <option value="mixed">Mixed</option><option value="basic">Basic</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option>
              </select>
            </Field>
          </div>
          <div>
            <span className="label">Question types (none selected = AI chooses)</span>
            <div className="flex flex-wrap gap-1.5">
              {QUESTION_TYPES.map((t) => {
                const on = types.includes(t.value)
                return <button type="button" key={t.value} aria-pressed={on} onClick={() => setTypes(on ? types.filter((x) => x !== t.value) : [...types, t.value])} className={cx('rounded border px-2 py-1 text-xs', on ? 'border-accent bg-accent/10 text-accent' : 'border-line text-muted hover:bg-raised')}>{t.label}</button>
              })}
            </div>
          </div>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          <p className="text-xs text-faint">Nothing is saved until you review the drafts and confirm.</p>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-muted">Review the drafts. Edit, deselect or keep each one — only selected questions are saved.</p>
          {drafts.map((d, i) => (
            <div key={i} className={cx('card p-3', !d._keep && 'opacity-60')}>
              <div className="flex items-start gap-3">
                <input type="checkbox" className="mt-1" checked={d._keep} onChange={(e) => update(i, { _keep: e.target.checked })} aria-label={`Keep question ${i + 1}`} />
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex flex-wrap items-center gap-1.5">
                    <Badge>{QUESTION_TYPES.find((t) => t.value === d.question_type)?.label}</Badge><Badge className="capitalize">{d.difficulty}</Badge>
                    <button className="ml-auto text-xs text-accent" onClick={() => update(i, { _edit: !d._edit })}>{d._edit ? 'Done' : 'Edit'}</button>
                  </div>
                  {d._edit ? (
                    <div className="space-y-2">
                      <textarea className="field" rows={3} value={d.content} onChange={(e) => update(i, { content: e.target.value })} aria-label="Question text" />
                      <textarea className="field" rows={3} value={d.answer.answer} onChange={(e) => update(i, { answer: { ...d.answer, answer: e.target.value } })} aria-label="Answer" />
                      <textarea className="field" rows={2} value={d.answer.explanation} onChange={(e) => update(i, { answer: { ...d.answer, explanation: e.target.value } })} aria-label="Explanation" />
                      {d.options.map((o, k) => (
                        <div key={k} className="flex items-center gap-2">
                          <input type="checkbox" checked={o.is_correct} onChange={(e) => update(i, { options: d.options.map((x, j) => (j === k ? { ...x, is_correct: e.target.checked } : x)) })} aria-label="Correct" />
                          <input className="field" value={o.text} onChange={(e) => update(i, { options: d.options.map((x, j) => (j === k ? { ...x, text: e.target.value } : x)) })} />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <>
                      <Markdown>{d.content}</Markdown>
                      {d.options.length > 0 && <ul className="mt-2 space-y-0.5 text-sm">{d.options.map((o, k) => <li key={k} className={o.is_correct ? 'font-medium text-good' : 'text-muted'}>{o.is_correct ? '✓' : '○'} {o.text}</li>)}</ul>}
                      <details className="mt-2 text-sm"><summary className="cursor-pointer text-muted">Answer & explanation</summary><div className="mt-1"><Markdown>{d.answer.answer}</Markdown>{d.answer.explanation && <Markdown className="text-muted">{d.answer.explanation}</Markdown>}</div></details>
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}
