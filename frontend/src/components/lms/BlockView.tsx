import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Download, ExternalLink, FileText, Info, Lightbulb, Sigma, Star } from 'lucide-react'
import { raw } from '@/api/client'
import type { Block } from '@/api/types'
import { Markdown, useFileUrl } from '@/components/Markdown'
import { cx } from '@/components/ui'
import { t } from '@/i18n'

/** Renders a lesson block exactly as a student sees it. Shared by the teacher preview and the student portal. */
export function BlockView({ block }: { block: Block }) {
  const d = block.data
  const fileUrl = useFileUrl()
  switch (block.type) {
    case 'video':
      return <VideoPlayer data={d} />
    case 'text':
    case 'rich_text':
    case 'table':
      return <section>{d.title && <h3 dir="auto" className="mb-1 font-semibold">{d.title}</h3>}<Markdown>{d.markdown ?? ''}</Markdown></section>
    case 'summary':
      return <section className="rounded-lg border border-accent/30 bg-accent/5 p-4"><h3 dir="auto" className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-accent"><Star size={14} /> {d.title || t('blocks.summary')}</h3><Markdown>{d.markdown ?? ''}</Markdown></section>
    case 'example':
      return <section className="rounded-lg border border-line bg-raised/50 p-4"><h3 dir="auto" className="mb-1 text-sm font-semibold">{d.title || t('blocks.example')}</h3><Markdown>{d.markdown ?? ''}</Markdown></section>
    case 'callout': {
      const v = { info: [Info, 'border-accent/40 bg-accent/5'], tip: [Lightbulb, 'border-good/40 bg-good/5'], warning: [AlertTriangle, 'border-warn/50 bg-warn/10'], important: [Star, 'border-bad/40 bg-bad/5'] }[d.variant as string] ?? [Info, '']
      const Icon = v[0] as typeof Info
      return <aside className={cx('flex gap-3 rounded-lg border p-4', v[1] as string)}><Icon size={16} className="mt-1 shrink-0" /><Markdown>{d.markdown ?? ''}</Markdown></aside>
    }
    case 'formula':
      return <section className="rounded-lg border border-line p-4">{d.title && <h3 dir="auto" className="mb-1 flex items-center gap-1.5 text-sm font-semibold"><Sigma size={14} />{d.title}</h3>}<Markdown>{`$$\n${d.latex ?? ''}\n$$`}</Markdown>{d.description && <Markdown className="text-muted">{d.description}</Markdown>}</section>
    case 'image': {
      const src = d.attachment_id ? `/api/attachments/${d.attachment_id}/file` : d.url
      return <figure>{src ? <Markdown>{`![${(d.alt ?? '').replace(/[\]\[]/g, '')}](${d.attachment_id ? src : d.url})`}</Markdown> : null}{d.caption && <figcaption dir="auto" className="text-center text-xs text-muted">{d.caption}</figcaption>}</figure>
    }
    case 'pdf':
    case 'file':
    case 'resource':
      return <ResourceCard d={d} kind={block.type} mapUrl={fileUrl} />
    case 'external_link':
      return <a href={d.url} target="_blank" rel="noopener noreferrer nofollow" className="card flex items-center gap-3 p-3 hover:border-faint"><ExternalLink size={16} className="text-faint" /><span className="min-w-0"><span dir="auto" className="block truncate text-sm font-medium">{d.title || d.url}</span>{d.description && <span className="block text-xs text-muted">{d.description}</span>}</span></a>
    case 'question':
      return d.question ? <QuestionPreview q={d.question} /> : <Unavailable what="" />
    case 'quiz': {
      const n = d.question_count ?? d.questions?.length ?? 0
      const inTeacherPreview = typeof window !== 'undefined' && window.location.pathname.startsWith('/teach')
      return (
        <section className="card p-5">
          <h3 dir="auto" className="text-base font-semibold">{d.title || 'Quiz'}</h3>
          <p className="mt-1 text-sm text-muted">{t('blocks.quizInfo', { n })}{d.settings?.time_limit_min ? ` · ${d.settings.time_limit_min} ${t('viewer.min')}` : ''}</p>
          {d.practice_set_id ? (
            inTeacherPreview ? <p className="mt-3 text-sm text-muted">{t('blocks.teacherPreviewQuiz')}</p>
              : <Link to={`/practice/${d.practice_set_id}`} className="btn btn-primary btn-lg mt-4">{t('blocks.startQuiz')}</Link>
          ) : <p className="mt-2 text-xs text-faint">{t('blocks.quizNotLinked')}</p>}
        </section>
      )
    }
    case 'assignment':
      return <section className="card p-4"><h3 dir="auto" className="text-sm font-semibold">{d.title || t('blocks.assignment')}</h3><Markdown>{d.instructions ?? ''}</Markdown><p className="mt-1 text-xs text-muted">{t('blocks.points', { n: d.points ?? 0 })}</p><p className="mt-2 text-xs text-faint">{t('blocks.assignmentLater')}</p></section>
    default:
      return null
  }
}

