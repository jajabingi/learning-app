import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, FolderTree, GraduationCap, Library as LibraryIcon, Menu as MenuIcon, Plus } from 'lucide-react'
import { del, patch, post } from '@/api/client'
import type { ChapterNode, CourseNode, SubjectNode, TopicNode } from '@/api/types'
import { useQuickCreate, SubjectForm } from '@/components/QuickCreate'
import { TopicPicker } from '@/components/TopicPicker'
import { Button, ConfirmDialog, Empty, ErrorState, Field, Loading, Menu, Modal, PageHeader, ProgressBar, Stat, cx } from '@/components/ui'
import { Page } from '@/components/Layout'
import { useTree } from '@/hooks/queries'
import { useToast } from '@/contexts/toast'
import { pct } from '@/lib/format'
import { Markdown } from '@/components/Markdown'
import TopicPage from './TopicPage'
import { tt } from '@/i18n'

type Kind = 'subject' | 'course' | 'chapter' | 'topic'

/* ---------- actions shared by tree and detail pages ---------- */
interface Actions {
  addCourse(subjectId: string): void
  addChapter(courseId: string): void
  edit(kind: Kind, id: string): void
  move(kind: Kind, id: string, dir: 'up' | 'down'): void
  archive(kind: Kind, id: string, archived: boolean): void
  remove(kind: Kind, id: string, name: string): void
  moveTopic(id: string): void
}
const ActionsCtx = createContext<Actions>(null as unknown as Actions)
export const useLibraryActions = () => useContext(ActionsCtx)
const PATHS: Record<Kind, string> = { subject: 'subjects', course: 'courses', chapter: 'chapters', topic: 'topics' }

function ActionsProvider({ children }: { children: ReactNode }) {
  const { data: tree = [] } = useTree(true)
  const qc = useQueryClient()
  const toast = useToast()
  const nav = useNavigate()
  const [dlg, setDlg] = useState<null | { t: 'addCourse' | 'addChapter'; parent: string } | { t: 'edit'; kind: Kind; id: string } | { t: 'delete'; kind: Kind; id: string; name: string } | { t: 'moveTopic'; id: string }>(null)
  const done = () => { qc.invalidateQueries(); setDlg(null) }
  const fail = (e: unknown) => toast.err(e instanceof Error ? e.message : tt("Failed"))

  const mv = useMutation({ mutationFn: (v: { kind: Kind; id: string; dir: string }) => post(`/${PATHS[v.kind]}/${v.id}/move`, { direction: v.dir }), onSuccess: () => qc.invalidateQueries(), onError: fail })
  const arch = useMutation({ mutationFn: (v: { kind: Kind; id: string; archived: boolean }) => patch(`/${PATHS[v.kind]}/${v.id}`, { archived: v.archived }), onSuccess: (_r, v) => { qc.invalidateQueries(); toast.ok(v.archived ? tt("Archived") : tt("Restored")) }, onError: fail })
  const rm = useMutation({ mutationFn: (v: { kind: Kind; id: string }) => del(`/${PATHS[v.kind]}/${v.id}`), onSuccess: () => { done(); toast.ok(tt("Deleted")); nav('/library') }, onError: fail })

  const actions: Actions = {
    addCourse: (p) => setDlg({ t: 'addCourse', parent: p }),
    addChapter: (p) => setDlg({ t: 'addChapter', parent: p }),
    edit: (kind, id) => setDlg({ t: 'edit', kind, id }),
    move: (kind, id, dir) => mv.mutate({ kind, id, dir }),
    archive: (kind, id, archived) => arch.mutate({ kind, id, archived }),
    remove: (kind, id, name) => setDlg({ t: 'delete', kind, id, name }),
    moveTopic: (id) => setDlg({ t: 'moveTopic', id }),
  }
  const find = (kind: Kind, id: string): { name: string; description: string } | undefined => {
    for (const s of tree) {
      if (kind === 'subject' && s.id === id) return s
      for (const c of s.courses) {
        if (kind === 'course' && c.id === id) return c
        for (const ch of c.chapters) if (kind === 'chapter' && ch.id === id) return ch
      }
    }
  }
  const warn: Record<Kind, string> = {
    subject: 'All courses, chapters and topics in this subject are deleted. Questions and notes are kept but become unfiled.',
    course: 'Its chapters are deleted. Topics inside move to the subject root; questions are kept.',
    chapter: 'Topics inside move to the subject root; questions are kept.',
    topic: 'Its subtopics are deleted. Questions are kept (they just lose the link to this topic).',
  }
  return (
    <ActionsCtx.Provider value={actions}>
      {children}
      {dlg && (dlg.t === 'addCourse' || dlg.t === 'addChapter') && <NameDialog title={dlg.t === 'addCourse' ? tt("New course") : tt("New chapter")} onClose={() => setDlg(null)} onSubmit={(v) => (dlg.t === 'addCourse' ? post('/courses', { ...v, subject_id: dlg.parent }) : post('/chapters', { ...v, course_id: dlg.parent })).then(done).catch(fail)} />}
      {dlg?.t === 'edit' && dlg.kind === 'subject' && (
        <Modal open onClose={() => setDlg(null)} title={tt("Edit subject")}><SubjectForm initial={tree.find((s) => s.id === dlg.id)} onDone={done} onCancel={() => setDlg(null)} /></Modal>
      )}
      {dlg?.t === 'edit' && dlg.kind !== 'subject' && <NameDialog title={tt("Edit {kind}", { kind: tt(dlg.kind) })} initial={find(dlg.kind, dlg.id)} onClose={() => setDlg(null)} onSubmit={(v) => patch(`/${PATHS[dlg.kind]}/${dlg.id}`, v).then(done).catch(fail)} />}
      {dlg?.t === 'moveTopic' && <MoveTopicDialog id={dlg.id} tree={tree} onClose={() => setDlg(null)} onDone={done} />}
      <ConfirmDialog open={dlg?.t === 'delete'} onClose={() => setDlg(null)} busy={rm.isPending} title={dlg?.t === 'delete' ? `Delete “${dlg.name}”?` : ''} message={dlg?.t === 'delete' ? <>{warn[dlg.kind]} {tt("This cannot be undone — consider archiving instead.")}</> : ''} onConfirm={() => dlg?.t === 'delete' && rm.mutate({ kind: dlg.kind, id: dlg.id })} />
    </ActionsCtx.Provider>
  )
}

