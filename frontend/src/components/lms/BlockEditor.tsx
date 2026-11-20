import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Upload, X } from 'lucide-react'
import { api, get, uploadWithProgress } from '@/api/client'
import type { BlockType, QuestionPage } from '@/api/types'
import { MarkdownEditor } from '@/components/MarkdownEditor'
import { Field } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { plain } from '@/lib/format'

type F =
  | { key: string; label: string; kind: 'text' | 'url' | 'textarea' | 'markdown' | 'number'; hint?: string; rows?: number }
  | { key: string; label: string; kind: 'select'; options: [string, string][] }
  | { key: string; label: string; kind: 'checkbox' }
  | { key: string; label: string; kind: 'file'; accept: string; hint?: string }
  | { key: string; label: string; kind: 'video' }
  | { key: string; label: string; kind: 'question' }
  | { key: string; label: string; kind: 'questions' }

const IMG = 'image/png,image/jpeg,image/gif,image/webp'
export const BLOCK_META: Record<BlockType, { label: string; desc: string; fields: F[] }> = {
  video: { label: 'Video', desc: 'Upload from your computer, or paste a YouTube / Vimeo / direct link', fields: [
    { key: 'attachment_id', label: 'Upload a video from your computer', kind: 'video' },
    { key: 'url', label: '...or video URL', kind: 'url', hint: 'YouTube, Vimeo, or a direct https .mp4 / .webm / .m3u8 link' }, { key: 'title', label: 'Title', kind: 'text' },
    { key: 'description', label: 'Description', kind: 'textarea' }, { key: 'thumbnail_url', label: 'Thumbnail URL (optional)', kind: 'url' }] },
  text: { label: 'Text', desc: 'Written explanation (Markdown)', fields: [{ key: 'title', label: 'Heading (optional)', kind: 'text' }, { key: 'markdown', label: 'Content', kind: 'markdown' }] },
  rich_text: { label: 'Rich-text explanation', desc: 'Long-form content with headings, lists, code, math', fields: [{ key: 'title', label: 'Heading (optional)', kind: 'text' }, { key: 'markdown', label: 'Content', kind: 'markdown', rows: 12 }] },
  summary: { label: 'Summary', desc: 'Key points of the lesson', fields: [{ key: 'title', label: 'Title', kind: 'text' }, { key: 'markdown', label: 'Summary', kind: 'markdown' }] },
  image: { label: 'Image', desc: 'Uploaded or linked image', fields: [{ key: 'attachment_id', label: 'Upload image', kind: 'file', accept: IMG }, { key: 'url', label: '…or image URL (https)', kind: 'url' }, { key: 'alt', label: 'Alt text', kind: 'text' }, { key: 'caption', label: 'Caption', kind: 'text' }] },
  pdf: { label: 'PDF', desc: 'PDF document students can open', fields: [{ key: 'attachment_id', label: 'Upload PDF', kind: 'file', accept: 'application/pdf' }, { key: 'url', label: '…or PDF URL', kind: 'url' }, { key: 'title', label: 'Title', kind: 'text' }, { key: 'description', label: 'Description', kind: 'textarea' }] },
  file: { label: 'File attachment', desc: 'Any supported file', fields: [{ key: 'attachment_id', label: 'Upload file', kind: 'file', accept: '.pdf,.png,.jpg,.jpeg,.gif,.webp,.txt,.csv,.md,.json' }, { key: 'url', label: '…or file URL', kind: 'url' }, { key: 'title', label: 'Title', kind: 'text' }, { key: 'description', label: 'Description', kind: 'textarea' }] },
  resource: { label: 'Downloadable resource', desc: 'Worksheet, template, reading list…', fields: [{ key: 'attachment_id', label: 'Upload file', kind: 'file', accept: '.pdf,.png,.jpg,.jpeg,.gif,.webp,.txt,.csv,.md,.json' }, { key: 'url', label: '…or URL', kind: 'url' }, { key: 'title', label: 'Title', kind: 'text' }, { key: 'description', label: 'Description', kind: 'textarea' }] },
  formula: { label: 'Formula', desc: 'LaTeX formula with explanation', fields: [{ key: 'title', label: 'Name', kind: 'text' }, { key: 'latex', label: 'LaTeX', kind: 'textarea', rows: 3, hint: 'e.g. NPV = \\sum_{t=0}^{n} \\frac{CF_t}{(1+r)^t}' }, { key: 'description', label: 'Explanation (optional)', kind: 'textarea' }] },
  table: { label: 'Table', desc: 'Markdown table', fields: [{ key: 'title', label: 'Title (optional)', kind: 'text' }, { key: 'markdown', label: 'Table (Markdown)', kind: 'markdown', rows: 6 }] },
  example: { label: 'Example', desc: 'Worked example', fields: [{ key: 'title', label: 'Title', kind: 'text' }, { key: 'markdown', label: 'Worked example', kind: 'markdown' }] },
  callout: { label: 'Callout', desc: 'Highlighted note, tip or warning', fields: [{ key: 'variant', label: 'Style', kind: 'select', options: [['info', 'Info'], ['tip', 'Tip'], ['warning', 'Warning'], ['important', 'Important']] }, { key: 'markdown', label: 'Content', kind: 'markdown', rows: 4 }] },
  external_link: { label: 'External link', desc: 'Link to further reading', fields: [{ key: 'url', label: 'URL', kind: 'url' }, { key: 'title', label: 'Title', kind: 'text' }, { key: 'description', label: 'Description', kind: 'textarea' }] },
  question: { label: 'Practice question', desc: 'One question from your private bank', fields: [{ key: 'question_id', label: 'Question', kind: 'question' }, { key: 'show_answer', label: 'Reveal answer', kind: 'select', options: [['after_attempt', 'After the student answers'], ['always', 'Always'], ['never', 'Never']] }] },
  quiz: { label: 'Quiz', desc: 'Several questions with scoring settings', fields: [
    { key: 'title', label: 'Title', kind: 'text' }, { key: 'question_ids', label: 'Questions from your bank', kind: 'questions' },
    { key: 'settings.time_limit_min', label: 'Time limit (minutes, optional)', kind: 'number' }, { key: 'settings.passing_grade', label: 'Passing grade (%)', kind: 'number' },
    { key: 'settings.attempts', label: 'Attempts allowed (empty = unlimited)', kind: 'number' }, { key: 'settings.shuffle', label: 'Randomise question order', kind: 'checkbox' },
    { key: 'settings.show_answers', label: 'Show answers', kind: 'select', options: [['after_submit', 'After submitting'], ['immediately', 'Immediately'], ['never', 'Never']] }] },
  assignment: { label: 'Assignment', desc: 'Instructions and points (submissions come in a later release)', fields: [{ key: 'title', label: 'Title', kind: 'text' }, { key: 'instructions', label: 'Instructions', kind: 'markdown', rows: 6 }, { key: 'points', label: 'Points', kind: 'number' }] },
}
export const BLOCK_ORDER: BlockType[] = ['video', 'text', 'rich_text', 'summary', 'formula', 'example', 'table', 'callout', 'image', 'pdf', 'file', 'resource', 'external_link', 'question', 'quiz', 'assignment']
export const DEFAULTS: Partial<Record<BlockType, Record<string, any>>> = {
  callout: { variant: 'info', markdown: '' }, question: { show_answer: 'after_attempt' }, quiz: { question_ids: [], settings: { passing_grade: 60, shuffle: false, show_answers: 'after_submit' } }, assignment: { points: 100 },
}

