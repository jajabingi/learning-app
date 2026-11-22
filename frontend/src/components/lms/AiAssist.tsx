import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { get, post } from '@/api/client'
import { Markdown } from '@/components/Markdown'
import { Button, Field, Modal } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { tt } from '@/i18n'

export const AI_BLOCK_TYPES = ['text', 'rich_text', 'summary', 'example', 'table', 'formula', 'callout']
type Data = Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any

const IDEAS: Record<string, string[]> = {
  text: ['Explain the concept simply', 'Give a formal definition', 'Add a real-life analogy'],
  rich_text: ['Explain the topic in depth with headings', 'Cover common mistakes'],
  summary: ['Key points of the lesson', 'Revision checklist'],
  example: ['A worked numerical example, step by step', 'A real-world case'],
  table: ['Compare the main alternatives', 'A table of formulas and when to use them'],
  formula: ['The key formula with a symbol legend', 'The formula and when to use it'],
  callout: ['A useful tip', 'A common mistake to avoid', 'A key point to remember'],
}
const REWRITES: [string, string][] = [['shorter', 'Shorter'], ['simpler', 'Simpler'], ['advanced', 'More advanced'], ['add_example', 'Add an example'], ['add_steps', 'Add step-by-step'], ['translate_en', 'Translate to English'], ['translate_he', 'Translate to Hebrew'], ['fix', 'Fix and polish']]
const hasContent = (d: Data) => !!(d?.markdown || d?.latex || d?.description)

/** "Create with AI" for one content block. Generates a DRAFT; nothing is saved until the teacher applies it and saves the block. */
export function AiAssistButton({ lessonId, type, data, onApply }: { lessonId: string; type: string; data: Data; onApply(d: Data): void }) {
  const [open, setOpen] = useState(false)
  const status = useQuery({ queryKey: ['ai-status'], queryFn: () => get<{ enabled: boolean; used_today?: number; daily_limit?: number }>('/teach/ai/status'), staleTime: 60_000 })
  if (!AI_BLOCK_TYPES.includes(type)) return null
  return (
    <>
      <button type="button" className="btn gap-1.5 border-accent/40 text-accent" onClick={() => setOpen(true)}><Sparkles size={14} /> {tt("Create with AI")}</button>
      {open && <AssistModal lessonId={lessonId} type={type} data={data} enabled={status.data?.enabled !== false} onClose={() => setOpen(false)} onApply={(d) => { onApply(d); setOpen(false) }} />}
    </>
  )
}

function Preview({ type, d }: { type: string; d: Data }) {
  if (type === 'formula') return <div className="space-y-2">{d.title && <h4 dir="auto" className="font-semibold">{d.title}</h4>}<Markdown>{`$$${d.latex ?? ''}$$`}</Markdown>{d.description && <Markdown>{d.description}</Markdown>}</div>
  return <div dir="auto" className="prose-recall">{d.title && <h4 className="font-semibold">{d.title}</h4>}<Markdown>{d.markdown ?? ''}</Markdown></div>
}

function AssistModal({ lessonId, type, data, enabled, onClose, onApply }: { lessonId: string; type: string; data: Data; enabled: boolean; onClose(): void; onApply(d: Data): void }) {
  const toast = useToast()
  const [instruction, setInstruction] = useState('')
  const [language, setLanguage] = useState<'he' | 'en'>('he')
  const [draft, setDraft] = useState<Data | null>(null)
  const gen = useMutation({
    mutationFn: (rewrite?: string) => post<{ draft: { data: Data } }>('/teach/ai/block-draft', { lesson_id: lessonId, block_type: type, instruction, language, rewrite: rewrite ?? null, current: rewrite && hasContent(data) ? data : null }),
    onSuccess: (r) => setDraft(r.draft.data), onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")),
  })
  return (
    <Modal open onClose={onClose} wide title={tt("Create with AI")} footer={<><button className="btn" onClick={onClose}>{tt("Cancel")}</button>{draft && <Button className="btn-primary" onClick={() => onApply(draft)}>{tt("Use this draft")}</Button>}</>}>
      <div className="space-y-4">
        {!enabled && <p role="alert" className="rounded border border-warn/40 bg-warn/10 p-3 text-sm">{tt("AI is not configured on the server. Add ANTHROPIC_API_KEY to the backend environment.")}</p>}
        <p className="text-sm text-muted">{tt("The AI sees your course, the lesson and what it already contains. It writes a draft: review and edit it before saving.")}</p>
        <Field label={tt("What should it write?")}><textarea className="field" dir="auto" rows={3} value={instruction} maxLength={4000} onChange={(e) => setInstruction(e.target.value)} placeholder={tt("e.g. Explain NPV and why a higher discount rate lowers it")} /></Field>
        <div className="flex flex-wrap gap-1.5">{(IDEAS[type] ?? []).map((i) => <button key={i} type="button" className="rounded-full border border-line px-2.5 py-1 text-xs hover:border-accent" onClick={() => setInstruction(tt(i))}>{tt(i)}</button>)}</div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">{tt("Language")}<select className="field h-8 w-auto py-0" value={language} onChange={(e) => setLanguage(e.target.value as 'he' | 'en')}><option value="he">{tt("Hebrew")}</option><option value="en">{tt("English")}</option></select></label>
          <Button className="btn-primary" disabled={!enabled} loading={gen.isPending} onClick={() => gen.mutate(undefined)}>{draft ? tt("Generate again") : tt("Generate")}</Button>
        </div>
        {hasContent(data) && <div><span className="label">{tt("Or improve the current text")}</span><div className="flex flex-wrap gap-1.5">{REWRITES.map(([k, l]) => <button key={k} type="button" disabled={!enabled || gen.isPending} className="rounded-full border border-line px-2.5 py-1 text-xs hover:border-accent disabled:opacity-50" onClick={() => gen.mutate(k)}>{tt(l)}</button>)}</div></div>}
        {draft && <div className="rounded-lg border border-dashed border-accent/50 p-4"><p className="mb-2 text-xs text-accent">{tt("AI draft — check the facts and the maths")}</p><Preview type={type} d={draft} /></div>}
      </div>
    </Modal>
  )
}

/** Writes the lesson's closing summary from the lesson's own content. */
export function AiSummaryButton({ lessonId, current, onDraft }: { lessonId: string; current: string; onDraft(md: string): void }) {
  const toast = useToast()
  const status = useQuery({ queryKey: ['ai-status'], queryFn: () => get<{ enabled: boolean }>('/teach/ai/status'), staleTime: 60_000 })
  const m = useMutation({ mutationFn: () => post<{ markdown: string }>('/teach/ai/lesson-summary', { lesson_id: lessonId, language: 'he' }),
    onSuccess: (r) => onDraft(r.markdown), onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")) })
  return (
    <Button type="button" className="gap-1.5" loading={m.isPending} disabled={status.data?.enabled === false}
      onClick={() => { if (!current.trim() || confirm(tt("Replace the current summary with an AI draft?"))) m.mutate() }}><Sparkles size={14} /> {tt("Write the summary with AI")}</Button>
  )
}
