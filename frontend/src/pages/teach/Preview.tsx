import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Eye } from 'lucide-react'
import { get } from '@/api/client'
import type { ModuleNode } from '@/api/types'
import { CourseViewer } from '@/components/lms/CourseViewer'
import { Page } from '@/components/Layout'
import { ErrorState, Loading } from '@/components/ui'

export default function CoursePreview() {
  const { id = '' } = useParams()
  const [drafts, setDrafts] = useState(true)
  const q = useQuery({ queryKey: ['teach-preview', id, drafts], queryFn: () => get<{ title: string; curriculum: ModuleNode[]; status: string } & Record<string, any>>(`/teach/courses/${id}/preview`, { include_drafts: drafts }) })
  return (
    <Page>
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-warn/40 bg-warn/10 px-4 py-2.5 text-sm">
        <Eye size={15} className="text-warn" /><span className="font-medium">Student preview</span>
        <span className="text-muted">Nothing here is tracked or saved.</span>
        <label className="ml-auto flex items-center gap-1.5"><input type="checkbox" checked={drafts} onChange={(e) => setDrafts(e.target.checked)} /> Include unpublished modules &amp; lessons</label>
        <Link className="btn" to={`/teach/courses/${id}`}>Back to editor</Link>
      </div>
      {q.isLoading ? <Loading /> : q.error || !q.data ? <ErrorState error={q.error} retry={q.refetch} /> : (
        <CourseViewer key={String(drafts)} course={q.data as never} showDraftFlags={drafts} lessonPath={(lid) => `/teach/lessons/${lid}/preview`} />
      )}
    </Page>
  )
}
