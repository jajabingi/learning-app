import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BookOpenText, ShieldAlert } from 'lucide-react'
import { del, get, post, type Tokens } from '@/api/client'
import { Button, Field, Loading } from '@/components/ui'
import { useAuth } from '@/contexts/auth'
import { useToast } from '@/contexts/toast'
import { tt } from '@/i18n'

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div dir="rtl" lang="he" className="flex min-h-full items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <Link to="/" className="mb-6 flex items-center gap-2"><div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-accent-fg"><BookOpenText size={19} /></div><span className="text-lg font-semibold tracking-tight">Recall</span></Link>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <div className="mt-5">{children}</div>
        <p className="mt-6 text-sm"><Link to="/login" className="text-muted underline">{tt("Back to sign in")}</Link></p>
      </div>
    </div>
  )
}

export function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return (
    <Shell title={tt("Reset your password")}>
      {sent ? <p role="status" className="rounded border border-good/40 bg-good/10 p-3 text-sm">{tt("If the address has an account, an email with instructions was sent.")}</p> : (
        <form className="space-y-4" onSubmit={async (e) => { e.preventDefault(); setBusy(true); setError(''); try { await post('/auth/password/forgot', { email }); setSent(true) } catch (x) { setError(x instanceof Error ? x.message : '') } finally { setBusy(false) } }}>
          <p className="text-sm text-muted">{tt("Enter your email and we will send you a link to choose a new password.")}</p>
          <Field label={tt("Email")}><input type="email" required dir="ltr" className="field text-base" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus /></Field>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          <Button type="submit" className="btn-primary btn-lg w-full" loading={busy}>{tt("Send reset link")}</Button>
        </form>
      )}
    </Shell>
  )
}

