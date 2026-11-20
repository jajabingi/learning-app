import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

type Pref = 'light' | 'dark' | 'system'
const Ctx = createContext<{ pref: Pref; setPref(p: Pref): void; dark: boolean }>({ pref: 'system', setPref() {}, dark: false })

function read(): Pref {
  try {
    return (localStorage.getItem('recall.theme') as Pref) || 'system'
  } catch {
    return 'system'
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<Pref>(read)
  const [sysDark, setSysDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches)

  useEffect(() => {
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const h = (e: MediaQueryListEvent) => setSysDark(e.matches)
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [])

  const dark = pref === 'dark' || (pref === 'system' && sysDark)
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  }, [dark])

  const setPref = (p: Pref) => {
    setPrefState(p)
    try {
      localStorage.setItem('recall.theme', p)
    } catch {
      /* ignore */
    }
  }
  return <Ctx.Provider value={{ pref, setPref, dark }}>{children}</Ctx.Provider>
}

export const useTheme = () => useContext(Ctx)
