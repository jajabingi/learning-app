import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { get, post } from '@/api/client'
import type { Block, QuestionDraft } from '@/api/types'
import { BlockView } from '@/components/lms/BlockView'
import { Markdown } from '@/components/Markdown'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Field, Loading, Modal, Tabs, cx } from '@/components/ui'
import { useToast } from '@/contexts/toast'

interface Draft { title: string; summary: string; lessons: { title: string; summary: string; estimated_minutes: number; blocks: { type: Block['type']; data: Record<string, any> }[] }[] }
type QDraft = QuestionDraft & { _keep: boolean; _edit: boolean }
type Mode = 'module' | 'questions'

/** AI studio: describe what you want, review the DRAFT, then import it. Nothing is saved until you confirm.
 * The API key lives on the server (ANTHROPIC_API_KEY or OPENAI_API_KEY). */
export function AiStudio({ courseId, practiceSetId, initialMode = 'module', onClose }: { courseId: string; practiceSetId?: string; initialMode?: Mode; onClose(): void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const status = useQuery({ queryKey: ['teach-ai-status'], queryFn: () => get<{ enabled: boolean; provider: string | null; model: string | null }>('/teach/ai/status') })
  const [mode, setMode] = useState<Mode>(initialMode)
  const [prompt, setPrompt] = useState('')
  const [language, setLanguage] = useState<'he' | 'en'>('he')
  const [lessons, setLessons] = useState(4)
  const [count, setCount] = useState(5)
  const [level, setLevel] = useState('mixed')
  const [steps, setSteps] = useState(true)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [qs, setQs] = useState<QDraft[] | null>(null)
  const [error, setError] = useState('')

  const genModule = useMutation({ mutationFn: () => post<{ draft: Draft }>('/teach/ai/module-draft', { prompt, lessons, language }), onSuccess: (r) => { setError(''); setDraft(r.draft) }, onError: (e) => setError(e instanceof Error ? e.message : 'Failed') })
  const importModule = useMutation({
    mutationFn: () => post<{ lessons: number; blocks: number; skipped_blocks: number }>(`/teach/ai/courses/${courseId}/import-module`, { draft }),
    onSuccess: (r) => { qc.invalidateQueries(); toast.ok(`Module imported as a draft: ${r.lessons} lessons, ${r.blocks} blocks${r.skipped_blocks ? ` (${r.skipped_blocks} invalid blocks skipped)` : ''}. Review and publish it.`); onClose() },
    onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed'),
  })
  const genQs = useMutation({ mutationFn: () => post<{ questions: QuestionDraft[] }>('/teach/ai/question-drafts', { prompt, count, level, language, steps }), onSuccess: (r) => { setError(''); setQs(r.questions.map((q) => ({ ...q, _keep: true, _edit: false }))) }, onError: (e) => setError(e instanceof Error ? e.message : 'Failed') })
  const saveQs = useMutation({
    mutationFn: async () => {
      const chosen = qs!.filter((q) => q._keep).map(({ _keep, _edit, ...q }) => q)
      const saved = await post<{ id: string }[]>('/questions/batch', chosen)
      if (practiceSetId) await post(`/teach/practice-sets/${practiceSetId}/items`, { question_ids: saved.map((s) => s.id) })
      return saved.length
    },
    onSuccess: (n) => { qc.invalidateQueries(); toast.ok(practiceSetId ? `${n} questions saved and added to the set` : `${n} questions saved to your question bank`); onClose() },
    onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed'),
  })
  const kept = qs?.filter((q) => q._keep).length ?? 0
  const upd = (i: number, p: Partial<QDraft>) => setQs((a) => a!.map((x, j) => (j === i ? { ...x, ...p } : x)))
  const showForm = mode === 'module' ? !draft : !qs

  return (
    <Modal open onClose={onClose} wide title={<span className="inline-flex items-center gap-2"><Sparkles size={15} /> AI studio</span>}
      footer={showForm ? (
        <><button className="btn" onClick={onClose}>Cancel</button>
          <Button className="btn-primary" disabled={!status.data?.enabled || prompt.trim().length < 10} loading={genModule.isPending || genQs.isPending} onClick={() => { setError(''); mode === 'module' ? genModule.mutate() : genQs.mutate() }}><Sparkles size={14} /> Generate draft</Button></>
      ) : mode === 'module' ? (
        <><button className="btn" onClick={() => setDraft(null)}>Back</button><Button className="btn-primary" loading={importModule.isPending} onClick={() => importModule.mutate()}>Import as new module (unpublished)</Button></>
      ) : (
        <><button className="btn" onClick={() => setQs(null)}>Back</button><Button className="btn-primary" disabled={!kept} loading={saveQs.isPending} onClick={() => saveQs.mutate()}>Save {kept} selected{practiceSetId ? ' and add to set' : ''}</Button></>
      )}>
      {status.isLoading ? <Loading /> : !status.data?.enabled && (
        <div className="mb-4 rounded border border-warn/40 bg-warn/10 p-3 text-sm">
          AI is not configured on the server. Set <code className="font-mono">ANTHROPIC_API_KEY</code> (Claude) or <code className="font-mono">AI_PROVIDER=openai</code> + <code className="font-mono">OPENAI_API_KEY</code> (ChatGPT) in <code className="font-mono">backend/.env</code> and restart the API. The key never reaches the browser.
        </div>
      )}
      {status.data?.enabled && <p className="mb-3 text-xs text-muted">Provider: {status.data.provider} · model: {status.data.model}. Generated content is a draft: review it before importing.</p>}
      {showForm ? (
        <div className="space-y-4">
          {!practiceSetId && <Tabs<Mode> value={mode} onChange={(m) => { setMode(m); setError('') }} tabs={[{ id: 'module', label: 'New module' }, { id: 'questions', label: 'Questions with solutions' }]} />}
          <Field label={mode === 'module' ? 'What should the module teach? (topic, level, what to include)' : 'What should the questions cover?'}>
            <textarea className="field" dir="auto" rows={6} value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={20000}
              placeholder={mode === 'module' ? 'למשל: מודול על Duration ו-Convexity באג״ח, לסטודנטים לתואר ראשון. לכלול הגדרות, נוסחאות, דוגמה מחושבת וסיכום.' : 'למשל: 5 שאלות חישוב על Annuity ו-Perpetuity, עם פתרון מלא שלב אחר שלב.'} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Language"><select className="field" value={language} onChange={(e) => setLanguage(e.target.value as 'he' | 'en')}><option value="he">Hebrew (formulas & acronyms stay in English)</option><option value="en">English</option></select></Field>
            {mode === 'module' ? <Field label="Number of lessons"><input type="number" min={1} max={10} className="field" value={lessons} onChange={(e) => setLessons(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} /></Field> : (
              <>
                <Field label="Number of questions"><input type="number" min={1} max={20} className="field" value={count} onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} /></Field>
                <Field label="Level"><select className="field" value={level} onChange={(e) => setLevel(e.target.value)}><option value="mixed">Mixed</option><option value="basic">Basic</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></Field>
              </>
            )}
          </div>
          {mode === 'questions' && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={steps} onChange={(e) => setSteps(e.target.checked)} /> Full step-by-step solution in the explanation</label>}
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        </div>
      ) : mode === 'module' && draft ? (
        <div className="space-y-4">
          <div><h2 dir="auto" className="text-lg font-semibold">{draft.title}</h2>{draft.summary && <Markdown className="text-muted">{draft.summary}</Markdown>}</div>
          {draft.lessons.map((l, i) => (
            <details key={i} className="card p-3" open={i === 0}><summary className="cursor-pointer text-sm font-medium"><span dir="auto">{i + 1}. {l.title}</span> <span className="text-xs text-muted">· {l.blocks.length} blocks · {l.estimated_minutes} min</span></summary>
              <div className="mt-3 space-y-4">{l.blocks.map((b, k) => <BlockView key={k} block={{ id: String(k), type: b.type, position: k, data: b.data }} />)}</div></details>
          ))}
        </div>
      ) : qs && (
        <div className="space-y-3">
          <p className="text-sm text-muted">Review the drafts. Deselect or edit before saving; only selected questions are saved{practiceSetId ? ' and added to the set' : ' to your private question bank'}.</p>
          {qs.map((d, i) => (
            <div key={i} className={cx('card p-3', !d._keep && 'opacity-60')}>
              <div className="flex items-start gap-3">
                <input type="checkbox" className="mt-1" checked={d._keep} onChange={(e) => upd(i, { _keep: e.target.checked })} aria-label={`Keep question ${i + 1}`} />
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-1.5"><Badge>{d.question_type.replace('_', ' ')}</Badge><Badge className="capitalize">{d.difficulty}</Badge><button className="ms-auto text-xs text-accent" onClick={() => upd(i, { _edit: !d._edit })}>{d._edit ? 'Done' : 'Edit'}</button></div>
                  {d._edit ? (
                    <div className="space-y-2"><textarea dir="auto" className="field" rows={3} value={d.content} onChange={(e) => upd(i, { content: e.target.value })} aria-label="Question" /><textarea dir="auto" className="field" rows={2} value={d.answer.answer} onChange={(e) => upd(i, { answer: { ...d.answer, answer: e.target.value } })} aria-label="Answer" /><textarea dir="auto" className="field font-mono" rows={6} value={d.answer.explanation} onChange={(e) => upd(i, { answer: { ...d.answer, explanation: e.target.value } })} aria-label="Solution" /></div>
                  ) : (
                    <><Markdown>{d.content}</Markdown>{d.options.length > 0 && <ul className="mt-2 space-y-0.5 text-sm">{d.options.map((o, k) => <li key={k} dir="auto" className={o.is_correct ? 'font-medium text-good' : 'text-muted'}>{o.is_correct ? '✓' : '○'} {o.text}</li>)}</ul>}
                      <details className="mt-2 text-sm"><summary className="cursor-pointer text-muted">Answer &amp; solution</summary><div className="mt-1"><Markdown>{d.answer.answer}</Markdown><Markdown className="text-muted">{d.answer.explanation}</Markdown></div></details></>
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