export function ResetPassword() {
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const toast = useToast()
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const token = sp.get('token') ?? ''
  return (
    <Shell title={tt("Choose a new password")}>
      <form className="space-y-4" onSubmit={async (e) => { e.preventDefault(); setBusy(true); setError(''); try { await post('/auth/password/reset', { token, new_password: pw }); toast.ok(tt("Password changed. You can sign in now.")); nav('/login', { replace: true }) } catch (x) { setError(x instanceof Error ? x.message : '') } finally { setBusy(false) } }}>
        <Field label={tt("New password")} hint={tt("At least 8 characters")}><input type="password" required minLength={8} dir="ltr" className="field text-base" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" autoFocus /></Field>
        {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        <Button type="submit" className="btn-primary btn-lg w-full" loading={busy} disabled={!token}>{tt("Change password")}</Button>
      </form>
    </Shell>
  )
}

/** Opened from the verification / link-confirmation email: spends the single-use token and signs the user in. */
function TokenLanding({ endpoint, title, ok }: { endpoint: string; title: string; ok: string }) {
  const [sp] = useSearchParams()
  const { loginWithTokens } = useAuth()
  const [state, setState] = useState<'work' | 'done' | 'fail'>('work')
  const [msg, setMsg] = useState('')
  const ran = useRef(false)
  useEffect(() => {
    if (ran.current) return
    ran.current = true // the token is single-use: never spend it twice (React strict mode)
    post<Tokens>(endpoint, { token: sp.get('token') ?? '' })
      .then((t) => loginWithTokens(t)).then(() => setState('done'))
      .catch((e) => { setMsg(e instanceof Error ? e.message : ''); setState('fail') })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Shell title={title}>
      {state === 'work' && <Loading />}
      {state === 'done' && <><p role="status" className="rounded border border-good/40 bg-good/10 p-3 text-sm">{ok}</p><Navigate to="/" replace /></>}
      {state === 'fail' && <p role="alert" className="rounded border border-bad/40 bg-bad/10 p-3 text-sm">{msg || tt("This link is invalid or has expired")}</p>}
    </Shell>
  )
}
export const VerifyEmail = () => <TokenLanding endpoint="/auth/email/verify" title={tt("Verifying your email")} ok={tt("Your email is verified.")} />
export const LinkConfirm = () => <TokenLanding endpoint="/auth/link/confirm" title={tt("Connecting Google")} ok={tt("Google is now connected to your account.")} />

const ERRORS: Record<string, string> = {
  google_failed: 'Google sign-in failed. Please try again.', google_denied: 'Google sign-in was cancelled.', suspended: 'This account is suspended. Contact an administrator.',
  account_exists: 'An account with this email already exists. We sent a confirmation link to that address — open it to connect Google, or sign in with your password.',
  google_in_use: 'This Google account is already connected to another user.', registration_disabled: 'Registration is disabled.',
}

/** Landing page of the Google redirect: trades the single-use code for tokens (tokens never travel in a URL). */
export function AuthCallback() {
  const [sp] = useSearchParams()
  const { loginWithTokens, user } = useAuth()
  const [error, setError] = useState(sp.get('error') ?? '')
  const ran = useRef(false)
  const code = sp.get('code')
  useEffect(() => {
    if (ran.current || !code) return
    ran.current = true
    post<Tokens>('/auth/google/exchange', { code }).then(loginWithTokens).catch(() => setError('google_failed'))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  if (sp.get('linked') && user) return <Navigate to={user.role === 'student' ? '/account' : '/settings'} replace />
  if (user) return <Navigate to={user.role === 'student' ? '/my' : user.role === 'admin' ? '/admin' : '/teach'} replace />
  return (
    <Shell title={tt("Signing you in")}>
      {error ? <p role="alert" className="rounded border border-bad/40 bg-bad/10 p-3 text-sm">{tt(ERRORS[error] ?? ERRORS.google_failed)}</p> : <Loading />}
    </Shell>
  )
}

/** Shown when a signed-in user opens a page their role may not use (the server enforces this independently). */
export function Forbidden() {
  const { user } = useAuth()
  const home = user?.role === 'student' ? '/my' : user?.role === 'admin' ? '/admin' : '/teach'
  return (
    <div dir="rtl" className="mx-auto max-w-md px-4 py-16 text-center">
      <ShieldAlert size={36} className="mx-auto text-warn" />
      <h1 className="mt-3 text-2xl font-semibold">{tt("You do not have access to this page")}</h1>
      <p className="mt-2 text-muted">{tt("Your account does not have the permissions needed for this area. If you think this is a mistake, contact an administrator.")}</p>
      <Link to={home} className="btn btn-primary mt-5 inline-flex">{tt("Back to my area")}</Link>
    </div>
  )
}

/** Sign-in methods card for the account/settings pages: connect or disconnect Google. */
export function SignInMethods() {
  const toast = useToast()
  const cfg = useQuery({ queryKey: ['auth-config'], queryFn: () => get<{ google_enabled: boolean }>('/auth/config'), staleTime: 60_000 })
  const q = useQuery({ queryKey: ['auth-identities'], queryFn: () => get<{ has_password: boolean; identities: { id: string; provider: string; email: string }[] }>('/auth/identities') })
  const [busy, setBusy] = useState(false)
  if (!q.data) return null
  const google = q.data.identities.find((i) => i.provider === 'google')
  const link = async () => { setBusy(true); try { const r = await post<{ url: string }>('/auth/google/link/start'); window.location.href = r.url } catch (e) { toast.err(e instanceof Error ? e.message : ''); setBusy(false) } }
  const unlink = async () => { try { await del(`/auth/identities/${google!.id}`); await q.refetch(); toast.ok(tt("Google was disconnected")) } catch (e) { toast.err(e instanceof Error ? e.message : '') } }
  return (
    <section className="card space-y-3 p-5">
      <h2 className="text-base font-semibold">{tt("Sign-in methods")}</h2>
      <ul className="space-y-2 text-sm">
        <li className="flex items-center justify-between gap-3"><span>{tt("Email and password")}</span><span className="text-muted">{q.data.has_password ? tt("Active") : tt("Not set")}</span></li>
        <li className="flex items-center justify-between gap-3"><span>Google{google ? <span dir="ltr" className="ms-2 text-xs text-muted">{google.email}</span> : null}</span>
          {google ? <button className="btn h-8" onClick={unlink}>{tt("Disconnect")}</button> : cfg.data?.google_enabled ? <Button className="h-8" loading={busy} onClick={link}>{tt("Connect Google")}</Button> : <span className="text-muted">{tt("Not available")}</span>}</li>
      </ul>
    </section>
  )
}
