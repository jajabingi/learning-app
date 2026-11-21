import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Printer } from 'lucide-react'
import { get, post } from '@/api/client'
import { Badge, Button, Empty, ErrorState, Loading } from '@/components/ui'
import { useToast } from '@/contexts/toast'
import { shortDate } from '@/lib/format'
import { tt, tl } from '@/i18n'

interface P { id: string; kind: 'payment' | 'refund'; amount: number; method: string; status: string; date: string; receipt_no: string | null }
interface Inst { id: string; amount: number; due_date: string; paid: number; status: string; overdue: boolean }
interface Order { id: string; course_id: string; course_title: string; currency: string; amount_due: number; paid: number; balance: number; pending: number; status: string; payment_instructions: string; can_pay_online: boolean; installments: Inst[]; overdue: number; payments: P[] }
const money = (n: number, cur = 'ILS') => new Intl.NumberFormat('he-IL', { style: 'currency', currency: cur }).format(n)
const M = ({ v, cur }: { v: number; cur?: string }) => <span dir="ltr" className="tabnum">{money(v, cur)}</span>

export function StudentPayments() {
  const q = useQuery({ queryKey: ['student-payments'], queryFn: () => get<{ online_enabled: boolean; orders: Order[] }>('/student/payments'), staleTime: 0 })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div><h1 className="text-3xl font-semibold tracking-tight">{tt("My payments")}</h1><p className="mt-1 text-lg text-muted">{tt("What you owe, what you paid, and your receipts.")}</p></div>
      {q.data.orders.length === 0 ? <div className="card"><Empty title={tt("No payments yet")}>{tt("When you sign up for a paid course, the amount and how to pay appear here.")}</Empty></div> : q.data.orders.map((o) => <OrderCard key={o.id} o={o} />)}
    </div>
  )
}

function OrderCard({ o }: { o: Order }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [amount, setAmount] = useState('')
  const checkout = useMutation({ mutationFn: () => post<{ redirect: string | null }>(`/student/orders/${o.id}/checkout`, { amount: amount === '' ? null : amount }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['student-payments'] }); if (r.redirect) nav(r.redirect) }, onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")) })
  return (
    <section className="card space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 dir="auto" className="text-xl font-semibold">{o.course_title}</h2><Badge tone={o.status === 'paid' ? 'good' : 'warn'}>{o.status === 'paid' ? tt("Paid in full") : tt("Balance due")}</Badge></div>
      <dl className="grid grid-cols-3 gap-3 text-center"><div><dt className="text-sm text-muted">{tt("Price")}</dt><dd className="text-lg font-semibold"><M v={o.amount_due} cur={o.currency} /></dd></div><div><dt className="text-sm text-muted">{tt("Paid")}</dt><dd className="text-lg font-semibold text-good"><M v={o.paid} cur={o.currency} /></dd></div><div><dt className="text-sm text-muted">{tt("Balance")}</dt><dd className="text-lg font-semibold"><M v={o.balance} cur={o.currency} /></dd></div></dl>
      {o.overdue > 0 && <p role="alert" className="rounded border border-bad/40 bg-bad/10 p-3 text-sm">{tt("You have an overdue amount of")} <M v={o.overdue} cur={o.currency} />.</p>}
      {o.pending > 0 && <p className="rounded border border-warn/40 bg-warn/10 p-3 text-sm">{tt("An online payment is waiting for confirmation. It is counted only after it is confirmed.")}</p>}
      {o.installments.length > 0 && <div><h3 className="mb-1 text-sm font-semibold">{tt("Payment schedule")}</h3><ul className="divide-y divide-line rounded-lg border border-line">{o.installments.map((i) => <li key={i.id} className="flex items-center gap-3 px-3 py-2 text-sm"><span dir="ltr" className="tabnum">{shortDate(i.due_date)}</span><M v={i.amount} cur={o.currency} /><Badge tone={i.status === 'paid' ? 'good' : i.overdue ? 'bad' : 'neutral'}>{i.status === 'paid' ? tt("Paid") : i.overdue ? tt("Overdue") : tt("Upcoming")}</Badge></li>)}</ul></div>}
      {o.balance > 0 && o.payment_instructions && <div className="rounded-lg bg-raised/60 p-4"><h3 className="mb-1 text-sm font-semibold">{tt("How to pay")}</h3><p dir="auto" className="whitespace-pre-wrap text-sm">{o.payment_instructions}</p><p className="mt-2 text-xs text-muted">{tt("After you pay, your teacher confirms the payment and your access opens.")}</p></div>}
      {o.can_pay_online && o.balance > 0 && <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); checkout.mutate() }}>
        <label className="text-sm">{tt("Amount to pay now")}<input type="number" min={1} max={o.balance} step="0.01" dir="ltr" className="field mt-1 w-40" placeholder={String(o.balance)} value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        <Button type="submit" className="btn-primary" loading={checkout.isPending}>{tt("Pay online")}</Button></form>}
      {o.payments.length > 0 && <div><h3 className="mb-1 text-sm font-semibold">{tt("Payment history")}</h3><ul className="divide-y divide-line rounded-lg border border-line">{o.payments.map((p) => (
        <li key={p.id} className={`flex flex-wrap items-center gap-3 px-3 py-2 text-sm ${p.status === 'voided' ? 'text-faint line-through' : ''}`}><span className="text-xs tabnum">{shortDate(p.date.slice(0, 10))}</span><M v={p.kind === 'refund' ? -p.amount : p.amount} cur={o.currency} /><span className="text-muted">{p.kind === 'refund' ? tt("Refund") : tl(p.method)}</span><Badge tone={p.status === 'confirmed' ? 'good' : p.status === 'pending' ? 'warn' : 'neutral'}>{tl(p.status)}</Badge>
          {p.status === 'confirmed' && p.receipt_no && <Link to={`/receipt/${p.id}`} className="ms-auto text-accent underline" dir="ltr">{p.receipt_no}</Link>}</li>))}</ul></div>}
    </section>
  )
}

