import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { BookOpenText } from 'lucide-react'
import { useAuth } from '@/contexts/auth'
import { Button, Field } from '@/components/ui'
import { t, tt } from '@/i18n'
import { get } from '@/api/client'

export function AuthPage({ mode, staff }: { mode: 'login' | 'register'; staff?: boolean }) {
  const { user, login, register, logout } = useAuth()
  const loc = useLocation()
  const [sp] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const cfg = useQuery({ queryKey: ['auth-config'], queryFn: () => get<{ google_enabled: boolean }>('/auth/config'), staleTime: 60_000 })
  // where to go after signing in: a protected page we came from, or ?next=/course/... (internal paths only)
  const nextParam = sp.get('next')
  const wanted = (loc.state as { from?: string } | null)?.from ?? (nextParam && nextParam.startsWith('/') && !nextParam.startsWith('//') ? nextParam : null)
  // default landing after sign-in: the user's own area (students -> /my, teachers/admins -> /teach)
  const dest = wanted ?? (user?.role === 'student' ? '/my' : user?.role === 'admin' ? '/admin' : '/teach')
  // the teachers' entrance only admits teachers/admins
  useEffect(() => { if (staff && user?.role === 'student') { logout(); setError(t('auth.notTeacher')) } }, [staff, user]) // eslint-disable-line react-hooks/exhaustive-deps
  if (user && !(staff && user.role === 'student')) return <Navigate to={dest} replace />
  const isLogin = mode === 'login'
  const title = staff ? t('auth.teacherTitle') : isLogin ? t('auth.loginTitle') : t('auth.registerTitle')
  const other = `${isLogin ? '/register' : '/login'}${nextParam ? `?next=${encodeURIComponent(nextParam)}` : ''}`

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (isLogin) await login(email, password)
      else if ((await register(email, password, name)).verificationRequired) setNotice(tt("We sent you an email. Open the link in it to activate your account, then sign in."))
      // the redirect happens above once the signed-in user is known
    } catch (err) {
      setError(err instanceof Error ? err.message : t('auth.somethingWrong'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div dir="rtl" lang="he" className="flex min-h-full items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <Link to="/" className="mb-6 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-accent-fg"><BookOpenText size={19} /></div>
          <span className="text-lg font-semibold tracking-tight">Recall</span>
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 text-[15px] leading-7 text-muted">{staff ? t('auth.teacherHint') : t('auth.tagline')}</p>
        {cfg.data?.google_enabled && <>
          <a href="/api/auth/google/start" className="btn btn-lg mt-6 flex w-full items-center justify-center gap-2 text-base" dir="auto">
            <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" /><path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.4 5.8c4.3-4 6.9-9.9 6.9-17.2z" /><path fill="#FBBC05" d="M10.5 28.7a14.5 14.5 0 0 1 0-9.4l-7.9-6.1a24 24 0 0 0 0 21.6l7.9-6.1z" /><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.8c-2.1 1.4-4.8 2.3-8.5 2.3-6.3 0-11.6-4.1-13.5-9.9l-7.9 6.1C6.5 42.6 14.6 48 24 48z" /></svg>
            {tt("Continue with Google")}
          </a>
          <div className="my-4 flex items-center gap-3 text-xs text-muted"><span className="h-px flex-1 bg-line" />{tt("or")}<span className="h-px flex-1 bg-line" /></div>
        </>}
        <form onSubmit={submit} className={`${cfg.data?.google_enabled ? '' : 'mt-6 '}space-y-4`}>
          {!isLogin && <Field label={t('auth.name')}><input className="field text-base" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={100} dir="auto" /></Field>}
          <Field label={t('auth.email')}><input type="email" required className="field text-base" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus /></Field>
          <Field label={t('auth.password')} hint={isLogin ? undefined : t('auth.passwordHint')}>
            <input type="password" required minLength={isLogin ? undefined : 8} className="field text-base" dir="ltr" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={isLogin ? 'current-password' : 'new-password'} />
          </Field>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          {notice && <p role="status" className="rounded border border-good/40 bg-good/10 p-3 text-sm">{notice}</p>}
          {isLogin && <p className="text-sm"><Link className="text-accent underline" to="/forgot-password">{tt("Forgot your password?")}</Link></p>}
          <Button type="submit" className="btn-primary btn-lg w-full" loading={busy}>{isLogin ? t('auth.loginBtn') : t('auth.registerBtn')}</Button>
        </form>
        {!staff && <p className="mt-4 text-sm text-muted">
          {isLogin ? <>{t('auth.newHere')} <Link className="text-accent underline" to={other}>{t('auth.createAccount')}</Link></> : <>{t('auth.haveAccount')} <Link className="text-accent underline" to={other}>{t('auth.signInLink')}</Link></>}
        </p>}
        <p className="mt-6 text-sm"><Link to="/" className="text-muted underline">{t('nav.home')}</Link></p>
      </div>
    </div>
  )
}