const getPath = (o: any, p: string) => p.split('.').reduce((a, k) => (a == null ? a : a[k]), o)
function setPath(o: any, p: string, v: any): any {
  const [h, ...rest] = p.split('.')
  return { ...o, [h]: rest.length ? setPath(o?.[h] ?? {}, rest.join('.'), v) : v }
}

export function BlockForm({ type, data, onChange }: { type: BlockType; data: Record<string, any>; onChange(d: Record<string, any>): void }) {
  const meta = BLOCK_META[type]
  return (
    <div className="space-y-3">
      {meta.fields.map((f) => {
        const v = getPath(data, f.key)
        const set = (x: any) => onChange(setPath(data, f.key, x))
        if (f.kind === 'markdown') return <div key={f.key}><span className="label">{f.label}</span><MarkdownEditor value={v ?? ''} onChange={set} label={f.label} minRows={f.rows ?? 8} /></div>
        if (f.kind === 'checkbox') return <label key={f.key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} /> {f.label}</label>
        if (f.kind === 'video') return <VideoField key={f.key} f={f} value={v} onChange={(x) => onChange({ ...data, attachment_id: x, ...(x ? { url: '' } : {}) })} />
        if (f.kind === 'file') return <FileField key={f.key} f={f} value={v} onChange={set} />
        if (f.kind === 'question') return <div key={f.key}><span className="label">{f.label}</span><QuestionPick multi={false} value={v ? [v] : []} onChange={(ids) => set(ids[0] ?? null)} /></div>
        if (f.kind === 'questions') return <div key={f.key}><span className="label">{f.label}</span><QuestionPick multi value={v ?? []} onChange={set} /></div>
        if (f.kind === 'select') return <Field key={f.key} label={f.label}><select className="field" value={v ?? f.options[0][0]} onChange={(e) => set(e.target.value)}>{f.options.map(([val, l]) => <option key={val} value={val}>{l}</option>)}</select></Field>
        if (f.kind === 'textarea') return <Field key={f.key} label={f.label} hint={f.hint}><textarea className="field font-mono" rows={f.rows ?? 3} value={v ?? ''} onChange={(e) => set(e.target.value)} /></Field>
        if (f.kind === 'number') return <Field key={f.key} label={f.label}><input type="number" className="field" min={0} value={v ?? ''} onChange={(e) => set(e.target.value === '' ? null : Number(e.target.value))} /></Field>
        return <Field key={f.key} label={f.label} hint={f.hint}><input type={f.kind === 'url' ? 'url' : 'text'} className="field" value={v ?? ''} onChange={(e) => set(e.target.value)} /></Field>
      })}
    </div>
  )
}