function NameDialog({ title, initial, onClose, onSubmit }: { title: string; initial?: { name: string; description: string }; onClose(): void; onSubmit(v: { name: string; description: string }): void }) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  return (
    <Modal open onClose={onClose} title={title}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (name.trim()) onSubmit({ name, description }) }}>
        <Field label={tt("Name")}><input className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required autoFocus /></Field>
        <Field label={tt("Description")}><textarea className="field" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={5000} /></Field>
        <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onClose}>{tt("Cancel")}</button><Button type="submit" className="btn-primary">{tt("Save")}</Button></div>
      </form>
    </Modal>
  )
}

function MoveTopicDialog({ id, tree, onClose, onDone }: { id: string; tree: SubjectNode[]; onClose(): void; onDone(): void }) {
  const toast = useToast()
  const [subjectId, setSubjectId] = useState('')
  const [chapterId, setChapterId] = useState('')
  const [parent, setParent] = useState<string[]>([])
  const chapters = tree.find((s) => s.id === subjectId)?.courses.flatMap((c) => c.chapters.map((ch) => ({ id: ch.id, label: `${c.name} › ${ch.name}` }))) ?? []
  const go = () =>
    patch(`/topics/${id}`, parent[0] ? { move: true, parent_id: parent[0] } : { move: true, subject_id: subjectId, chapter_id: chapterId || null })
      .then(() => { toast.ok(tt("Topic moved")); onDone() })
      .catch((e) => toast.err(e.message))
  return (
    <Modal open onClose={onClose} title={tt("Move topic")} footer={<><button className="btn" onClick={onClose}>{tt("Cancel")}</button><button className="btn btn-primary" disabled={!parent[0] && !subjectId} onClick={go}>{tt("Move")}</button></>}>
      <div className="space-y-3">
        <div><span className="label">{tt("Make it a subtopic of…")}</span><TopicPicker single value={parent} onChange={setParent} /></div>
        {!parent[0] && (
          <>
            <p className="text-xs text-muted">{tt("…or place it in a subject:")}</p>
            <Field label={tt("Subject")}><select className="field" value={subjectId} onChange={(e) => { setSubjectId(e.target.value); setChapterId('') }}><option value="">{tt("Choose…")}</option>{tree.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
            {chapters.length > 0 && <Field label={tt("Chapter (optional)")}><select className="field" value={chapterId} onChange={(e) => setChapterId(e.target.value)}><option value="">{tt("— subject root —")}</option>{chapters.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</select></Field>}
          </>
        )}
      </div>
    </Modal>
  )
}

/* ---------- tree ---------- */
function useExpanded() {
  const [open, setOpen] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem('recall.tree') ?? '[]')) } catch { return new Set() }
  })
  const toggle = (id: string, force?: boolean) =>
    setOpen((s) => {
      const n = new Set(s)
      const on = force ?? !n.has(id)
      on ? n.add(id) : n.delete(id)
      try { localStorage.setItem('recall.tree', JSON.stringify([...n])) } catch { /* ignore */ }
      return n
    })
  return { open, toggle }
}

