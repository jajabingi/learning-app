import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Pencil, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '@/api/client'
import { Page } from '@/components/Layout'
import { Badge, Button, ConfirmDialog, Empty, ErrorState, Field, Loading, Modal, PageHeader } from '@/components/ui'
import { useToast } from '@/contexts/toast'

interface Inst { id: string; slug: string; name: string; description: string; is_published: boolean; course_count: number }

export default function Institutions() {
  const qc = useQueryClient()
  const toast = useToast()
  const [edit, setEdit] = useState<Inst | 'new' | null>(null)
  const [rm, setRm] = useState<Inst | null>(null)
  const q = useQuery({ queryKey: ['teach-institutions'], queryFn: () => get<Inst[]>('/teach/institutions') })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['teach-institutions'] }); qc.invalidateQueries({ queryKey: ['teach-courses'] }) }
  const err = (e: unknown) => toast.err(e instanceof Error ? e.message : 'Failed')
  const toggle = useMutation({ mutationFn: (i: Inst) => patch(`/teach/institutions/${i.id}`, { is_published: !i.is_published }), onSuccess: refresh, onError: err })
  const remove = useMutation({ mutationFn: (i: Inst) => del(`/teach/institutions/${i.id}`), onSuccess: () => { refresh(); setRm(null) }, onError: err })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  return (
    <Page>
      <PageHeader title="Institutions" subtitle="Universities, schools or brands shown on the public landing page. Students pick one, then a course. Assign a course to an institution in the course’s Details tab." actions={<button className="btn btn-primary" onClick={() => setEdit('new')}>New institution</button>} />
      {q.data.length === 0 ? <div className="card"><Empty title="No institutions yet" icon={<Building2 size={28} />} action={<button className="btn btn-primary" onClick={() => setEdit('new')}>Create institution</button>}>Create one for each university or brand, publish it, then assign courses to it.</Empty></div> : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {q.data.map((i) => (
            <section key={i.id} className="card p-4">
              <div className="flex items-start justify-between gap-2"><h3 dir="auto" className="font-medium">{i.name}</h3><Badge tone={i.is_published ? 'good' : 'warn'}>{i.is_published ? 'Published' : 'Hidden'}</Badge></div>
              <p dir="auto" className="mt-1 line-clamp-2 min-h-10 text-sm text-muted">{i.description || 'No description'}</p>
              <div className="mt-3 flex items-center gap-2 text-sm text-muted"><span>{i.course_count} courses</span>
                <div className="ms-auto flex gap-1"><button className="btn h-7" onClick={() => toggle.mutate(i)}>{i.is_published ? 'Hide' : 'Publish'}</button><button className="btn btn-ghost btn-icon h-7 w-7" aria-label="Edit" onClick={() => setEdit(i)}><Pencil size={13} /></button><button className="btn btn-ghost btn-icon h-7 w-7 text-bad" aria-label="Delete" onClick={() => setRm(i)}><Trash2 size={13} /></button></div></div>
            </section>
          ))}
        </div>
      )}
      {edit && <InstForm initial={edit === 'new' ? undefined : edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); refresh() }} />}
      <ConfirmDialog open={!!rm} onClose={() => setRm(null)} busy={remove.isPending} onConfirm={() => rm && remove.mutate(rm)} title={`Delete “${rm?.name}”?`} message="Its courses are kept; they just no longer belong to an institution." />
    </Page>
  )
}

function InstForm({ initial, onClose, onDone }: { initial?: Inst; onClose(): void; onDone(): void }) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [pub, setPub] = useState(initial?.is_published ?? false)
  const toast = useToast()
  const m = useMutation({ mutationFn: () => (initial ? patch(`/teach/institutions/${initial.id}`, { name, description, is_published: pub }) : post('/teach/institutions', { name, description, is_published: pub })), onSuccess: onDone, onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed') })
  return (
    <Modal open onClose={onClose} title={initial ? 'Edit institution' : 'New institution'}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (name.trim()) m.mutate() }}>
        <Field label="Name"><input className="field" dir="auto" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required autoFocus /></Field>
        <Field label="Description (shown on the landing page)"><textarea className="field" dir="auto" rows={4} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={5000} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={pub} onChange={(e) => setPub(e.target.checked)} /> Published (visible on the public landing page)</label>
        <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onClose}>Cancel</button><Button type="submit" className="btn-primary" loading={m.isPending}>Save</Button></div>
      </form>
    </Modal>
  )
}
