import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Eye, EyeOff, Pencil, Plus, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '@/api/client'
import type { Block, BlockType, LessonDetail } from '@/api/types'
import { BlockView } from '@/components/lms/BlockView'
import { BLOCK_META, BLOCK_ORDER, BlockForm, DEFAULTS } from '@/components/lms/BlockEditor'
import { SortableList } from '@/components/lms/SortableList'
import { AiSummaryButton } from '@/components/lms/AiAssist'
import { MarkdownEditor } from '@/components/MarkdownEditor'
import { Page } from '@/components/Layout'
import { Badge, Button, ConfirmDialog, ErrorState, Loading, Modal, Segmented } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { tt } from '@/i18n'


export default function LessonEditor() {
  const { id: courseId = '', lid = '' } = useParams()
  const qc = useQueryClient()
  const toast = useToast()
  const [mode, setMode] = useState<'edit' | 'preview'>('edit')
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState<Record<string, any>>({})
  const [rm, setRm] = useState<Block | null>(null)
  const [creating, setCreating] = useState<{ type: BlockType; data: Record<string, any> } | null>(null)
  const key = ['teach-lesson', lid]
  const q = useQuery({ queryKey: key, queryFn: () => get<LessonDetail>(`/teach/lessons/${lid}`) })
  const preview = useQuery({ queryKey: ['teach-lesson-preview', lid, q.dataUpdatedAt], queryFn: () => get<LessonDetail>(`/teach/lessons/${lid}/preview`), enabled: mode === 'preview' })
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  useEffect(() => { if (q.data) { setTitle(q.data.title); setSummary(q.data.summary) } }, [q.data?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => { qc.invalidateQueries({ queryKey: key }); qc.invalidateQueries({ queryKey: ['teach-course', courseId] }) }
  const run = useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: refresh, onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")) })
  const savePatch = (body: Record<string, unknown>, ok?: string) => run.mutateAsync(() => patch(`/teach/lessons/${lid}`, body)).then(() => ok && toast.ok(ok)).catch(() => {})

  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const l = q.data

  async function saveBlock(b: Block) {
    try {
      await patch(`/teach/blocks/${b.id}`, { data: draft })
      setEditing(null)
      refresh()
    } catch (e) { toast.err(e instanceof Error ? e.message : tt("Could not save block")) }
  }
  function addBlock(type: BlockType) {
    setCreating({ type, data: DEFAULTS[type] ?? {} })
    setAdding(false)
  }

  return (
    <Page narrow>
      <Link to={`/teach/courses/${courseId}`} className="mb-1 inline-block text-xs text-muted hover:text-fg">{tt("← Back to course")}</Link>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input className="min-w-0 flex-1 bg-transparent text-2xl font-semibold tracking-tight outline-none focus:underline" value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => title.trim() && title !== l.title && savePatch({ title })} aria-label={tt("Lesson title")} />
        <Badge tone={l.is_published ? 'good' : 'warn'}>{l.is_published ? tt("Published") : tt("Draft")}</Badge>
        <Segmented<'edit' | 'preview'> value={mode} onChange={setMode} label={tt("Mode")} options={[{ value: 'edit', label: tt("Edit") }, { value: 'preview', label: tt("Student preview") }]} />
      </div>
      <div className="mb-5 flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={!!l.is_published} onChange={(e) => savePatch({ is_published: e.target.checked }, e.target.checked ? 'Lesson published' : 'Lesson unpublished')} /> {tt("Published to students")}</label>
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={l.is_free_preview} onChange={(e) => savePatch({ is_free_preview: e.target.checked })} /> {tt("Free preview lesson")}</label>
        <label className="flex items-center gap-1.5">{tt("Minutes")} <input type="number" min={0} className="field h-7 w-20" value={l.estimated_minutes} onChange={(e) => savePatch({ estimated_minutes: Number(e.target.value) || 0 })} /></label>
      </div>

      {mode === 'preview' ? (
        preview.isLoading ? <Loading /> : (
          <div className="space-y-6 rounded-lg border border-dashed border-line p-4">
            <p className="text-xs text-muted">{tt("This is what students see (hidden blocks and answers are removed).")}</p>
            {preview.data?.blocks.map((b) => <BlockView key={b.id} block={b} />)}
            {preview.data?.blocks.length === 0 && <p className="text-sm text-muted">{tt("No visible content yet.")}</p>}
          </div>
        )
      ) : (
        <>
          <SortableList items={l.blocks} className="space-y-3" onReorder={(ids) => run.mutate(() => post(`/teach/lessons/${lid}/blocks/reorder`, { ids }))}
            render={(b) => (
              <div className="card">
                <div className="flex items-center gap-2 border-b border-line px-3 py-1.5">
                  <Badge>{BLOCK_META[b.type]?.label ?? b.type}</Badge>{b.is_visible === false && <Badge tone="warn">{tt("hidden from students")}</Badge>}
                  <div className="ml-auto flex items-center">
                    <button className="btn btn-ghost btn-icon h-7 w-7" aria-label={tt("Edit block")} onClick={() => { setEditing(editing === b.id ? null : b.id); setDraft(b.data) }}><Pencil size={13} /></button>
                    <button className="btn btn-ghost btn-icon h-7 w-7" aria-label={b.is_visible === false ? tt("Show to students") : tt("Hide from students")} onClick={() => run.mutate(() => patch(`/teach/blocks/${b.id}`, { is_visible: b.is_visible === false }))}>{b.is_visible === false ? <EyeOff size={13} /> : <Eye size={13} />}</button>
                    <button className="btn btn-ghost btn-icon h-7 w-7" aria-label={tt("Duplicate block")} onClick={() => run.mutate(() => post(`/teach/blocks/${b.id}/duplicate`))}><Copy size={13} /></button>
                    <button className="btn btn-ghost btn-icon h-7 w-7 text-bad" aria-label={tt("Delete block")} onClick={() => setRm(b)}><Trash2 size={13} /></button>
                  </div>
                </div>
                <div className="p-4">
                  {editing === b.id ? (
                    <div className="space-y-3"><BlockForm type={b.type} data={draft} onChange={setDraft} lessonId={lid} /><div className="flex justify-end gap-2"><button className="btn" onClick={() => setEditing(null)}>{tt("Cancel")}</button><Button className="btn-primary" onClick={() => saveBlock(b)}>{tt("Save block")}</Button></div></div>
                  ) : <BlockView block={b} />}
                </div>
              </div>
            )} />
          {l.blocks.length === 0 && <p className="mb-3 text-sm text-muted">{tt("This lesson is empty. Add blocks in any order — video, text, formula, example, summary, questions…")}</p>}
          <button className="btn btn-primary mt-3" onClick={() => setAdding(true)}><Plus size={14} /> {tt("Add block")}</button>
          <div className="mt-8"><span className="label">{tt("Lesson summary (shown at the end of the lesson)")}</span><MarkdownEditor value={summary} onChange={setSummary} label={tt("Lesson summary")} minRows={4} />
            <div className="mt-2 flex flex-wrap gap-2"><AiSummaryButton lessonId={lid} current={summary} onDraft={setSummary} /><Button disabled={summary === l.summary} onClick={() => savePatch({ summary }, 'Summary saved')}>{tt("Save summary")}</Button></div></div>
        </>
      )}

      <Modal open={adding} onClose={() => setAdding(false)} title={tt("Add a content block")} wide>
        <div className="grid gap-2 sm:grid-cols-2">{BLOCK_ORDER.map((t) => <button key={t} className="card p-3 text-start hover:border-accent" onClick={() => addBlock(t)}><div className="text-sm font-medium">{BLOCK_META[t].label}</div><div className="text-xs text-muted">{BLOCK_META[t].desc}</div></button>)}</div>
      </Modal>
      {creating && <NewBlockDialog lid={lid} init={creating} onClose={() => setCreating(null)} onDone={() => { setCreating(null); refresh() }} />}
      <ConfirmDialog open={!!rm} onClose={() => setRm(null)} title={tt("Delete this block?")} message={tt("The block is permanently removed from the lesson.")} onConfirm={() => rm && run.mutateAsync(() => del(`/teach/blocks/${rm.id}`)).then(() => setRm(null))} />
    </Page>
  )
}

function NewBlockDialog({ lid, init, onClose, onDone }: { lid: string; init: { type: BlockType; data: Record<string, any> }; onClose(): void; onDone(): void }) {
  const [data, setData] = useState(init.data)
  const toast = useToast()
  const m = useMutation({ mutationFn: () => post(`/teach/lessons/${lid}/blocks`, { type: init.type, data }), onSuccess: onDone, onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")) })
  return (
    <Modal open onClose={onClose} wide title={tt("New block: {type}", { type: BLOCK_META[init.type].label })} footer={<><button className="btn" onClick={onClose}>{tt("Cancel")}</button><Button className="btn-primary" loading={m.isPending} onClick={() => m.mutate()}>{tt("Add block")}</Button></>}>
      <BlockForm type={init.type} data={data} onChange={setData} lessonId={lid} />
    </Modal>
  )
}