function Row({ to, depth, label, color, expandable, expanded, onToggle, muted, meta, menu }: { to: string; depth: number; label: string; color?: string; expandable: boolean; expanded: boolean; onToggle(): void; muted?: boolean; meta?: ReactNode; menu: React.ComponentProps<typeof Menu>['items'] }) {
  return (
    <div className="group flex items-center" style={{ paddingLeft: depth * 14 }}>
      <button className="flex h-7 w-6 shrink-0 items-center justify-center text-faint hover:text-fg" onClick={onToggle} aria-label={expanded ? tt("Collapse") : tt("Expand")} tabIndex={expandable ? 0 : -1} aria-hidden={!expandable}>
        {expandable ? (expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} className="rtl:rotate-180" />) : null}
      </button>
      <NavLink to={to} className={({ isActive }) => cx('flex h-7 min-w-0 flex-1 items-center gap-1.5 rounded px-1.5 text-sm', isActive ? 'bg-raised font-medium' : 'hover:bg-raised/70', muted && 'opacity-50')}>
        {color && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />}
        <span className="truncate">{label}</span>
        {meta}
      </NavLink>
      <div className="opacity-0 focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"><Menu items={menu} label={tt("Actions for {label}", { label: label })} /></div>
    </div>
  )
}

function TopicRows({ t, depth, ex }: { t: TopicNode; depth: number; ex: ReturnType<typeof useExpanded> }) {
  const a = useLibraryActions()
  const qc = useQuickCreate()
  const has = t.children.length > 0
  return (
    <>
      <Row to={`/library/topic/${t.id}`} depth={depth} label={t.name} expandable={has} expanded={ex.open.has(t.id)} onToggle={() => ex.toggle(t.id)} muted={t.archived}
        meta={<>{t.due > 0 && <span className="ml-auto rounded bg-accent/10 px-1 text-[11px] font-medium text-accent tabnum">{t.due}</span>}</>}
        menu={[
          { label: tt("Add subtopic"), onClick: () => { ex.toggle(t.id, true); qc.open('topic', { topic: { parent_id: t.id, subject_id: t.subject_id } }) } },
          { label: tt("Move…"), onClick: () => a.moveTopic(t.id) }, { label: tt("Move up"), onClick: () => a.move('topic', t.id, 'up') }, { label: tt("Move down"), onClick: () => a.move('topic', t.id, 'down') },
          { label: t.archived ? tt("Restore") : tt("Archive"), onClick: () => a.archive('topic', t.id, !t.archived) }, 'sep',
          { label: tt("Delete…"), danger: true, onClick: () => a.remove('topic', t.id, t.name) },
        ]} />
      {has && ex.open.has(t.id) && t.children.map((c) => <TopicRows key={c.id} t={c} depth={depth + 1} ex={ex} />)}
    </>
  )
}