const Unavailable = ({ what }: { what: string }) => <p className="text-sm text-muted">{t('blocks.questionGone')}</p>

function QuestionPreview({ q }: { q: { title: string; content: string; options: { id: string; text: string }[] } }) {
  return (
    <section className="card p-4">
      {q.title && <h3 dir="auto" className="mb-1 text-sm font-semibold">{q.title}</h3>}
      <Markdown>{q.content}</Markdown>
      {q.options.length > 0 && <ul className="mt-2 space-y-1">{q.options.map((o) => <li key={o.id} className="rounded border border-line px-3 py-1.5 text-sm">{o.text}</li>)}</ul>}
      <p className="mt-2 text-xs text-faint">{t('blocks.questionNote')}</p>
    </section>
  )
}

function ResourceCard({ d, kind, mapUrl }: { d: Record<string, any>; kind: string; mapUrl: (s: string) => string }) {
  const [busy, setBusy] = useState(false)
  async function open() {
    if (d.url && !d.attachment_id) return window.open(d.url, '_blank', 'noopener,noreferrer')
    setBusy(true)
    try {
      const r = await raw(mapUrl(`/api/attachments/${d.attachment_id}/file`).replace(/^\/api/, ''))
      if (!r.ok) throw new Error()
      const url = URL.createObjectURL(await r.blob())
      const a = document.createElement('a')
      a.href = url
      a.download = d.title || 'download'
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } finally {
      setBusy(false)
    }
  }
  return (
    <button onClick={open} disabled={busy} className="card flex w-full items-center gap-3 p-3 text-start hover:border-faint">
      <FileText size={18} className="shrink-0 text-faint" />
      <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{d.title || (kind === 'pdf' ? t('blocks.pdf') : t('blocks.download'))}</span>{d.description && <span className="block text-xs text-muted">{d.description}</span>}</span>
      <Download size={15} className="text-muted" />
    </button>
  )
}

export function VideoPlayer({ data }: { data: Record<string, any> }) {
  const r = data.resolved
  return (
    <figure>
      {data.title && <h3 dir="auto" className="mb-1 text-sm font-semibold">{data.title}</h3>}
      <div className="aspect-video w-full overflow-hidden rounded-lg border border-line bg-black">
        {r?.kind === 'embed' && r.embed_url ? (
          <iframe src={r.embed_url} title={data.title || 'Video'} className="h-full w-full" loading="lazy" referrerPolicy="strict-origin-when-cross-origin"
            sandbox="allow-scripts allow-same-origin allow-presentation allow-popups" allow="accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen" allowFullScreen />
        ) : r?.kind === 'upload' && data.playback_url ? (
          <video src={data.playback_url} controls preload="metadata" controlsList="nodownload" className="h-full w-full" poster={data.thumbnail_url || undefined} />
        ) : r?.kind === 'file' ? (
          <video src={r.url} controls preload="metadata" className="h-full w-full" poster={data.thumbnail_url || undefined} />
        ) : <div className="flex h-full items-center justify-center text-sm text-white/70">{t('blocks.videoUnavailable')}</div>}
      </div>
      {data.description && <figcaption dir="auto" className="mt-1.5 text-sm text-muted">{data.description}</figcaption>}
    </figure>
  )
}
