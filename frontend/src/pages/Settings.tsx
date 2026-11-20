import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, download, post } from '@/api/client'
import { Page } from '@/components/Layout'
import { Badge, Button, Field, PageHeader, Segmented } from '@/components/ui'
import { useAuth } from '@/contexts/auth'
import { useTheme } from '@/contexts/theme'
import { useToast } from '@/contexts/toast'
import { useAiStatus } from '@/hooks/queries'

function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return <section className="card mb-5 p-5"><h2 className="text-sm font-semibold">{title}</h2>{desc && <p className="mb-4 mt-0.5 text-sm text-muted">{desc}</p>}<div className={desc ? '' : 'mt-3'}>{children}</div></section>
}

export default function SettingsPage() {
  const { user, updateUser } = useAuth()
  const { pref, setPref } = useTheme()
  const toast = useToast()
  const qc = useQueryClient()
  const ai = useAiStatus()
  const [name, setName] = useState(user?.display_name ?? '')
  const [retention, setRetention] = useState(Math.round((user?.desired_retention ?? 0.9) * 100))
  const [newLimit, setNewLimit] = useState(user?.daily_new_limit ?? 20)
  const [goal, setGoal] = useState(user?.daily_review_goal ?? 30)
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState('')
  const jsonFile = useRef<HTMLInputElement>(null)
  const csvFile = useRef<HTMLInputElement>(null)
  const err = (e: unknown) => toast.err(e instanceof Error ? e.message : 'Failed')

  async function saveProfile() {
    setBusy('profile')
    try { await updateUser({ display_name: name, desired_retention: retention / 100, daily_new_limit: newLimit, daily_review_goal: goal }); toast.ok('Settings saved') } catch (e) { err(e) } finally { setBusy('') }
  }
  async function changePw() {
    setBusy('pw')
    try { await post('/auth/change-password', { current_password: cur, new_password: next }); setCur(''); setNext(''); toast.ok('Password changed') } catch (e) { err(e) } finally { setBusy('') }
  }
  async function upload(path: string, f: File) {
    const form = new FormData(); form.append('file', f)
    try {
      const r = await api<Record<string, number | unknown[]>>(path, { form })
      qc.invalidateQueries()
      toast.ok(path.includes('json') ? `Imported ${r.subjects} subjects, ${r.topics} topics, ${r.questions} questions, ${r.notes} notes` : `Imported ${r.created} questions${r.error_count ? `, ${r.error_count} row(s) skipped` : ''}`)
    } catch (e) { err(e) }
  }

  return (
    <Page narrow>
      <PageHeader title="Settings" />
      <Section title="Profile">
        <div className="grid gap-3 sm:grid-cols-2"><Field label="Display name"><input className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} /></Field><Field label="Email"><input className="field" value={user?.email ?? ''} disabled /></Field></div>
      </Section>

      <Section title="Appearance">
        <Segmented label="Theme" value={pref} onChange={setPref} options={[{ value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }, { value: 'system', label: 'System' }]} />
      </Section>

      <Section title="Learning" desc="Controls the spaced-repetition scheduler (FSRS).">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={`Target retention: ${retention}%`} hint="Higher = more frequent reviews. 90% is a good default."><input type="range" min={75} max={97} value={retention} onChange={(e) => setRetention(Number(e.target.value))} className="w-full" aria-label="Target retention" /></Field>
          <Field label="New questions per day"><input type="number" min={0} max={500} className="field" value={newLimit} onChange={(e) => setNewLimit(Number(e.target.value))} /></Field>
          <Field label="Daily review goal"><input type="number" min={1} max={2000} className="field" value={goal} onChange={(e) => setGoal(Number(e.target.value))} /></Field>
        </div>
        <Button className="btn-primary mt-4" loading={busy === 'profile'} onClick={saveProfile}>Save settings</Button>
      </Section>

      <Section title="AI features" desc="AI runs on the server; your API key is never sent to the browser.">
        <div className="flex items-center gap-2 text-sm">{ai.data?.enabled ? <><Badge tone="good">Enabled</Badge><span className="text-muted">{ai.data.provider} · {ai.data.model}</span></> : <><Badge>Not configured</Badge><span className="text-muted">Set <code className="font-mono">ANTHROPIC_API_KEY</code> in the backend environment and restart the server.</span></>}</div>
      </Section>

      <Section title="Import & export" desc="Back up everything as JSON, or move questions in and out with CSV. Imports are added alongside existing data; nothing is overwritten.">
        <input ref={jsonFile} type="file" accept="application/json,.json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload('/import/json', f); e.target.value = '' }} />
        <input ref={csvFile} type="file" accept=".csv,text/csv" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload('/import/questions', f); e.target.value = '' }} />
        <div className="flex flex-wrap gap-2">
          <button className="btn" onClick={() => download('/export/json', 'recall-export.json').catch(err)}>Export JSON (full backup)</button>
          <button className="btn" onClick={() => jsonFile.current?.click()}>Import JSON…</button>
          <button className="btn" onClick={() => download('/export/questions.csv', 'questions.csv').catch(err)}>Export questions CSV</button>
          <button className="btn" onClick={() => csvFile.current?.click()}>Import questions CSV…</button>
        </div>
        <p className="mt-3 text-xs text-muted">CSV columns: title, content, question_type, difficulty, answer, explanation, subject, topics (;-separated), tags (;-separated), source, options (|-separated, correct option prefixed with *). PDF and Word import are planned.</p>
      </Section>

      <Section title="Change password">
        <div className="grid gap-3 sm:grid-cols-2"><Field label="Current password"><input type="password" className="field" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" /></Field><Field label="New password" hint="At least 8 characters"><input type="password" className="field" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" /></Field></div>
        <Button className="mt-3" disabled={!cur || next.length < 8} loading={busy === 'pw'} onClick={changePw}>Change password</Button>
      </Section>
    </Page>
  )
}
