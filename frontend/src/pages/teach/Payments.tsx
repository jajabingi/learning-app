import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Plus, Wallet } from 'lucide-react'
import { download, get, patch, post } from '@/api/client'
import { Page } from '@/components/Layout'
import { Badge, Button, Empty, ErrorState, Field, Loading, Modal, PageHeader, Stat } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { shortDate } from '@/lib/format'
import { tt, tl } from '@/i18n'

export interface Pay { id: string; kind: 'payment' | 'refund'; amount: number; method: string; status: string; provider: string; reference: string; note: string; received_at: string | null; created_at: string; receipt_no: string | null; void_reason: string }
export interface Inst { id: string; position: number; amount: number; due_date: string; paid: number; status: string; overdue: boolean }
export interface OrderRow { id: string; student_id: string; student_name: string; student_email: string; course_id: string; course_title: string; currency: string; list_price: number; amount_due: number; paid: number; balance: number; pending: number; status: string; overdue: number; note: string; created_at: string; payments?: Pay[]; installments?: Inst[] }
const money = (n: number, cur = 'ILS') => new Intl.NumberFormat('he-IL', { style: 'currency', currency: cur, maximumFractionDigits: 2 }).format(n)
const ST: Record<string, 'good' | 'warn' | 'bad' | 'neutral'> = { paid: 'good', open: 'warn', cancelled: 'neutral' }
const METHODS = ['cash', 'bank_transfer', 'check', 'card', 'bit_paybox', 'other']
const useErr = () => { const t = useToast(); return (e: unknown) => t.err(e instanceof Error ? e.message : tt("Failed")) }

export function Money({ v, cur }: { v: number; cur?: string }) { return <span dir="ltr" className="tabnum">{money(v, cur)}</span> }

// ------------------------------------------------------------------ course tab
export function CoursePayments({ courseId }: { courseId: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const q = useQuery({ queryKey: ['teach-orders', courseId], queryFn: () => get<OrderRow[]>(`/teach/courses/${courseId}/orders`) })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const refresh = () => { qc.invalidateQueries({ queryKey: ['teach-orders', courseId] }); qc.invalidateQueries({ queryKey: ['teach-finance'] }); qc.invalidateQueries({ queryKey: ['teach-students'] }) }
  const totals = q.data.filter((o) => o.status !== 'cancelled').reduce((a, o) => ({ due: a.due + o.amount_due, paid: a.paid + o.paid, bal: a.bal + Math.max(o.balance, 0) }), { due: 0, paid: 0, bal: 0 })
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3"><Stat label={tt("Billed")} value={<Money v={totals.due} />} /><Stat label={tt("Collected")} value={<Money v={totals.paid} />} tone="good" /><Stat label={tt("Outstanding")} value={<Money v={totals.bal} />} tone={totals.bal ? 'warn' : undefined} /></div>
      <div className="flex flex-wrap gap-2"><button className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={14} /> {tt("New order")}</button>
        <button className="btn" onClick={() => download(`/teach/finance/ledger.csv?course_id=${courseId}`, 'ledger.csv')}><Download size={14} /> {tt("Export ledger (CSV)")}</button></div>
      {q.data.length === 0 ? <div className="card"><Empty title={tt("No orders yet")} icon={<Wallet size={26} />}>{tt("An order is created when a student asks to join this paid course, or when you create one for a student.")}</Empty></div> : (
        <div className="card overflow-x-auto"><table className="w-full min-w-[720px] text-sm"><thead><tr className="border-b border-line text-xs text-muted">{[tt("Student"), tt("Amount due"), tt("Paid"), tt("Balance"), tt("Status"), ''].map((h, i) => <th key={i} className="px-3 py-2 text-start font-medium">{h}</th>)}</tr></thead>
          <tbody>{q.data.map((o) => (
            <tr key={o.id} className="border-b border-line last:border-0 hover:bg-raised/50">
              <td className="px-3 py-2"><div className="font-medium">{o.student_name}</div><div className="text-xs text-muted" dir="ltr">{o.student_email}</div></td>
              <td className="px-3 py-2"><Money v={o.amount_due} cur={o.currency} /></td><td className="px-3 py-2"><Money v={o.paid} cur={o.currency} /></td>
              <td className="px-3 py-2"><Money v={Math.max(o.balance, 0)} cur={o.currency} />{o.overdue > 0 && <Badge tone="bad" className="ms-2">{tt("Overdue")}</Badge>}{o.pending > 0 && <Badge tone="warn" className="ms-2">{tt("Online payment pending")}</Badge>}</td>
              <td className="px-3 py-2"><Badge tone={ST[o.status]}>{tl(o.status)}</Badge></td>
              <td className="px-3 py-2 text-end"><button className="btn h-7" onClick={() => setOpen(o.id)}>{tt("Manage")}</button></td></tr>))}</tbody></table></div>
      )}
      {open && <OrderModal id={open} onClose={() => setOpen(null)} onChanged={refresh} />}
      {creating && <NewOrder courseId={courseId} onClose={() => setCreating(false)} onCreated={(id) => { refresh(); setCreating(false); setOpen(id) }} />}
    </div>
  )
}