function FileField({ f, value, onChange }: { f: Extract<F, { kind: 'file' }>; value: string | null; onChange(v: string | null): void }) {
  const ref = useRef<HTMLInputElement>(null)
  const toast = useToast()
  const [name, setName] = useState('')
  async function up(file: File) {
    const form = new FormData()
    form.append('file', file)
    try {
      const a = await api<{ id: string; filename: string }>('/attachments', { form })
      setName(a.filename)
      onChange(a.id)
    } catch (e) { toast.err(e instanceof Error ? e.message : 'Upload failed') }
  }
  return (
    <div>
      <span className="label">{f.label}</span>
      <div className="flex items-center gap-2">
        <button type="button" className="btn" onClick={() => ref.current?.click()}><Upload size={14} /> {value ? 'Replace' : 'Choose file'}</button>
        {value && <span className="inline-flex items-center gap-1 text-sm text-muted">{name || 'File attached'}<button type="button" aria-label="Remove file" onClick={() => { onChange(null); setName('') }}><X size={13} /></button></span>}
        <input ref={ref} type="file" hidden accept={f.accept} onChange={(e) => { const x = e.target.files?.[0]; if (x) up(x); e.target.value = '' }} />
      </div>
    </div>
  )
}

function QuestionPick({ multi, value, onChange }: { multi: boolean; value: string[]; onChange(ids: string[]): void }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const res = useQuery({ queryKey: ['questions', 'lms-picker', q], queryFn: () => get<QuestionPage>('/questions', { q, page_size: 10 }), enabled: open })
  const names = useQuery({ queryKey: ['questions', 'lms-names', value], enabled: value.length > 0, queryFn: async () => Object.fromEntries(await Promise.all(value.map(async (id) => { try { const x = await get<{ title: string; content: string }>(`/questions/${id}`); return [id, x.title || plain(x.content, 70)] } catch { return [id, 'Missing question'] } }))) })
  return (
    <div>
      <div className="mb-1 flex flex-wrap gap-1">{value.map((id) => <span key={id} className="inline-flex max-w-full items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5 text-xs text-accent"><span className="truncate">{names.data?.[id] ?? '…'}</span><button type="button" aria-label="Remove question" onClick={() => onChange(value.filter((x) => x !== id))}><X size={11} /></button></span>)}</div>
      {(multi || !value.length) && (
        <div className="relative">
          <input className="field" placeholder="Search your question bank…" value={q} onFocus={() => setOpen(true)} onChange={(e) => { setQ(e.target.value); setOpen(true) }} aria-label="Search question bank" />
          {open && <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-line bg-surface py-1 shadow-lg">
            {res.data?.items.length === 0 && <div className="px-3 py-2 text-sm text-muted">No questions found</div>}
            {res.data?.items.filter((x) => !value.includes(x.id)).map((x) => <button type="button" key={x.id} className="block w-full truncate px-3 py-1.5 text-left text-sm hover:bg-raised" onClick={() => { onChange(multi ? [...value, x.id] : [x.id]); setQ(''); setOpen(multi) }}>{x.title || plain(x.content, 80)}</button>)}
            <button type="button" className="block w-full px-3 py-1 text-left text-xs text-muted hover:bg-raised" onClick={() => setOpen(false)}>Close</button>
          </div>}
        </div>
      )}
    </div>
  )
}