function Tree() {
  const { data: tree, isLoading, error, refetch } = useTree(true)
  const ex = useExpanded()
  const a = useLibraryActions()
  const qc = useQuickCreate()
  const [showArchived, setShowArchived] = useState(false)
  if (isLoading) return <Loading />
  if (error) return <ErrorState error={error} retry={refetch} />
  const vis = <T extends { archived: boolean }>(x: T[]) => (showArchived ? x : x.filter((i) => !i.archived))
  const visTopics = (ts: TopicNode[]): TopicNode[] => vis(ts).map((t) => ({ ...t, children: visTopics(t.children) }))
  return (
    <div>
      <div className="mb-2 flex items-center justify-between px-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">{tt("Subjects")}</span>
        <button className="btn btn-ghost btn-icon h-6 w-6" aria-label={tt("New subject")} onClick={() => qc.open('subject')}><Plus size={14} /></button>
      </div>
      {vis(tree!).map((s) => (
        <div key={s.id}>
          <Row to={`/library/subject/${s.id}`} depth={0} label={s.name} color={s.color} expandable={s.courses.length + s.topics.length > 0} expanded={ex.open.has(s.id)} onToggle={() => ex.toggle(s.id)} muted={s.archived}
            menu={[
              { label: tt("Add course"), onClick: () => { ex.toggle(s.id, true); a.addCourse(s.id) } },
              { label: tt("Add topic"), onClick: () => { ex.toggle(s.id, true); qc.open('topic', { topic: { subject_id: s.id } }) } },
              { label: tt("Edit…"), onClick: () => a.edit('subject', s.id) }, { label: tt("Move up"), onClick: () => a.move('subject', s.id, 'up') }, { label: tt("Move down"), onClick: () => a.move('subject', s.id, 'down') },
              { label: s.archived ? tt("Restore") : tt("Archive"), onClick: () => a.archive('subject', s.id, !s.archived) }, 'sep',
              { label: tt("Delete…"), danger: true, onClick: () => a.remove('subject', s.id, s.name) },
            ]} />
          {ex.open.has(s.id) && (
            <>
              {vis(s.courses).map((c) => (
                <div key={c.id}>
                  <Row to={`/library/course/${c.id}`} depth={1} label={c.name} expandable={c.chapters.length > 0} expanded={ex.open.has(c.id)} onToggle={() => ex.toggle(c.id)} muted={c.archived}
                    meta={<GraduationCap size={11} className="ml-1 shrink-0 text-faint" />}
                    menu={[
                      { label: tt("Add chapter"), onClick: () => { ex.toggle(c.id, true); a.addChapter(c.id) } }, { label: tt("Edit…"), onClick: () => a.edit('course', c.id) },
                      { label: tt("Move up"), onClick: () => a.move('course', c.id, 'up') }, { label: tt("Move down"), onClick: () => a.move('course', c.id, 'down') },
                      { label: c.archived ? tt("Restore") : tt("Archive"), onClick: () => a.archive('course', c.id, !c.archived) }, 'sep',
                      { label: tt("Delete…"), danger: true, onClick: () => a.remove('course', c.id, c.name) },
                    ]} />
                  {ex.open.has(c.id) && vis(c.chapters).map((ch) => (
                    <div key={ch.id}>
                      <Row to={`/library/chapter/${ch.id}`} depth={2} label={ch.name} expandable={ch.topics.length > 0} expanded={ex.open.has(ch.id)} onToggle={() => ex.toggle(ch.id)} muted={ch.archived}
                        menu={[
                          { label: tt("Add topic"), onClick: () => { ex.toggle(ch.id, true); qc.open('topic', { topic: { subject_id: s.id, chapter_id: ch.id } }) } }, { label: tt("Edit…"), onClick: () => a.edit('chapter', ch.id) },
                          { label: tt("Move up"), onClick: () => a.move('chapter', ch.id, 'up') }, { label: tt("Move down"), onClick: () => a.move('chapter', ch.id, 'down') },
                          { label: ch.archived ? tt("Restore") : tt("Archive"), onClick: () => a.archive('chapter', ch.id, !ch.archived) }, 'sep',
                          { label: tt("Delete…"), danger: true, onClick: () => a.remove('chapter', ch.id, ch.name) },
                        ]} />
                      {ex.open.has(ch.id) && visTopics(ch.topics).map((t) => <TopicRows key={t.id} t={t} depth={3} ex={ex} />)}
                    </div>
                  ))}
                </div>
              ))}
              {visTopics(s.topics).map((t) => <TopicRows key={t.id} t={t} depth={1} ex={ex} />)}
            </>
          )}
        </div>
      ))}
      {tree!.length === 0 && <p className="px-2 py-4 text-sm text-muted">{tt("No subjects yet.")}</p>}
      <label className="mt-3 flex items-center gap-2 px-2 text-xs text-muted"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> {tt("Show archived")}</label>
    </div>
  )
}

