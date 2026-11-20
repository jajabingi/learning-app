import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { get, patch, post } from '@/api/client'
import type { TeamUser } from '@/api/types'
import { Page } from '@/components/Layout'
import { Badge, Button, ErrorState, Field, Loading, Modal, PageHeader } from '@/components/ui'
import { useAuth } from '@/contexts/auth'
import { useToast } from '@/contexts/toast'

export default function Team() {
  const { user: me } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [adding, setAdding] = useState(false)
  const users = useQuery({ queryKey: ['admin-users'], queryFn: () => get<TeamUser[]>('/admin/users') })
  const perms = useQuery({ queryKey: ['admin-perms'], queryFn: () => get<{ all: string[] }>('/admin/permissions') })
  const upd = useMutation({ mutationFn: (v: { id: string; body: Record<string, unknown> }) => patch(`/admin/users/${v.id}`, v.body), onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }), onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed') })
  if (users.isLoading || perms.isLoading) return <Loading />
  if (users.error || !users.data) return <ErrorState error={users.error} retry={users.refetch} />
  const staff = users.data.filter((u) => u.role !== 'student')
  const students = users.data.length - staff.length
  return (
    <Page>
      <PageHeader title="Team & permissions" subtitle={`${staff.length} staff accounts · ${students} students. Only administrators can see this page.`} actions={<button className="btn btn-primary" onClick={() => setAdding(true)}>Add teacher / admin</button>} />
      <div className="space-y-3">
        {staff.map((u) => (
          <section key={u.id} className="card p-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="min-w-0 flex-1"><div className="truncate font-medium">{u.display_name} {u.id === me?.id && <span className="text-xs text-muted">(you)</span>}</div><div className="truncate text-sm text-muted">{u.email}</div></div>
              <Badge tone={u.role === 'admin' ? 'accent' : 'neutral'} className="capitalize">{u.role}</Badge>{!u.is_active && <Badge tone="bad">deactivated</Badge>}
              <select className="field h-8 w-auto py-0" value={u.role} disabled={u.id === me?.id} aria-label={`Role of ${u.email}`} onChange={(e) => upd.mutate({ id: u.id, body: { role: e.target.value } })}><option value="teacher">Teacher</option><option value="admin">Admin</option><option value="student">Student (remove access)</option></select>
              <button className="btn" disabled={u.id === me?.id} onClick={() => upd.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? 'Deactivate' : 'Reactivate'}</button>
            </div>
            {u.role === 'teacher' ? (
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">{perms.data?.all.map((p) => <label key={p} className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={u.permissions.includes(p)} onChange={(e) => upd.mutate({ id: u.id, body: { permissions: e.target.checked ? [...u.permissions, p] : u.permissions.filter((x) => x !== p) } })} /> <span className="font-mono text-xs">{p}</span></label>)}</div>
            ) : <p className="mt-2 text-xs text-muted">Administrators have every permission.</p>}
          </section>
        ))}
      </div>
      <h2 className="h-section mb-2 mt-8">Student accounts ({students})</h2>
      {students === 0 ? <p className="text-sm text-muted">No students have registered yet.</p> : (
        <div className="card overflow-x-auto"><table className="w-full min-w-[520px] text-sm"><thead><tr className="border-b border-line text-left text-xs text-muted"><th className="px-4 py-2 font-medium">Student</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 text-right font-medium">Action</th></tr></thead>
          <tbody>{users.data.filter((u) => u.role === 'student').map((u) => (
            <tr key={u.id} className="border-b border-line last:border-0"><td className="px-4 py-2"><div className="font-medium">{u.display_name}</div><div className="text-xs text-muted">{u.email}</div></td><td className="px-4 py-2">{u.is_active ? <Badge tone="good">active</Badge> : <Badge tone="bad">deactivated</Badge>}</td><td className="px-4 py-2 text-right"><button className="btn h-7" onClick={() => upd.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? 'Deactivate' : 'Reactivate'}</button></td></tr>
          ))}</tbody></table></div>
      )}
      <p className="mt-3 text-xs text-muted">Public sign-up only creates student accounts. Teacher and admin accounts exist only when an administrator creates them here.</p>
      <AddStaff open={adding} onClose={() => setAdding(false)} />
    </Page>
  )
}

function AddStaff({ open, onClose }: { open: boolean; onClose(): void }) {
  const [f, setF] = useState({ email: '', password: '', display_name: '', role: 'teacher' })
  const qc = useQueryClient()
  const toast = useToast()
  const m = useMutation({ mutationFn: () => post('/admin/users', f), onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); toast.ok('Account created'); setF({ email: '', password: '', display_name: '', role: 'teacher' }); onClose() }, onError: (e) => toast.err(e instanceof Error ? e.message : 'Failed') })
  return (
    <Modal open={open} onClose={onClose} title="Add teacher / admin">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate() }}>
        <Field label="Name"><input className="field" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></Field>
        <Field label="Email"><input type="email" required className="field" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Temporary password" hint="At least 8 characters. Share it securely; they can change it in Settings."><input type="password" required minLength={8} className="field" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" /></Field>
        <Field label="Role"><select className="field" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="teacher">Teacher</option><option value="admin">Admin</option></select></Field>
        <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onClose}>Cancel</button><Button type="submit" className="btn-primary" loading={m.isPending}>Create</Button></div>
      </form>
    </Modal>
  )
}