function VideoField({ f, value, onChange }: { f: { label: string }; value: string | null; onChange(v: string | null): void }) {
  const ref = useRef<HTMLInputElement>(null)
  const toast = useToast()
  const [pct, setPct] = useState<number | null>(null)
  const [name, setName] = useState('')
  async function up(file: File) {
    if (!/\.(mp4|m4v|webm)$/i.test(file.name)) return toast.err('Please choose an MP4 (H.264) or WebM file')
    setPct(0)
    try {
      const a = await uploadWithProgress<{ id: string; filename: string }>('/teach/videos', file, setPct)
      setName(a.filename)
      onChange(a.id)
      toast.ok('Video uploaded')
    } catch (e) { toast.err(e instanceof Error ? e.message : 'Upload failed') } finally { setPct(null) }
  }
  return (
    <div>
      <span className="label">{f.label}</span>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn" disabled={pct !== null} onClick={() => ref.current?.click()}><Upload size={14} /> {value ? 'Replace video' : 'Choose video file'}</button>
        {pct !== null && <div className="flex min-w-40 flex-1 items-center gap-2"><div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised"><div className="h-full bg-accent" style={{ width: `${pct}%` }} /></div><span className="text-xs tabnum text-muted">{pct}%</span></div>}
        {pct === null && value && <span className="inline-flex items-center gap-1 text-sm text-muted">{name || 'Video uploaded'}<button type="button" aria-label="Remove video" onClick={() => { onChange(null); setName('') }}><X size={13} /></button></span>}
        <input ref={ref} type="file" hidden accept="video/mp4,video/webm,.mp4,.m4v,.webm" onChange={(e) => { const x = e.target.files?.[0]; if (x) up(x); e.target.value = '' }} />
      </div>
      <p className="mt-1 text-xs text-faint">MP4 (H.264) or WebM, up to 1 GB. For many or very large videos, host them on YouTube/Vimeo/a video service and paste the link.</p>
    </div>
  )
}
