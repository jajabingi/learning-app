import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { get, patch, post, setAuthLostHandler, tokenStore, type Tokens } from '@/api/client'
import type { User } from '@/api/types'

interface AuthCtx {
  user: User | null
  loading: boolean
  login(email: string, password: string): Promise<void>
  register(email: string, password: string, name: string): Promise<{ verificationRequired: boolean }>
  loginWithTokens(t: Tokens): Promise<void>
  logout(): void
  updateUser(patch: Partial<User>): Promise<void>
}
const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(!!tokenStore.get())
  const qc = useQueryClient()

  const clear = useCallback(() => {
    tokenStore.set(null)
    setUser(null)
    qc.clear()
  }, [qc])
  // explicit sign-out also revokes the account's tokens on the server (best effort)
  const logout = useCallback(() => {
    if (tokenStore.get()) post('/auth/logout').catch(() => undefined)
    clear()
  }, [clear])

  useEffect(() => {
    setAuthLostHandler(clear)
    if (!tokenStore.get()) return
    get<User>('/auth/me')
      .then(setUser)
      .catch(() => tokenStore.set(null))
      .finally(() => setLoading(false))
  }, [clear])

  const value = useMemo<AuthCtx>(
    () => ({
      user,
      loading,
      async login(email, password) {
        tokenStore.set(await post<Tokens>('/auth/login', { email, password }))
        setUser(await get<User>('/auth/me'))
      },
      async register(email, password, name) {
        const r = await post<Tokens & { verification_required?: boolean }>('/auth/register', { email, password, display_name: name })
        if (r.verification_required) return { verificationRequired: true }
        tokenStore.set(r)
        setUser(await get<User>('/auth/me'))
        return { verificationRequired: false }
      },
      async loginWithTokens(t) {
        tokenStore.set(t)
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