/** TEST-ONLY stand-in for a hosted gateway page (only reachable when the server runs the sandbox provider). */
export function SandboxPay() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const toast = useToast()
  const q = useQuery({ queryKey: ['sandbox-payment', id], queryFn: () => get<{ status: string; amount: number }>(`/student/payments/${id}`) })
  const done = useMutation({ mutationFn: (outcome: 'success' | 'fail') => post(`/student/payments/${id}/sandbox-complete`, { outcome }), onSuccess: () => nav('/payments'), onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")) })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  return (
    <div className="mx-auto max-w-md space-y-4 text-center">
      <p className="rounded border border-warn/40 bg-warn/10 p-3 text-sm">{tt("TEST MODE: this is a simulated payment page. No real money moves.")}</p>
      <h1 className="text-2xl font-semibold">{tt("Pay")} <M v={q.data.amount} /></h1>
      <div className="flex justify-center gap-3"><Button className="btn-primary" loading={done.isPending} onClick={() => done.mutate('success')}>{tt("Simulate successful payment")}</Button><button className="btn" onClick={() => done.mutate('fail')}>{tt("Simulate failure")}</button></div>
    </div>
  )
}

interface R { receipt_no: string; kind: string; date: string; amount: number; currency: string; method: string; reference: string; student: { name: string; email: string }; course: string; issued_by: string; order_total: number; paid_to_date: number; balance_after: number }
export function Receipt() {
  const { id = '' } = useParams()
  const q = useQuery({ queryKey: ['receipt', id], queryFn: () => get<R>(`/student/payments/${id}/receipt`) })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={q.refetch} />
  const r = q.data
  return (
    <div className="mx-auto max-w-xl space-y-4">
      <div className="print:hidden flex gap-2"><Link to="/payments" className="btn">{tt("← My payments")}</Link><button className="btn btn-primary" onClick={() => window.print()}><Printer size={14} /> {tt("Print / save as PDF")}</button></div>
      <article className="card space-y-3 p-6">
        <header className="flex items-start justify-between"><h1 className="text-2xl font-semibold">{r.kind === 'refund' ? tt("Credit note") : tt("Payment receipt")}</h1><span dir="ltr" className="tabnum text-lg font-semibold">{r.receipt_no}</span></header>
        <dl className="space-y-1.5 text-sm">{[[tt("Date"), shortDate(r.date.slice(0, 10))], [tt("Received from"), `${r.student.name} (${r.student.email})`], [tt("For"), r.course], [tt("Issued by"), r.issued_by], [tt("Method"), tl(r.method)], ...(r.reference ? [[tt("Reference"), r.reference]] : [])].map(([k, v]) => <div key={k} className="flex justify-between gap-4 border-b border-line py-1"><dt className="text-muted">{k}</dt><dd dir="auto" className="font-medium">{v}</dd></div>)}</dl>
        <p className="pt-2 text-center text-3xl font-semibold"><M v={r.amount} cur={r.currency} /></p>
        <dl className="grid grid-cols-3 gap-2 text-center text-xs text-muted"><div>{tt("Course price")}<div className="text-base text-fg"><M v={r.order_total} cur={r.currency} /></div></div><div>{tt("Paid to date")}<div className="text-base text-fg"><M v={r.paid_to_date} cur={r.currency} /></div></div><div>{tt("Balance")}<div className="text-base text-fg"><M v={r.balance_after} cur={r.currency} /></div></div></dl>
      </article>
    </div>
  )
}
