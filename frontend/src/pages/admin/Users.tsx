import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { get, patch, post } from '@/api/client'
import { Page } from '@/components/Layout'
import { Badge, Button, ConfirmDialog, Empty, ErrorState, Field, Loading, Modal, PageHeader, Stat } from '@/components/ui'
import { useAuth } from '@/contexts/auth'
import { useToast } from '@/contexts/toast'
import { shortDate } from '@/lib/format'
import { tt, tl } from '@/i18n'

interface Row { id: string; email: string; display_name: string; role: 'student' | 'teacher' | 'admin'; status: string; created_at: string; providers: string[]; enrolled_courses: number; email_verified: boolean }
interface Audit { id: string; action: string; actor: string | null; target: string | null; target_id: string | null; details: Record<string, unknown>; created_at: string }
interface Detail extends Row { permissions: string[]; enrollments: { course_id: string; course_title: string; status: string; source: string }[]; owned_courses: number; last_learning_activity: string | null; activity: Audit[] }
const ROLE_TONE: Record<string, 'accent' | 'good' | 'neutral'> = { admin: 'accent', teacher: 'good', student: 'neutral' }
const STATUS_TONE: Record<string, 'good' | 'bad' | 'warn'> = { active: 'good', suspended: 'bad', pending_verification: 'warn' }
const ACTIONS: Record<string, string> = {
  role_changed: 'Role changed', user_suspended: 'User suspended', user_reactivated: 'User reactivated', user_created: 'User created', profile_edited: 'Profile edited',
  permissions_changed: 'Permissions changed', user_registered: 'User registered', login_google: 'Google sign-in', identity_linked: 'Google connected', identity_unlinked: 'Google disconnected',
  identity_link_requested: 'Google link requested', password_changed: 'Password changed', password_reset_requested: 'Password reset requested', password_reset_completed: 'Password reset completed', email_verified: 'Email verified',
}
const actionLabel = (a: string) => tt(ACTIONS[a] ?? a)
const detail = (d: Record<string, unknown>) => Object.entries(d).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`).join(' · ')

function AuditList({ items }: { items: Audit[] }) {
  if (!items.length) return <p className="text-sm text-muted">{tt("No activity yet.")}</p>
  return <ul className="card divide-y divide-line">{items.map((a) => (
    <li key={a.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-2 text-sm"><span className="font-medium">{actionLabel(a.action)}</span>
      <span className="text-xs text-muted" dir="ltr">{a.actor ?? '—'}{a.target && a.target !== a.actor ? ` → ${a.target}` : ''}</span>
      {Object.keys(a.details).length > 0 && <span className="text-xs text-muted" dir="ltr">{detail(a.details)}</span>}
      <span className="ms-auto text-xs text-muted tabnum">{new Date(a.created_at).toLocaleString('he-IL')}</span></li>))}</ul>
}

export function AdminDashboard() {
  const q = useQuery({ queryKey: ['admin-summary'], queryFn: () => get<{ by_role: Record<string, number>; by_status: Record<string, number>; total: number; recent: Audit[] }>('/admin/users/summary') })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const s = q.data
  return (
    <Page>
      <PageHeader title={tt("Admin dashboard")} subtitle={tt("Users, roles and recent administrative activity.")} actions={<Link to="/admin/users" className="btn btn-primary">{tt("Manage users")}</Link>} />
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label={tt("All users")} value={s.total} /><Stat label={tt("Students")} value={s.by_role.student ?? 0} /><Stat label={tt("Teachers")} value={s.by_role.teacher ?? 0} />
        <Stat label={tt("Administrators")} value={s.by_role.admin ?? 0} /><Stat label={tt("Suspended")} value={s.by_status.suspended ?? 0} tone={s.by_status.suspended ? 'warn' : undefined} />
      </div>
      <h2 className="h-section mb-2">{tt("Recent activity")}</h2>
      <AuditList items={s.recent} />
    </Page>
  )
}

function NewUser({ onClose }: { onClose(): void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState({ email: '', display_name: '', role: 'student', password: '' })
  const m = useMutation({ mutationFn: () => post('/admin/users', f), onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-directory'] }); qc.invalidateQueries({ queryKey: ['admin-summary'] }); toast.ok(tt("Account created")); onClose() }, onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")) })
  return (
    <Modal open onClose={onClose} title={tt("New user")}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate() }}>
        <Field label={tt("Name")}><input className="field" dir="auto" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} maxLength={100} /></Field>
        <Field label={tt("Email")}><input type="email" required dir="ltr" className="field" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label={tt("Role")}><select className="field" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="student">{tt("Student")}</option><option value="teacher">{tt("Teacher")}</option><option value="admin">{tt("Admin")}</option></select></Field>
        <Field label={tt("Temporary password")} hint={tt("At least 8 characters. Share it securely; they can change it in Settings.")}><input type="password" required minLength={8} dir="ltr" className="field" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" /></Field>
        <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onClose}>{tt("Cancel")}</button><Button type="submit" className="btn-primary" loading={m.isPending}>{tt("Create")}</Button></div>
      </form>
    </Modal>
  )
}

export function AdminUsers() {
  const [creating, setCreating] = useState(false)
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [sort, setSort] = useState('created')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const res = useQuery({ queryKey: ['admin-directory', q, role, status, sort, order, page], placeholderData: (p) => p,
    queryFn: () => get<{ items: Row[]; total: number; page: number; page_size: number }>('/admin/users/directory', { q, role, status, sort, order, page, page_size: 20 }) })
  const pages = res.data ? Math.max(1, Math.ceil(res.data.total / res.data.page_size)) : 1
  const set = (fn: () => void) => { fn(); setPage(1) }
  const th = (key: string, label: string) => <th className="px-3 py-2 text-start font-medium"><button className="hover:text-fg" onClick={() => { if (sort === key) setOrder(order === 'asc' ? 'desc' : 'asc'); else { setSort(key); setOrder('asc') } }}>{label}{sort === key ? (order === 'asc' ? ' ▲' : ' ▼') : ''}</button></th>
  return (
    <Page>
      <PageHeader title={tt("Users")} subtitle={tt("Search, filter and manage every account. Only administrators can see this page.")} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative"><Search size={14} className="pointer-events-none absolute start-3 top-3 text-faint" /><input className="field w-64 ps-9" placeholder={tt("Search name or email…")} aria-label={tt("Search users")} value={q} onChange={(e) => set(() => setQ(e.target.value))} /></div>
        <select className="field w-auto" value={role} aria-label={tt("Filter by role")} onChange={(e) => set(() => setRole(e.target.value))}><option value="">{tt("All users")}</option><option value="student">{tt("Students")}</option><option value="teacher">{tt("Teachers")}</option><option value="admin">{tt("Administrators")}</option></select>
        <select className="field w-auto" value={status} aria-label={tt("Filter by status")} onChange={(e) => set(() => setStatus(e.target.value))}><option value="">{tt("All statuses")}</option><option value="active">{tt("Active")}</option><option value="suspended">{tt("Suspended")}</option><option value="pending_verification">{tt("Pending verification")}</option></select>
        <button className="btn btn-primary ms-auto" onClick={() => setCreating(true)}>{tt("New user")}</button><Link to="/admin/audit" className="btn">{tt("Audit log")}</Link>
      </div>
      {res.isLoading ? <Loading /> : res.error || !res.data ? <ErrorState error={res.error} retry={res.refetch} /> : res.data.items.length === 0 ? <div className="card"><Empty title={tt("No users match")} /></div> : (
        <div className="card overflow-x-auto"><table className="w-full min-w-[820px] text-sm"><thead><tr className="border-b border-line text-xs text-muted">
          {th('name', tt("Name"))}{th('email', tt("Email"))}{th('role', tt("Role"))}{th('status', tt("Status"))}<th className="px-3 py-2 text-start font-medium">{tt("Sign-in")}</th><th className="px-3 py-2 text-start font-medium">{tt("Courses")}</th>{th('created', tt("Registered"))}<th /></tr></thead>
          <tbody>{res.data.items.map((u) => (
            <tr key={u.id} className="border-b border-line last:border-0 hover:bg-raised/50">
              <td className="px-3 py-2 font-medium"><Link to={`/admin/users/${u.id}`} className="hover:underline" dir="auto">{u.display_name || '—'}</Link></td><td className="px-3 py-2 text-muted" dir="ltr">{u.email}</td>
              <td className="px-3 py-2"><Badge tone={ROLE_TONE[u.role]}>{tl(u.role)}</Badge></td><td className="px-3 py-2"><Badge tone={STATUS_TONE[u.status]}>{tl(u.status)}</Badge></td>
              <td className="px-3 py-2 text-xs text-muted">{u.providers.map((p) => tl(p)).join(' · ')}</td><td className="px-3 py-2 tabnum">{u.enrolled_courses}</td>
              <td className="px-3 py-2 text-xs text-muted">{shortDate(u.created_at.slice(0, 10))}</td><td className="px-3 py-2 text-end"><Link to={`/admin/users/${u.id}`} className="btn h-7">{tt("Edit")}</Link></td></tr>))}</tbody></table></div>
      )}
      {res.data && <div className="mt-3 flex items-center justify-between text-sm text-muted tabnum"><span>{res.data.total} {tt("users")}</span>
        <div className="flex items-center gap-2"><button className="btn h-8" disabled={page <= 1} onClick={() => setPage(page - 1)}>{tt("Previous page")}</button><span>{tt("Page")} {page} {tt("of")} {pages}</span><button className="btn h-8" disabled={page >= pages} onClick={() => setPage(page + 1)}>{tt("Next page")}</button></div></div>}
      {creating && <NewUser onClose={() => setCreating(false)} />}
    </Page>
  )
}

export function AdminUserDetail() {
  const { id = '' } = useParams()
  const { user: me } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['admin-user', id], queryFn: () => get<Detail>(`/admin/users/${id}`) })
  const [name, setName] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<null | { title: string; message: string; label: string; body: Record<string, unknown>; danger?: boolean }>(null)
  const save = useMutation({ mutationFn: (body: Record<string, unknown>) => patch(`/admin/users/${id}`, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-user', id] }); qc.invalidateQueries({ queryKey: ['admin-directory'] }); qc.invalidateQueries({ queryKey: ['admin-summary'] }); setConfirm(null); setName(null); toast.ok(tt("Saved")) },
    onError: (e) => { setConfirm(null); toast.err(e instanceof Error ? e.message : tt("Failed")) } })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <Page><Empty title={tt("User not found")} action={<Link className="btn" to="/admin/users">{tt("Back to users")}</Link>} /></Page>
  const u = q.data
  const self = me?.id === u.id
  const roleChange = (role: 'student' | 'teacher' | 'admin') => setConfirm({ title: tt("Change role to {role}?", { role: tl(role) }), message: tt("{email} will become {role}. Their current sessions end and they must sign in again.", { email: u.email, role: tl(role) }), label: tt("Change role"), body: { role }, danger: role === 'admin' || u.role === 'admin' })
  return (
    <Page>
      <Link to="/admin/users" className="mb-1 inline-block text-xs text-muted hover:text-fg">{tt("← Users")}</Link>
      <PageHeader title={<span className="flex items-center gap-2"><span dir="auto">{u.display_name || u.email}</span><Badge tone={ROLE_TONE[u.role]}>{tl(u.role)}</Badge><Badge tone={STATUS_TONE[u.status]}>{tl(u.status)}</Badge></span>} subtitle={<span dir="ltr">{u.email}</span>} />
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card space-y-3 p-4"><h2 className="h-section">{tt("Profile")}</h2>
          <Field label={tt("Name")}><div className="flex gap-2"><input className="field" dir="auto" value={name ?? u.display_name} onChange={(e) => setName(e.target.value)} maxLength={100} /><button className="btn" disabled={name === null || !name.trim()} onClick={() => save.mutate({ display_name: name })}>{tt("Save")}</button></div></Field>
          <dl className="space-y-1 text-sm"><div className="flex justify-between"><dt className="text-muted">{tt("Registered")}</dt><dd>{shortDate(u.created_at.slice(0, 10))}</dd></div>
            <div className="flex justify-between"><dt className="text-muted">{tt("Sign-in")}</dt><dd>{u.providers.map((p) => tl(p)).join(' · ')}</dd></div>
            <div className="flex justify-between"><dt className="text-muted">{tt("Email verified")}</dt><dd>{u.email_verified ? tt("Yes") : tt("No")}</dd></div>
            <div className="flex justify-between"><dt className="text-muted">{tt("Last learning activity")}</dt><dd>{u.last_learning_activity ? new Date(u.last_learning_activity).toLocaleDateString('he-IL') : '—'}</dd></div>
            {u.role === 'teacher' && <div className="flex justify-between"><dt className="text-muted">{tt("Courses owned")}</dt><dd>{u.owned_courses}</dd></div>}</dl>
        </section>
        <section className="card space-y-3 p-4"><h2 className="h-section">{tt("Role and access")}</h2>
          <Field label={tt("Role")}><select className="field" value={u.role} disabled={self} onChange={(e) => roleChange(e.target.value as 'student' | 'teacher' | 'admin')}><option value="student">{tt("Student")}</option><option value="teacher">{tt("Teacher")}</option><option value="admin">{tt("Admin")}</option></select></Field>
          {self && <p className="text-xs text-muted">{tt("You cannot change your own role or status.")}</p>}
          <div className="flex flex-wrap gap-2">{u.role === 'student' && <button className="btn btn-primary" onClick={() => roleChange('teacher')}>{tt("Promote to teacher")}</button>}
            <button className="btn" disabled={u.status === 'suspended'} onClick={() => post(`/admin/users/${u.id}/send-reset`).then(() => toast.ok(tt("Reset email sent"))).catch((e) => toast.err(e instanceof Error ? e.message : tt("Failed")))}>{tt("Send password reset email")}</button>
            {u.status === 'active' ? <button className="btn btn-danger" disabled={self} onClick={() => setConfirm({ title: tt("Suspend this account?"), message: tt("{email} will be signed out everywhere and will not be able to sign in. Their data is kept.", { email: u.email }), label: tt("Suspend"), body: { status: 'suspended' }, danger: true })}>{tt("Suspend")}</button>
              : <button className="btn btn-primary" onClick={() => setConfirm({ title: tt("Reactivate this account?"), message: tt("{email} will be able to sign in again.", { email: u.email }), label: tt("Reactivate"), body: { status: 'active' }, danger: false })}>{tt("Reactivate")}</button>}</div>
        </section>
      </div>
      <h2 className="h-section mb-2 mt-6">{tt("Course enrollments")}</h2>
      {u.enrollments.length === 0 ? <p className="text-sm text-muted">{tt("No enrollments.")}</p> : <ul className="card divide-y divide-line">{u.enrollments.map((e) => <li key={e.course_id} className="flex items-center gap-3 px-4 py-2 text-sm"><span dir="auto" className="flex-1">{e.course_title}</span><Badge>{tl(e.status)}</Badge><span className="text-xs text-muted">{tl(e.source)}</span></li>)}</ul>}
      <h2 className="h-section mb-2 mt-6">{tt("Activity history")}</h2>
      <AuditList items={u.activity} />
      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} busy={save.isPending} title={confirm?.title ?? ''} message={confirm?.message ?? ''} confirmLabel={confirm?.label} danger={confirm?.danger} onConfirm={() => confirm && save.mutate(confirm.body)} />
    </Page>
  )
}

export function AdminAudit() {
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const q = useQuery({ queryKey: ['admin-audit', page, action], placeholderData: (p) => p, queryFn: () => get<{ items: Audit[]; total: number; page_size: number }>('/admin/audit', { page, action, page_size: 30 }) })
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1
  return (
    <Page>
      <Link to="/admin/users" className="mb-1 inline-block text-xs text-muted hover:text-fg">{tt("← Users")}</Link>
      <PageHeader title={tt("Audit log")} subtitle={tt("Sensitive actions: role changes, suspensions, account linking and sign-in events. Secrets are never recorded.")} actions={<select className="field w-auto" value={action} aria-label={tt("Filter by action")} onChange={(e) => { setAction(e.target.value); setPage(1) }}><option value="">{tt("All actions")}</option>{Object.keys(ACTIONS).map((a) => <option key={a} value={a}>{actionLabel(a)}</option>)}</select>} />
      {q.isLoading ? <Loading /> : q.data ? <><AuditList items={q.data.items} /><div className="mt-3 flex items-center justify-end gap-2 text-sm text-muted tabnum"><button className="btn h-8" disabled={page <= 1} onClick={() => setPage(page - 1)}>{tt("Previous page")}</button><span>{tt("Page")} {page} {tt("of")} {pages}</span><button className="btn h-8" disabled={page >= pages} onClick={() => setPage(page + 1)}>{tt("Next page")}</button></div></> : <ErrorState error={q.error} retry={q.refetch} />}
    </Page>
  )
}
