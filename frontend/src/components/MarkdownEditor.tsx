import { useRef, useState } from 'react'
import { Bold, Code, Heading2, Image as ImageIcon, Italic, Link2, List, ListOrdered, Quote, Sigma, SquareCode, Table2 } from 'lucide-react'
import { api } from '@/api/client'
import { useToast } from '@/contexts/toast'
import { Markdown } from './Markdown'
import { Segmented, cx } from './ui'
import { tt } from '@/i18n'


interface Props {
  value: string
  onChange(v: string): void
  placeholder?: string
  minRows?: number
  label?: string
  /** Attach uploaded images to this entity */
  attach?: { question_id?: string; note_id?: string }
  textareaRef?: React.RefObject<HTMLTextAreaElement>
}

export function MarkdownEditor({ value, onChange, placeholder, minRows = 6, label, attach, textareaRef }: Props) {
  const own = useRef<HTMLTextAreaElement>(null)
  const ta = textareaRef ?? own
  const fileRef = useRef<HTMLInputElement>(null)
  const [view, setView] = useState<'write' | 'preview'>('write')
  const toast = useToast()

  function edit(fn: (sel: string, before: string, after: string) => { text: string; select?: [number, number] }) {
    const el = ta.current
    if (!el) return
    const { selectionStart: s, selectionEnd: e } = el
    const r = fn(value.slice(s, e), value.slice(0, s), value.slice(e))
    onChange(r.text)
    requestAnimationFrame(() => {
      el.focus()
      if (r.select) el.setSelectionRange(r.select[0], r.select[1])
    })
  }
  const wrap = (l: string, r = l, ph = 'text') => () =>
    edit((sel, b, a) => {
      const inner = sel || ph
      return { text: b + l + inner + r + a, select: [b.length + l.length, b.length + l.length + inner.length] }
    })
  const linePrefix = (p: string) => () =>
    edit((sel, b, a) => {
      const lines = (sel || 'item').split('\n').map((x, i) => (p === '1. ' ? `${i + 1}. ` : p) + x)
      const t = lines.join('\n')
      const nl = b && !b.endsWith('\n') ? '\n' : ''
      return { text: b + nl + t + a, select: [b.length + nl.length, b.length + nl.length + t.length] }
    })
  const block = (l: string, r: string, ph: string) => () =>
    edit((sel, b, a) => {
      const inner = sel || ph
      const nl = b && !b.endsWith('\n') ? '\n' : ''
      return { text: b + nl + l + inner + r + a, select: [b.length + nl.length + l.length, b.length + nl.length + l.length + inner.length] }
    })

  async function upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    if (attach?.question_id) form.append('question_id', attach.question_id)
    if (attach?.note_id) form.append('note_id', attach.note_id)
    try {
      const a = await api<{ id: string; filename: string; url: string }>('/attachments', { form })
      const isImg = /\.(png|jpe?g|gif|webp)$/i.test(a.filename)
      edit((sel, b, af) => ({ text: b + `${isImg ? '!' : ''}[${sel || a.filename}](${a.url})` + af }))
    } catch (e) {
      toast.err(e instanceof Error ? e.message : tt("Upload failed"))
    }
  }

  const tools = [
    { i: Heading2, t: tt("Heading"), f: linePrefix('## ') },
    { i: Bold, t: tt("Bold"), f: wrap('**') },
    { i: Italic, t: tt("Italic"), f: wrap('*') },
    { i: List, t: tt("Bulleted list"), f: linePrefix('- ') },
    { i: ListOrdered, t: tt("Numbered list"), f: linePrefix('1. ') },
    { i: Quote, t: tt("Quote"), f: linePrefix('> ') },
    { i: Code, t: tt("Inline code"), f: wrap('`', '`', 'code') },
    { i: SquareCode, t: tt("Code block"), f: block('```python\n', '\n```\n', 'code') },
    { i: Sigma, t: tt("Math (LaTeX)"), f: wrap('$', '$', 'x^2') },
    { i: Table2, t: tt("Table"), f: block('| A | B |\n| --- | --- |\n| ', ' | |\n', '1') },
    { i: Link2, t: tt("Link"), f: () => edit((sel, b, a) => ({ text: b + `[${sel || 'text'}](https://)` + a })) },
  ]

  return (
    <div className="rounded border border-line bg-surface focus-within:border-accent">
      <div className="flex flex-wrap items-center justify-between gap-1 border-b border-line px-1.5 py-1">
        <div className="flex flex-wrap items-center gap-0.5" role="toolbar" aria-label={`${label ?? 'Editor'} formatting`}>
          {tools.map(({ i: I, t, f }) => (
            <button key={t} type="button" title={t} aria-label={t} onClick={f} disabled={view === 'preview'} className="btn btn-ghost btn-icon h-7 w-7 text-muted">
              <I size={14} />
            </button>
          ))}
          <button type="button" title={tt("Insert image or file")} aria-label={tt("Insert image or file")} className="btn btn-ghost btn-icon h-7 w-7 text-muted" onClick={() => fileRef.current?.click()} disabled={view === 'preview'}>
            <ImageIcon size={14} />
          </button>
          <input ref={fileRef} type="file" hidden accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/csv" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = '' }} />
        </div>
        <Segmented<'write' | 'preview'> value={view} onChange={setView} label={tt("Editor view")} options={[{ value: 'write', label: tt("Write") }, { value: 'preview', label: tt("Preview") }]} />
      </div>
      {view === 'write' ? (
        <textarea
          ref={ta}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? tt("Markdown supported · $LaTeX$ · tables · code")}
          rows={minRows}
          aria-label={label}
          dir="auto"
          className="block w-full resize-y bg-transparent px-3 py-2 font-mono text-sm leading-relaxed outline-none placeholder:font-sans placeholder:text-faint"
          onPaste={(e) => {
            const f = Array.from(e.clipboardData.files).find((x) => x.type.startsWith('image/'))
            if (f) { e.preventDefault(); upload(f) }
          }}
        />
      ) : (
        <div className={cx('px-3 py-2')} style={{ minHeight: `${minRows * 1.6}rem` }}>
          {value.trim() ? <Markdown>{value}</Markdown> : <p className="text-sm text-faint">{tt("Nothing to preview")}</p>}
        </div>
      )}
    </div>
  )
}
