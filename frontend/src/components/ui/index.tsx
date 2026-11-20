import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { CheckCircle2, Circle, CircleDashed, Loader2, PauseCircle, RefreshCw, X, MoreHorizontal } from 'lucide-react'
import type { Status } from '@/api/types'
import { tt } from '@/i18n'


export const cx = clsx

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx('animate-spin text-faint', className)} size={18} aria-label={tt("Loading")} />
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
      <Spinner /> {label}
    </div>
  )
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="card mx-auto my-10 max-w-md p-6 text-center">
      <p className="text-sm font-medium text-bad">{tt("Something went wrong")}</p>
      <p className="mt-1 text-sm text-muted">{error instanceof Error ? error.message : tt("Unexpected error")}</p>
      {retry && (
        <button className="btn mt-4" onClick={retry}>
          {tt("Try again")}
        </button>
      )}
    </div>
  )
}

export function Empty({ title, children, action, icon }: { title: string; children?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      {icon && <div className="mb-3 text-faint">{icon}</div>}
      <p className="text-sm font-medium">{title}</p>
      {children && <p className="mt-1 max-w-sm text-sm text-muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="h-page truncate">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

const STATUS_META: Record<Status, { label: string; cls: string; Icon: typeof Circle }> = {
  new: { label: tt("New"), cls: 'text-muted bg-raised', Icon: Circle },
  learning: { label: tt("Learning"), cls: 'text-warn bg-warn/10', Icon: CircleDashed },
  reviewing: { label: tt("Reviewing"), cls: 'text-accent bg-accent/10', Icon: RefreshCw },
  mastered: { label: tt("Mastered"), cls: 'text-good bg-good/10', Icon: CheckCircle2 },
  suspended: { label: tt("Suspended"), cls: 'text-faint bg-raised line-through', Icon: PauseCircle },
}
export const statusLabel = (s: Status) => STATUS_META[s].label

export function StatusBadge({ status, compact }: { status: Status; compact?: boolean }) {
  const m = STATUS_META[status] ?? STATUS_META.new
  return (
    <span className={cx('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium', m.cls)} title={m.label}>
      <m.Icon size={12} /> {!compact && m.label}
    </span>
  )
}

export function Badge({ children, tone = 'neutral', className }: { children: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'bad' | 'accent'; className?: string }) {
  const t = { neutral: 'bg-raised text-muted', good: 'bg-good/10 text-good', warn: 'bg-warn/10 text-warn', bad: 'bg-bad/10 text-bad', accent: 'bg-accent/10 text-accent' }[tone]
  return <span className={cx('inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium', t, className)}>{children}</span>
}

export function ProgressBar({ value, tone, className, label }: { value: number; tone?: 'good' | 'warn' | 'bad' | 'accent'; className?: string; label?: string }) {
  const v = Math.max(0, Math.min(1, value || 0))
  const t = tone ?? (v >= 0.7 ? 'good' : v >= 0.35 ? 'warn' : 'bad')
  return (
    <div
      className={cx('h-1.5 w-full overflow-hidden rounded-full bg-raised', className)}
      role="progressbar"
      aria-valuenow={Math.round(v * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className={cx('h-full rounded-full', { good: 'bg-good', warn: 'bg-warn', bad: 'bg-bad', accent: 'bg-accent' }[t])} style={{ width: `${v * 100}%` }} />
    </div>
  )
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'good' | 'warn' | 'bad' }) {
  return (
    <div className="card p-4">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className={cx('tabnum mt-1 text-2xl font-semibold tracking-tight', tone && { good: 'text-good', warn: 'text-warn', bad: 'text-bad' }[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  )
}

export function Modal({ open, onClose, title, children, wide, footer, dir }: { open: boolean; onClose(): void; title: ReactNode; children: ReactNode; wide?: boolean; footer?: ReactNode; dir?: 'rtl' | 'ltr' }) {
  const id = useId()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    ref.current?.querySelector<HTMLElement>('input, textarea, select, button')?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      prev?.focus?.()
    }
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} dir={dir} role="dialog" aria-modal="true" aria-labelledby={id} className={cx('flex max-h-[92vh] w-full flex-col rounded-t-xl border border-line bg-surface shadow-xl sm:rounded-lg', wide ? 'sm:max-w-3xl' : 'sm:max-w-lg')}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 id={id} className="text-sm font-semibold">{title}</h2>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label={tt("Close")}><X size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-3 safe-bottom">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

export function ConfirmDialog({ open, onClose, onConfirm, title, message, confirmLabel = 'Delete', danger = true, busy }: { open: boolean; onClose(): void; onConfirm(): void; title: string; message: ReactNode; confirmLabel?: string; danger?: boolean; busy?: boolean }) {
  return (
    <Modal open={open} onClose={onClose} title={title} footer={<><button className="btn" onClick={onClose}>{tt("Cancel")}</button><button className={cx('btn', danger ? 'bg-bad text-white border-transparent hover:bg-bad hover:opacity-90' : 'btn-primary')} onClick={onConfirm} disabled={busy}>{confirmLabel}</button></>}>
      <div className="text-sm text-muted">{message}</div>
    </Modal>
  )
}

export function Menu({ items, label = tt('More actions'), icon }: { items: ({ label: string; onClick(): void; danger?: boolean; disabled?: boolean } | 'sep')[]; label?: string; icon?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const k = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', h)
    document.addEventListener('keydown', k)
    return () => {
      document.removeEventListener('mousedown', h)
      document.removeEventListener('keydown', k)
    }
  }, [open])
  return (
    <div className="relative" ref={ref}>
      <button className="btn btn-ghost btn-icon" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {icon ?? <MoreHorizontal size={16} />}
      </button>
      {open && (
        <div role="menu" className="absolute end-0 z-30 mt-1 min-w-44 rounded-lg border border-line bg-surface py-1 shadow-lg">
          {items.map((it, i) =>
            it === 'sep' ? (
              <div key={i} className="my-1 border-t border-line" />
            ) : (
              <button key={i} role="menuitem" disabled={it.disabled} className={cx('block w-full px-3 py-1.5 text-start text-sm hover:bg-raised disabled:opacity-50', it.danger && 'text-bad')} onClick={() => { setOpen(false); it.onClick() }}>
                {it.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange(v: T): void }) {
  return (
    <div role="tablist" className="-mx-1 flex gap-1 overflow-x-auto border-b border-line px-1">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)} className={cx('-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium', value === t.id ? 'border-accent text-fg' : 'border-transparent text-muted hover:text-fg')}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function Segmented<T extends string>({ options, value, onChange, label }: { options: { value: T; label: ReactNode }[]; value: T; onChange(v: T): void; label?: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded border border-line bg-raised p-0.5">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)} className={cx('rounded px-2.5 py-1 text-xs font-medium', value === o.value ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-faint">{hint}</span>}
    </label>
  )
}

export function Button({ loading, children, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  return (
    <button {...rest} disabled={rest.disabled || loading} className={cx('btn', className)}>
      {loading && <Loader2 size={14} className="animate-spin" />}
      {children}
    </button>
  )
}

export function TagList({ tags }: { tags: { id: string; name: string }[] }) {
  if (!tags.length) return null
  return (
    <span className="inline-flex flex-wrap gap-1">
      {tags.map((t) => (
        <span key={t.id} className="rounded bg-raised px-1.5 py-0.5 text-xs text-muted">#{t.name}</span>
      ))}
    </span>
  )
}

export function TagInput({ value, onChange, suggestions = [] }: { value: string[]; onChange(v: string[]): void; suggestions?: string[] }) {
  const [text, setText] = useState('')
  const listId = useId()
  const add = (raw: string) => {
    const v = raw.trim().toLowerCase()
    if (v && !value.includes(v)) onChange([...value, v])
    setText('')
  }
  return (
    <div className="flex flex-wrap items-center gap-1 rounded border border-line bg-surface px-1.5 py-1 focus-within:border-accent">
      {value.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded bg-raised px-1.5 py-0.5 text-xs">
          #{t}
          <button type="button" aria-label={tt("Remove tag {t}", { t: t })} className="text-faint hover:text-fg" onClick={() => onChange(value.filter((x) => x !== t))}><X size={11} /></button>
        </span>
      ))}
      <input
        list={listId}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(text) }
          else if (e.key === 'Backspace' && !text && value.length) onChange(value.slice(0, -1))
        }}
        onBlur={() => add(text)}
        placeholder={value.length ? '' : tt("Add tags…")}
        className="min-w-24 flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-faint"
        aria-label={tt("Add tag")}
      />
      <datalist id={listId}>{suggestions.map((s) => <option key={s} value={s} />)}</datalist>
    </div>
  )
}