/* ---------- overview + container pages ---------- */
function Overview() {
  const { data: tree = [], isLoading } = useTree()
  const qc = useQuickCreate()
  if (isLoading) return <Loading />
  return (
    <Page>
      <PageHeader title={tt("Knowledge Library")} subtitle={tt("Subjects → courses → chapters → topics → subtopics. Organise knowledge your way; reorganise any time.")} actions={<button className="btn btn-primary" onClick={() => qc.open('subject')}>{tt("New subject")}</button>} />
      {tree.length === 0 ? (
        <div className="card"><Empty title={tt("Start by creating a subject")} icon={<LibraryIcon size={28} />} action={<button className="btn btn-primary" onClick={() => qc.open('subject')}>{tt("Create subject")}</button>}>{tt("Subjects hold your courses, topics, notes and questions — e.g. “Finance”, “History” or “Mathematics”.")}</Empty></div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {tree.map((s) => (
            <Link key={s.id} to={`/library/subject/${s.id}`} className="card block p-4 hover:border-faint">
              <div className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: s.color }} /><span className="truncate font-medium">{s.name}</span></div>
              <p className="mt-1 line-clamp-2 min-h-10 text-sm text-muted">{s.description || tt("No description")}</p>
              <ProgressBar value={s.mastery} className="mt-3" label={tt("{name} mastery", { name: s.name })} />
              <div className="mt-2 flex justify-between text-xs text-muted tabnum"><span>{s.topic_count} {tt("topics ·")} {s.question_count} {tt("questions")}</span><span>{pct(s.mastery)} {tt("mastery")}</span></div>
            </Link>
          ))}
        </div>
      )}
    </Page>
  )
}

function TopicLinks({ topics }: { topics: TopicNode[] }) {
  if (!topics.length) return <p className="px-3 py-4 text-sm text-muted">{tt("No topics here yet.")}</p>
  return (
    <ul className="divide-y divide-line">
      {topics.map((t) => (
        <li key={t.id}><Link to={`/library/topic/${t.id}`} className="flex items-center gap-3 px-3 py-2.5 hover:bg-raised/60">
          <FolderTree size={14} className="shrink-0 text-faint" /><span className="min-w-0 flex-1 truncate text-sm font-medium">{t.name}</span>
          {t.due > 0 && <span className="rounded bg-accent/10 px-1.5 text-xs font-medium text-accent">{t.due} {tt("due")}</span>}
          <span className="w-16 text-end text-xs text-muted tabnum">{t.question_count} Q</span><div className="w-20"><ProgressBar value={t.mastery} label={tt("Mastery")} /></div>
        </Link></li>
      ))}
    </ul>
  )
}