function NewOrder({ courseId, onClose, onCreated }: { courseId: string; onClose(): void; onCreated(id: string): void }) {
  const err = useErr()
  const [email, setEmail] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const m = useMutation({
    mutationFn: async () => { const s = await get<{ id: string }>('/teach/students/lookup', { email }); return post<OrderRow>('/teach/orders', { student_id: s.id, course_id: courseId, amount_due: amount === '' ? null : amount, note }) },
    onSuccess: (o) => onCreated(o.id), onError: err,
  })
  return (
    <Modal open onClose={onClose} title={tt("New order")}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate() }}>
        <Field label={tt("Student email")}><input type="email" required dir="ltr" className="field" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label={tt("Amount due (empty = course price)")}><input type="number" min={0} step="0.01" dir="ltr" className="field" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label={tt("Note (optional)")}><input className="field" dir="auto" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} /></Field>
        <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onClose}>{tt("Cancel")}</button><Button type="submit" className="btn-primary" loading={m.isPending}>{tt("Create")}</Button></div>
      </form>
    </Modal>
  )
}

// ------------------------------------------------------------------ one order
function OrderModal({ id, onClose, onChanged }: { id: string; onClose(): void; onChanged(): void }) {
  const qc = useQueryClient()
  const err = useErr()
  const toast = useToast()
  const q = useQuery({ queryKey: ['teach-order', id], queryFn: () => get<OrderRow>(`/teach/orders/${id}`) })
  const [f, setF] = useState({ amount: '', method: 'cash', reference: '', note: '' })
  const [refund, setRefund] = useState({ amount: '', reason: '' })
  const [plan, setPlan] = useState({ count: '3', first: new Date().toISOString().slice(0, 10) })
  const [due, setDue] = useState('')
  const sync = (o: OrderRow) => { qc.setQueryData(['teach-order', id], o); onChanged() }
  const run = <T,>(fn: () => Promise<T>, ok: string, after?: (r: T) => void) => fn().then((r) => { after?.(r); toast.ok(ok) }).catch(err)
  if (!q.data) return <Modal open onClose={onClose} title={tt("Order")}><Loading /></Modal>
  const o = q.data
  const live = o.status !== 'cancelled'
  return (
    <Modal open onClose={onClose} wide title={`${o.student_name} — ${o.course_title}`}>
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><Stat label={tt("Amount due")} value={<Money v={o.amount_due} cur={o.currency} />} /><Stat label={tt("Paid")} value={<Money v={o.paid} cur={o.currency} />} tone="good" /><Stat label={tt("Balance")} value={<Money v={Math.max(o.balance, 0)} cur={o.currency} />} tone={o.balance > 0 ? 'warn' : undefined} /><Stat label={tt("Status")} value={tl(o.status)} /></div>

        {live && o.balance > 0 && <form className="card space-y-3 p-4" onSubmit={(e) => { e.preventDefault(); run(() => post<{ order: OrderRow }>(`/teach/orders/${id}/payments`, { amount: f.amount, method: f.method, reference: f.reference, note: f.note }), tt("Payment recorded"), (r) => { sync(r.order); setF({ ...f, amount: '', reference: '', note: '' }) }) }}>
          <h3 className="h-section">{tt("Record a payment")}</h3>
          <div className="grid gap-3 sm:grid-cols-4"><Field label={tt("Amount")}><input type="number" required min={0.01} max={o.balance} step="0.01" dir="ltr" className="field" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
            <Field label={tt("Method")}><select className="field" value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>{METHODS.map((m) => <option key={m} value={m}>{tl(m)}</option>)}</select></Field>
            <Field label={tt("Reference")}><input className="field" dir="auto" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} maxLength={200} placeholder={tt("cheque / transfer no.")} /></Field>
            <div className="flex items-end"><Button type="submit" className="btn-primary w-full">{tt("Record")}</Button></div></div>
          <button type="button" className="text-xs text-accent underline" onClick={() => setF({ ...f, amount: String(o.balance) })}>{tt("Fill the full balance")}</button>
        </form>}

        <section><h3 className="h-section mb-2">{tt("Ledger")}</h3>
          {(o.payments ?? []).length === 0 ? <p className="text-sm text-muted">{tt("No payments yet.")}</p> : <div className="card overflow-x-auto"><table className="w-full min-w-[560px] text-sm"><tbody>{o.payments!.map((p) => (
            <tr key={p.id} className={`border-b border-line last:border-0 ${p.status === 'voided' ? 'text-faint line-through' : ''}`}>
              <td className="px-3 py-2 text-xs">{shortDate((p.received_at ?? p.created_at).slice(0, 10))}</td><td className="px-3 py-2 tabnum" dir="ltr">{p.receipt_no ?? '—'}</td>
              <td className="px-3 py-2">{p.kind === 'refund' ? tt("Refund") : tl(p.method)}</td><td className="px-3 py-2"><Money v={p.kind === 'refund' ? -p.amount : p.amount} cur={o.currency} /></td>
              <td className="px-3 py-2"><Badge tone={p.status === 'confirmed' ? 'good' : p.status === 'pending' ? 'warn' : 'neutral'}>{tl(p.status)}</Badge></td><td className="px-3 py-2 text-xs text-muted" dir="auto">{p.reference || p.note || p.void_reason}</td>
              <td className="px-3 py-2 text-end">{p.status === 'confirmed' && p.kind === 'payment' && <button className="btn h-7" onClick={() => { const reason = prompt(tt("Why is this payment voided?")); if (reason && reason.trim().length >= 3) run(() => post<OrderRow>(`/teach/payments/${p.id}/void`, { reason }), tt("Payment voided"), sync) }}>{tt("Void")}</button>}</td></tr>))}</tbody></table></div>}
        </section>

        {live && <section><h3 className="h-section mb-2">{tt("Installment plan")}</h3>
          {(o.installments ?? []).length > 0 && <ul className="card mb-2 divide-y divide-line">{o.installments!.map((i) => <li key={i.id} className="flex items-center gap-3 px-3 py-2 text-sm"><span dir="ltr" className="tabnum">{shortDate(i.due_date)}</span><Money v={i.amount} cur={o.currency} /><Badge tone={i.status === 'paid' ? 'good' : i.overdue ? 'bad' : 'neutral'}>{i.status === 'paid' ? tt("Paid") : i.overdue ? tt("Overdue") : tt("Upcoming")}</Badge></li>)}</ul>}
          <div className="flex flex-wrap items-end gap-2"><Field label={tt("Number of installments")}><input type="number" min={1} max={36} dir="ltr" className="field w-24" value={plan.count} onChange={(e) => setPlan({ ...plan, count: e.target.value })} /></Field>
            <Field label={tt("First due date")}><input type="date" dir="ltr" className="field" value={plan.first} onChange={(e) => setPlan({ ...plan, first: e.target.value })} /></Field>
            <button className="btn" onClick={() => run(() => post<OrderRow>(`/teach/orders/${id}/installments`, { count: Number(plan.count), first_due: plan.first }), tt("Plan saved"), sync)}>{tt("Split evenly")}</button>
            {(o.installments ?? []).length > 0 && <button className="btn" onClick={() => run(() => post<OrderRow>(`/teach/orders/${id}/installments`, { clear: true }), tt("Plan removed"), sync)}>{tt("Remove plan")}</button>}</div></section>}

        {live && <section className="grid gap-4 sm:grid-cols-2">
          <form className="card space-y-2 p-4" onSubmit={(e) => { e.preventDefault(); if (due !== '') run(() => patch<OrderRow>(`/teach/orders/${id}`, { amount_due: due, reason: 'adjusted by teacher' }), tt("Order updated"), (r) => { sync(r); setDue('') }) }}>
            <h3 className="h-section">{tt("Adjust the amount due")}</h3><input type="number" min={0} step="0.01" dir="ltr" className="field" placeholder={String(o.amount_due)} value={due} onChange={(e) => setDue(e.target.value)} /><Button type="submit" disabled={due === ''}>{tt("Update")}</Button></form>
          {o.paid > 0 ? <form className="card space-y-2 p-4" onSubmit={(e) => { e.preventDefault(); run(() => post<OrderRow>(`/teach/orders/${id}/refunds`, { amount: refund.amount, reason: refund.reason, revoke_access: true }), tt("Refund recorded"), (r) => { sync(r); setRefund({ amount: '', reason: '' }) }) }}>
            <h3 className="h-section">{tt("Refund")}</h3><input type="number" required min={0.01} max={o.paid} step="0.01" dir="ltr" className="field" placeholder={tt("Amount")} value={refund.amount} onChange={(e) => setRefund({ ...refund, amount: e.target.value })} />
            <input required minLength={3} className="field" dir="auto" placeholder={tt("Reason")} value={refund.reason} onChange={(e) => setRefund({ ...refund, reason: e.target.value })} /><p className="text-xs text-muted">{tt("Refunding everything also removes access that this payment granted.")}</p><Button type="submit" className="btn-danger">{tt("Refund")}</Button></form>
            : <button className="btn btn-danger self-start" onClick={() => confirm(tt("Cancel this order?")) && run(() => patch<OrderRow>(`/teach/orders/${id}`, { status: 'cancelled' }), tt("Order cancelled"), sync)}>{tt("Cancel order")}</button>}
        </section>}
      </div>
    </Modal>
  )
}

