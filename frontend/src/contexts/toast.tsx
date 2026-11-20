import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { CheckCircle2, AlertCircle, X } from 'lucide-react'

interface T { id: number; kind: 'ok' | 'err'; msg: string }
const Ctx = createContext<{ ok(m: string): void; err(m: string): void }>({ ok() {}, err() {} })
let n = 0

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<T[]>([])
  const push = useCallback((kind: T['kind'], msg: string) => {
    const id = ++n
    setItems((x) => [...x, { id, kind, msg }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), kind === 'err' ? 6000 : 3000)
  }, [])
  return (
    <Ctx.Provider value={{ ok: (m) => push('ok', m), err: (m) => push('err', m) }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="pointer-events-auto flex items-start gap-2 rounded-lg border border-line bg-surface px-3 py-2.5 text-sm shadow-lg">
            {t.kind === 'ok' ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-good" /> : <AlertCircle size={16} className="mt-0.5 shrink-0 text-bad" />}
            <span className="flex-1">{t.msg}</span>
            <button aria-label="Dismiss" className="text-faint hover:text-fg" onClick={() => setItems((x) => x.filter((i) => i.id !== t.id))}>
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
export const useToast = () => useContext(Ctx)
