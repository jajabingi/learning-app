import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { get, patch, post, setAuthLostHandler, tokenStore, type Tokens } from '@/api/client'
import type { User } from '@/api/types'

interface AuthCtx {
  user: User | null
  loading: boolean
  login(email: string, password: string): Promise<void>
  register(email: string, password: string, name: string): Promise<void>
  logout(): void
  updateUser(patch: Partial<User>): Promise<void>
}
const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(!!tokenStore.get())
  const qc = useQueryClient()

  const logout = useCallback(() => {
    tokenStore.set(null)
    setUser(null)
    qc.clear()
  }, [qc])

  useEffect(() => {
    setAuthLostHandler(logout)
    if (!tokenStore.get()) return
    get<User>('/auth/me')
      .then(setUser)
      .catch(() => tokenStore.set(null))
      .finally(() => setLoading(false))
  }, [logout])

  const value = useMemo<AuthCtx>(
    () => ({
      user,
      loading,
      async login(email, password) {
        tokenStore.set(await post<Tokens>('/auth/login', { email, password }))
        setUser(await get<User>('/auth/me'))
      },
      async register(email, password, name) {
        tokenStore.set(await post<Tokens>('/auth/register', { email, password, display_name: name }))
        setUser(await get<User>('/auth/me'))
      },
      logout,
      async updateUser(p) {
        setUser(await patch<User>('/auth/me', p))
      },
    }),
    [user, loading, logout],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth() {
  const c = useContext(Ctx)
  if (!c) throw new Error('AuthProvider missing')
  return c
}
