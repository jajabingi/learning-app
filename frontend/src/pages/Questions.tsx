import { useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Download, Sparkles, Upload } from 'lucide-react'
import { api, download } from '@/api/client'
import { QuestionTable } from '@/components/QuestionTable'
import { useQuickCreate } from '@/components/QuickCreate'
import { Menu, PageHeader } from '@/components/ui'
import { Page } from '@/components/Layout'
import { useToast } from '@/contexts/toast'

export default function QuestionsPage() {
  const [sp] = useSearchParams()
  const qc = useQuickCreate()
  const cache = useQueryClient()
  const toast = useToast()
  const file = useRef<HTMLInputElement>(null)

  async function importCsv(f: File) {
    const form = new FormData()
    form.append('file', f)
    try {
      const r = await api<{ created: number; error_count: number; errors: { row: number; message: string }[] }>('/import/questions', { form })
      cache.invalidateQueries()
      if (r.error_count) toast.err(`${r.created} imported, ${r.error_count} row(s) skipped — first: row ${r.errors[0].row}: ${r.errors[0].message}`)
      else toast.ok(`${r.created} questions imported`)
    } catch (e) {
      toast.err(e instanceof Error ? e.message : 'Import failed')
    }
  }

  return (
    <Page>
      <PageHeader
        title="Questions"
        subtitle="Your question bank — create, organise and filter everything you want to remember."
        actions={
          <>
            <input ref={file} type="file" accept=".csv,text/csv" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) importCsv(f); e.target.value = '' }} />
            <Menu label="Import and export" icon={<span className="flex items-center gap-1 px-2.5 text-sm font-medium">Import / export</span>} items={[
              { label: 'Import questions from CSV…', onClick: () => file.current?.click() },
              { label: 'Export questions as CSV', onClick: () => download('/export/questions.csv', 'questions.csv').catch((e) => toast.err(e.message)) },
              { label: 'Export everything as JSON', onClick: () => download('/export/json', 'recall-export.json').catch((e) => toast.err(e.message)) },
            ]} />
            <button className="btn" onClick={() => qc.open('ai')}><Sparkles size={14} /> Generate with AI</button>
            <button className="btn btn-primary" onClick={() => qc.open('question')}>New question</button>
          </>
        }
      />
      <QuestionTable initial={{ tag: sp.get('tag') ?? undefined, status: sp.get('status') ?? undefined, subject_id: sp.get('subject') ?? undefined }} />
    </Page>
  )
}
export { Download, Upload }