function ContainerPage({ kind }: { kind: 'subject' | 'course' | 'chapter' }) {
  const { id = '' } = useParams()
  const { data: tree = [], isLoading } = useTree(true)
  const a = useLibraryActions()
  const qc = useQuickCreate()
  const nav = useNavigate()
  const found = useMemo(() => {
    for (const s of tree) {
      if (kind === 'subject' && s.id === id) return { subject: s, node: s as SubjectNode | CourseNode | ChapterNode }
      for (const c of s.courses) {
        if (kind === 'course' && c.id === id) return { subject: s, node: c }
        for (const ch of c.chapters) if (kind === 'chapter' && ch.id === id) return { subject: s, node: ch, course: c }
      }
    }
  }, [tree, id, kind])
  if (isLoading) return <Loading />
  if (!found) return <Page><Empty title={tt("Not found")} action={<Link className="btn" to="/library">{tt("Back to library")}</Link>} /></Page>
  const { subject, node } = found
  const s = subject
  return (
    <Page>
      <div className="mb-1 flex items-center gap-1 text-xs text-muted">
        <Link to="/library" className="hover:text-fg">{tt("Library")}</Link>
        {kind !== 'subject' && <><span>/</span><Link to={`/library/subject/${s.id}`} className="hover:text-fg">{s.name}</Link></>}
        {kind === 'chapter' && 'course' in found && found.course && <><span>/</span><Link to={`/library/course/${found.course.id}`} className="hover:text-fg">{found.course.name}</Link></>}
      </div>
      <PageHeader title={<span className="flex items-center gap-2">{kind === 'subject' && <span className="h-3 w-3 rounded-full" style={{ background: s.color }} />}{node.name}{node.archived && <span className="text-sm font-normal text-muted">{tt("(archived)")}</span>}</span>}
        actions={<>
          {kind === 'subject' && <><button className="btn" onClick={() => a.addCourse(id)}>{tt("Add course")}</button><button className="btn" onClick={() => qc.open('topic', { topic: { subject_id: id } })}>{tt("Add topic")}</button><button className="btn btn-primary" onClick={() => nav(`/study?subject=${id}`)}>{tt("Study subject")}</button></>}
          {kind === 'course' && <button className="btn" onClick={() => a.addChapter(id)}>{tt("Add chapter")}</button>}
          {kind === 'chapter' && <button className="btn" onClick={() => qc.open('topic', { topic: { subject_id: s.id, chapter_id: id } })}>{tt("Add topic")}</button>}
          <Menu items={[{ label: tt("Edit…"), onClick: () => a.edit(kind, id) }, { label: node.archived ? tt("Restore") : tt("Archive"), onClick: () => a.archive(kind, id, !node.archived) }, 'sep', { label: tt("Delete…"), danger: true, onClick: () => a.remove(kind, id, node.name) }]} />
        </>} />
      {node.description && <div className="card mb-5 p-4"><Markdown>{node.description}</Markdown></div>}
      {kind === 'subject' && (
        <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label={tt("Topics")} value={s.topic_count} /><Stat label={tt("Questions")} value={s.question_count} /><Stat label={tt("Mastery")} value={pct(s.mastery)} /><Stat label={tt("Due now")} value={s.due} tone={s.due ? 'warn' : undefined} />
        </div>
      )}
      {kind === 'subject' && (
        <section className="mb-5">
          <h2 className="h-section mb-2">{tt("Courses")}</h2>
          {(node as SubjectNode).courses.length === 0 ? <p className="text-sm text-muted">{tt("No courses. Courses are optional — topics can live directly under the subject.")}</p> : (
            <div className="card divide-y divide-line">{(node as SubjectNode).courses.filter((c) => !c.archived).map((c) => <Link key={c.id} to={`/library/course/${c.id}`} className="flex items-center gap-2 px-3 py-2.5 text-sm font-medium hover:bg-raised/60"><GraduationCap size={14} className="text-faint" />{c.name}<span className="ml-auto text-xs font-normal text-muted">{c.chapters.length} {tt("chapters")}</span></Link>)}</div>
          )}
        </section>
      )}
      {kind === 'course' && (
        <section><h2 className="h-section mb-2">{tt("Chapters")}</h2>
          {(node as CourseNode).chapters.length === 0 ? <p className="text-sm text-muted">{tt("No chapters yet.")}</p> : <div className="space-y-3">{(node as CourseNode).chapters.filter((c) => !c.archived).map((ch) => <div key={ch.id} className="card"><Link to={`/library/chapter/${ch.id}`} className="block border-b border-line px-3 py-2 text-sm font-medium hover:bg-raised/60">{ch.name}</Link><TopicLinks topics={ch.topics.filter((t) => !t.archived)} /></div>)}</div>}
        </section>
      )}
      {kind === 'chapter' && <section><h2 className="h-section mb-2">{tt("Topics")}</h2><div className="card"><TopicLinks topics={(node as ChapterNode).topics.filter((t) => !t.archived)} /></div></section>}
      {kind === 'subject' && <section><h2 className="h-section mb-2">{tt("Topics")}</h2><div className="card"><TopicLinks topics={(node as SubjectNode).topics.filter((t) => !t.archived)} /></div></section>}
    </Page>
  )
}

export default function LibraryPage() {
  const [navOpen, setNavOpen] = useState(false)
  const nav = useNavigate()
  useEffect(() => { /* close the mobile tree after navigating */ }, [nav])
  return (
    <ActionsProvider>
      <div className="flex h-full">
        <aside className="hidden w-72 shrink-0 overflow-y-auto border-e border-line bg-surface p-3 md:block"><Tree /></aside>
        {navOpen && (
          <div className="fixed inset-0 z-30 md:hidden"><div className="absolute inset-0 bg-black/40" onClick={() => setNavOpen(false)} /><aside className="absolute inset-y-0 start-0 w-80 max-w-[88%] overflow-y-auto bg-surface p-3 shadow-xl" onClick={(e) => (e.target as HTMLElement).closest('a') && setNavOpen(false)}><Tree /></aside></div>
        )}
        <div className="min-w-0 flex-1 overflow-y-auto">
          <button className="btn m-3 mb-0 md:hidden" onClick={() => setNavOpen(true)}><MenuIcon size={14} /> {tt("Browse library")}</button>
          <Routes>
            <Route index element={<Overview />} />
            <Route path="subject/:id" element={<ContainerPage kind="subject" />} />
            <Route path="course/:id" element={<ContainerPage kind="course" />} />
            <Route path="chapter/:id" element={<ContainerPage kind="chapter" />} />
            <Route path="topic/:id" element={<TopicPage />} />
          </Routes>
        </div>
      </div>
    </ActionsProvider>
  )
}
