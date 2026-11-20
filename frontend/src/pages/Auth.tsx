import { useEffect, useState } from 'react'
import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { BookOpenText } from 'lucide-react'
import { useAuth } from '@/contexts/auth'
import { Button, Field } from '@/components/ui'
import { t } from '@/i18n'

export function AuthPage({ mode, staff }: { mode: 'login' | 'register'; staff?: boolean }) {
  const { user, login, register, logout } = useAuth()
  const loc = useLocation()
  const [sp] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // where to go after signing in: a protected page we came from, or ?next=/course/... (internal paths only)
  const nextParam = sp.get('next')
  const wanted = (loc.state as { from?: string } | null)?.from ?? (nextParam && nextParam.startsWith('/') && !nextParam.startsWith('//') ? nextParam : null)
  // default landing after sign-in: the user's own area (students -> /my, teachers/admins -> /teach)
  const dest = wanted ?? (user?.role === 'student' ? '/my' : '/teach')
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
      else await register(email, password, name)
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
        <form onSubmit={submit} className="mt-6 space-y-4">
          {!isLogin && <Field label={t('auth.name')}><input className="field text-base" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={100} dir="auto" /></Field>}
          <Field label={t('auth.email')}><input type="email" required className="field text-base" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus /></Field>
          <Field label={t('auth.password')} hint={isLogin ? undefined : t('auth.passwordHint')}>
            <input type="password" required minLength={isLogin ? undefined : 8} className="field text-base" dir="ltr" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={isLogin ? 'current-password' : 'new-password'} />
          </Field>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
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