// ------------------------------------------------------------------ finance dashboard
interface Summary { currency: string; orders: number; billed: number; collected: number; outstanding: number; overdue: number; pending_online: number; refunded: number; by_method: Record<string, number>; by_month: { month: string; amount: number }[]; by_course: { course_id: string; course_title: string; orders: number; billed: number; collected: number; outstanding: number }[]; overdue_orders: OrderRow[] }

export function Finance() {
  const q = useQuery({ queryKey: ['teach-finance'], queryFn: () => get<Summary>('/teach/finance/summary') })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const s = q.data
  const cur = s.currency === 'mixed' ? 'ILS' : s.currency
  const maxMonth = Math.max(1, ...s.by_month.map((m) => m.amount))
  return (
    <Page>
      <PageHeader title={tt("Finance")} subtitle={tt("Money billed, collected and still owed across your courses.")} actions={<button className="btn" onClick={() => download('/teach/finance/ledger.csv', 'ledger.csv')}><Download size={14} /> {tt("Export ledger (CSV)")}</button>} />
      {s.currency === 'mixed' && <p className="mb-3 rounded border border-warn/40 bg-warn/10 p-3 text-sm">{tt("Your courses use more than one currency: totals below are shown without conversion.")}</p>}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5"><Stat label={tt("Billed")} value={<Money v={s.billed} cur={cur} />} /><Stat label={tt("Collected")} value={<Money v={s.collected} cur={cur} />} tone="good" /><Stat label={tt("Outstanding")} value={<Money v={s.outstanding} cur={cur} />} tone={s.outstanding ? 'warn' : undefined} /><Stat label={tt("Overdue")} value={<Money v={s.overdue} cur={cur} />} tone={s.overdue ? 'bad' : undefined} /><Stat label={tt("Refunded")} value={<Money v={s.refunded} cur={cur} />} /></div>
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-4"><h2 className="h-section mb-3">{tt("Collected by month")}</h2>{s.by_month.length === 0 ? <p className="text-sm text-muted">{tt("No payments yet.")}</p> : <ul className="space-y-1.5">{s.by_month.map((m) => <li key={m.month} className="flex items-center gap-2 text-sm"><span className="w-16 text-xs text-muted tabnum" dir="ltr">{m.month}</span><span className="h-3 rounded bg-accent" style={{ width: `${(m.amount / maxMonth) * 70}%` }} /><Money v={m.amount} cur={cur} /></li>)}</ul>}</section>
        <section className="card p-4"><h2 className="h-section mb-3">{tt("By payment method")}</h2>{Object.keys(s.by_method).length === 0 ? <p className="text-sm text-muted">{tt("No payments yet.")}</p> : <ul className="space-y-1.5">{Object.entries(s.by_method).map(([k, v]) => <li key={k} className="flex justify-between text-sm"><span>{tl(k)}</span><Money v={v} cur={cur} /></li>)}</ul>}</section>
      </div>
      <h2 className="h-section mb-2 mt-6">{tt("By course")}</h2>
      <div className="card overflow-x-auto"><table className="w-full min-w-[560px] text-sm"><thead><tr className="border-b border-line text-xs text-muted">{[tt("Course"), tt("Orders"), tt("Billed"), tt("Collected"), tt("Outstanding")].map((h) => <th key={h} className="px-3 py-2 text-start font-medium">{h}</th>)}</tr></thead>
        <tbody>{s.by_course.map((c) => <tr key={c.course_id} className="border-b border-line last:border-0"><td className="px-3 py-2"><Link className="hover:underline" to={`/teach/courses/${c.course_id}`}>{c.course_title}</Link></td><td className="px-3 py-2 tabnum">{c.orders}</td><td className="px-3 py-2"><Money v={c.billed} cur={cur} /></td><td className="px-3 py-2"><Money v={c.collected} cur={cur} /></td><td className="px-3 py-2"><Money v={c.outstanding} cur={cur} /></td></tr>)}</tbody></table></div>
      <h2 className="h-section mb-2 mt-6">{tt("Overdue payments")}</h2>
      {s.overdue_orders.length === 0 ? <p className="text-sm text-muted">{tt("Nothing is overdue.")}</p> : <ul className="card divide-y divide-line">{s.overdue_orders.map((o) => <li key={o.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm"><span className="font-medium">{o.student_name}</span><span className="text-xs text-muted" dir="ltr">{o.student_email}</span><span className="text-muted">{o.course_title}</span><span className="ms-auto text-bad"><Money v={o.overdue} cur={o.currency} /></span></li>)}</ul>}
    </Page>
  )
}
