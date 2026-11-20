import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, useEdgesState, useNodesState, useReactFlow, type Connection, type Edge, type Node, type NodeProps } from '@xyflow/react'
import dagre from '@dagrejs/dagre'
import '@xyflow/react/dist/style.css'
import { Trash2, X } from 'lucide-react'
import { del, get, post } from '@/api/client'
import { RELATIONS, type GraphData } from '@/api/types'
import { TopicPicker } from '@/components/TopicPicker'
import { Button, Empty, ErrorState, Loading, Modal, PageHeader, ProgressBar, cx } from '@/components/ui'
import { useTree } from '@/hooks/queries'
import { useTheme } from '@/contexts/theme'
import { useToast } from '@/contexts/toast'
import { pct } from '@/lib/format'
import { tt } from '@/i18n'

type GNode = GraphData['nodes'][number]
type TNodeData = { n: GNode; weak: boolean; dim: boolean; selected: boolean }

const REL_STYLE: Record<string, { color: string; dash?: string; arrow: boolean; label: string }> = {
  prerequisite_for: { color: 'rgb(var(--accent))', arrow: true, label: tt("prerequisite for") },
  depends_on: { color: 'rgb(var(--accent))', dash: '2 3', arrow: true, label: tt("depends on") },
  part_of: { color: 'rgb(var(--muted))', arrow: true, label: tt("part of") },
  applied_in: { color: 'rgb(var(--good))', dash: '6 3', arrow: true, label: tt("applied in") },
  contrasts_with: { color: 'rgb(var(--bad))', dash: '6 3', arrow: false, label: tt("contrasts with") },
  related_to: { color: 'rgb(var(--faint))', dash: '4 4', arrow: false, label: tt("related to") },
}
const WEAK = 0.35
const tone = (m: number) => (m >= 0.7 ? 'bg-good' : m >= WEAK ? 'bg-warn' : 'bg-bad')

function TopicNode({ data }: NodeProps<Node<TNodeData>>) {
  const { n, weak, dim, selected } = data
  return (
    <div className={cx('w-44 rounded-lg border bg-surface px-3 py-2 shadow-sm', selected ? 'border-accent ring-2 ring-accent/40' : weak ? 'border-bad/60' : 'border-line', dim && 'opacity-30')}>
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-line !bg-faint" />
      <div className="flex items-center gap-1.5"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: n.color }} /><span className="truncate text-sm font-medium" title={n.name}>{n.name}</span></div>
      <div className="mt-1.5 flex items-center gap-2"><div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised"><div className={cx('h-full', tone(n.mastery))} style={{ width: `${Math.max(n.mastery * 100, n.questions ? 3 : 0)}%` }} /></div><span className="text-[11px] text-muted tabnum">{n.questions ? pct(n.mastery) : tt("no Q")}</span></div>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-line !bg-faint" />
    </div>
  )
}
const nodeTypes = { topic: TopicNode }

function layout(nodes: GNode[], edges: GraphData['edges']) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 28, ranksep: 90 })
  g.setDefaultEdgeLabel(() => ({}))
  nodes.forEach((n) => g.setNode(n.id, { width: 176, height: 62 }))
  // Prerequisites flow left → right: for "depends_on" the target is the prerequisite.
  edges.forEach((e) => (e.relation_type === 'depends_on' ? g.setEdge(e.target_topic_id, e.source_topic_id) : g.setEdge(e.source_topic_id, e.target_topic_id)))
  dagre.layout(g)
  return Object.fromEntries(nodes.map((n) => { const p = g.node(n.id); return [n.id, { x: p.x - 88, y: p.y - 31 }] }))
}

function GraphInner() {
  const { dark } = useTheme()
  const qc = useQueryClient()
  const toast = useToast()
  const rf = useReactFlow()
  const { data: tree = [] } = useTree()
  const [subject, setSubject] = useState('')
  const [weakOnly, setWeakOnly] = useState(false)
  const [sel, setSel] = useState<{ kind: 'node' | 'edge'; id: string } | null>(null)
  const [pendingConn, setPendingConn] = useState<Connection | null>(null)
  const [relType, setRelType] = useState('prerequisite_for')
  const [addA, setAddA] = useState<string[]>([])
  const [addB, setAddB] = useState<string[]>([])
  const [addType, setAddType] = useState('prerequisite_for')
  const [showAdd, setShowAdd] = useState(false)

  const g = useQuery({ queryKey: ['graph', subject], queryFn: () => get<GraphData>('/graph', { subject_id: subject }) })
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<TNodeData>>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  const byId = useMemo(() => new Map((g.data?.nodes ?? []).map((n) => [n.id, n])), [g.data])

  useEffect(() => {
    if (!g.data) return
    const pos = layout(g.data.nodes, g.data.edges)
    setNodes(g.data.nodes.map((n) => ({ id: n.id, type: 'topic', position: pos[n.id], data: { n, weak: n.questions > 0 && n.mastery < WEAK, dim: false, selected: false } })))
    setEdges(g.data.edges.map((e) => {
      const s = REL_STYLE[e.relation_type] ?? REL_STYLE.related_to
      return { id: e.id, source: e.source_topic_id, target: e.target_topic_id, label: s.label, labelStyle: { fontSize: 10, fill: 'rgb(var(--muted))' }, labelBgStyle: { fill: 'rgb(var(--surface))' }, style: { stroke: s.color, strokeWidth: 1.6, strokeDasharray: s.dash },
        markerEnd: s.arrow ? { type: MarkerType.ArrowClosed, color: s.color } : undefined, interactionWidth: 18 }
    }))
    setTimeout(() => rf.fitView({ padding: 0.2, duration: 250 }), 30)
  }, [g.data]) // eslint-disable-line react-hooks/exhaustive-deps

  // selection / weak highlighting without recomputing layout
  useEffect(() => {
    setNodes((ns) => ns.map((n) => ({ ...n, data: { ...n.data, selected: sel?.kind === 'node' && sel.id === n.id, dim: weakOnly && !n.data.weak } })))
    setEdges((es) => es.map((e) => ({ ...e, selected: sel?.kind === 'edge' && sel.id === e.id, animated: sel?.kind === 'edge' && sel.id === e.id })))
  }, [sel, weakOnly]) // eslint-disable-line react-hooks/exhaustive-deps

  const add = useMutation({
    mutationFn: (v: { s: string; t: string; type: string }) => post('/relationships', { source_topic_id: v.s, target_topic_id: v.t, relation_type: v.type }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['graph'] }); qc.invalidateQueries({ queryKey: ['topic'] }); toast.ok(tt("Relationship created")); setPendingConn(null); setAddA([]); setAddB([]) },
    onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")),
  })
  const rm = useMutation({ mutationFn: (id: string) => del(`/relationships/${id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ['graph'] }); qc.invalidateQueries({ queryKey: ['topic'] }); setSel(null); toast.ok(tt("Relationship removed")) }, onError: (e) => toast.err(e instanceof Error ? e.message : tt("Failed")) })

  const onConnect = useCallback((c: Connection) => { if (c.source && c.target && c.source !== c.target) setPendingConn(c) }, [])
  const data = g.data
  const selNode = sel?.kind === 'node' ? byId.get(sel.id) : undefined
  const selEdge = sel?.kind === 'edge' ? data?.edges.find((e) => e.id === sel.id) : undefined
  const nodeEdges = selNode ? data!.edges.filter((e) => e.source_topic_id === selNode.id || e.target_topic_id === selNode.id) : []
  // prerequisites of the selected node: sources of prerequisite_for → node, or targets of node depends_on
  const prereqs = selNode ? nodeEdges.flatMap((e) => (e.relation_type === 'prerequisite_for' && e.target_topic_id === selNode.id ? [byId.get(e.source_topic_id)] : e.relation_type === 'depends_on' && e.source_topic_id === selNode.id ? [byId.get(e.target_topic_id)] : [])).filter((x): x is GNode => !!x) : []

  if (g.isLoading) return <Loading />
  if (g.error || !data) return <ErrorState error={g.error} retry={g.refetch} />
  const weakCount = data.nodes.filter((n) => n.questions > 0 && n.mastery < WEAK).length

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 px-4 pt-5 sm:px-6">
        <PageHeader title={tt("Knowledge Graph")} subtitle={tt("Connect topics, see prerequisites, and spot weak links. Drag from a node’s right edge to another node to relate them.")}
          actions={<>
            <select className="field h-8 w-auto py-0" value={subject} onChange={(e) => { setSubject(e.target.value); setSel(null) }} aria-label={tt("Filter by subject")}><option value="">{tt("All subjects")}</option>{tree.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
            <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={weakOnly} onChange={(e) => setWeakOnly(e.target.checked)} /> {tt("Highlight weak (")}{weakCount})</label>
            <button className="btn btn-primary" onClick={() => setShowAdd(true)}>{tt("Add relationship")}</button>
          </>} />
      </div>
      {data.nodes.length === 0 ? <div className="card mx-4 sm:mx-6"><Empty title={tt("No topics to show")}>{tt("Create topics in the Library, then connect them here.")}</Empty></div> : (
        <div className="relative mx-4 mb-4 min-h-0 flex-1 overflow-hidden rounded-lg border border-line sm:mx-6">
          <div dir="ltr" className="absolute inset-0"><ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} nodeTypes={nodeTypes} onConnect={onConnect} colorMode={dark ? 'dark' : 'light'} fitView minZoom={0.2} maxZoom={1.8} nodesConnectable
            onNodeClick={(_, n) => setSel({ kind: 'node', id: n.id })} onEdgeClick={(_, e) => setSel({ kind: 'edge', id: e.id })} onPaneClick={() => setSel(null)} deleteKeyCode={null} proOptions={{ hideAttribution: true }}>
            <Background gap={20} color="rgb(var(--line))" /><Controls showInteractive={false} /><MiniMap pannable zoomable className="!hidden md:!block" nodeColor={(n) => ((n.data as TNodeData).weak ? 'rgb(var(--bad))' : 'rgb(var(--faint))')} />
          </ReactFlow></div>
          <div className="pointer-events-none absolute bottom-2 end-12 hidden flex-wrap gap-x-3 gap-y-1 rounded border border-line bg-surface/90 px-2 py-1 text-[11px] text-muted md:flex">
            {['prerequisite_for', 'part_of', 'applied_in', 'contrasts_with', 'related_to'].map((k) => <span key={k} className="inline-flex items-center gap-1"><svg width="18" height="6"><line x1="0" y1="3" x2="18" y2="3" stroke={REL_STYLE[k].color} strokeWidth="2" strokeDasharray={REL_STYLE[k].dash} /></svg>{REL_STYLE[k].label}</span>)}
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-bad" />{tt("weak <35%")}</span><span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-warn" />{tt("developing")}</span><span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-good" />{tt("strong ≥70%")}</span>
          </div>

          {(selNode || selEdge) && (
            <aside className="absolute inset-x-2 bottom-2 z-10 max-h-[60%] overflow-y-auto rounded-lg border border-line bg-surface p-4 shadow-lg sm:inset-x-auto sm:bottom-auto sm:right-3 sm:top-3 sm:max-h-[calc(100%-1.5rem)] sm:w-72" aria-label={tt("Details")}>
              <button className="btn btn-ghost btn-icon absolute end-1.5 top-1.5 h-7 w-7" onClick={() => setSel(null)} aria-label={tt("Close details")}><X size={14} /></button>
              {selNode && (
                <div className="space-y-3">
                  <div><h2 className="pr-6 font-semibold">{selNode.name}</h2><p className="text-xs text-muted">{selNode.subject_name}</p></div>
                  <div><div className="mb-1 flex justify-between text-xs text-muted"><span>{tt("Mastery")}</span><span className="tabnum">{selNode.questions ? pct(selNode.mastery) : tt("no questions")}</span></div><ProgressBar value={selNode.mastery} label={tt("Mastery")} /></div>
                  <div className="grid grid-cols-3 gap-2 text-center text-xs"><div className="rounded bg-raised p-1.5"><div className="font-semibold tabnum">{selNode.questions}</div>{tt("questions")}</div><div className="rounded bg-raised p-1.5"><div className="font-semibold tabnum">{pct(selNode.accuracy)}</div>{tt("accuracy")}</div><div className="rounded bg-raised p-1.5"><div className="font-semibold tabnum">{selNode.due}</div>{tt("due")}</div></div>
                  {prereqs.length > 0 && (
                    <div><h3 className="h-section mb-1">{tt("Prerequisites")}</h3><ul className="space-y-1 text-sm">{prereqs.map((p) => <li key={p.id} className="flex items-center justify-between gap-2"><button className="truncate text-start text-accent underline" onClick={() => { setSel({ kind: 'node', id: p.id }); rf.fitView({ nodes: [{ id: p.id }], duration: 300, maxZoom: 1.2 }) }}>{p.name}</button><span className={cx('text-xs tabnum', p.questions && p.mastery < WEAK ? 'font-medium text-bad' : 'text-muted')}>{p.questions ? pct(p.mastery) : '—'}</span></li>)}</ul>
                      {prereqs.some((p) => p.questions && p.mastery < WEAK) && <p className="mt-1 text-xs text-warn">{tt("A prerequisite is weak — review it first.")}</p>}</div>
                  )}
                  {nodeEdges.length > 0 && (
                    <div><h3 className="h-section mb-1">{tt("Connections")}</h3><ul className="space-y-1 text-xs">{nodeEdges.map((e) => { const out = e.source_topic_id === selNode.id; const o = byId.get(out ? e.target_topic_id : e.source_topic_id); return <li key={e.id} className="flex items-center justify-between gap-2"><span className="min-w-0 truncate">{out ? '→' : '←'} <span className="text-muted">{REL_STYLE[e.relation_type]?.label}</span> {o?.name}</span><button className="text-faint hover:text-bad" aria-label={tt("Remove relationship")} onClick={() => rm.mutate(e.id)}><Trash2 size={12} /></button></li> })}</ul></div>
                  )}
                  <div className="flex flex-wrap gap-2 pt-1"><Link className="btn btn-primary" to={`/library/topic/${selNode.id}`}>{tt("Open topic")}</Link><Link className={cx('btn', !selNode.questions && 'pointer-events-none opacity-50')} to={`/study?topic=${selNode.id}`}>{tt("Study")}</Link></div>
                </div>
              )}
              {selEdge && (
                <div className="space-y-3"><h2 className="pr-6 font-semibold">{tt("Relationship")}</h2>
                  <p className="text-sm"><b>{byId.get(selEdge.source_topic_id)?.name}</b> <span className="text-muted">{REL_STYLE[selEdge.relation_type]?.label}</span> <b>{byId.get(selEdge.target_topic_id)?.name}</b></p>
                  <Button className="btn-danger" loading={rm.isPending} onClick={() => rm.mutate(selEdge.id)}><Trash2 size={14} /> {tt("Remove relationship")}</Button></div>
              )}
            </aside>
          )}
        </div>
      )}

      <Modal open={!!pendingConn} onClose={() => setPendingConn(null)} title={tt("Create relationship")} footer={<><button className="btn" onClick={() => setPendingConn(null)}>{tt("Cancel")}</button><Button className="btn-primary" loading={add.isPending} onClick={() => add.mutate({ s: pendingConn!.source!, t: pendingConn!.target!, type: relType })}>{tt("Create")}</Button></>}>
        {pendingConn && <div className="space-y-3 text-sm"><p><b>{byId.get(pendingConn.source!)?.name}</b> → <b>{byId.get(pendingConn.target!)?.name}</b></p><select className="field" value={relType} onChange={(e) => setRelType(e.target.value)} aria-label={tt("Relationship type")}>{RELATIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select></div>}
      </Modal>
      <Modal open={showAdd} onClose={() => setShowAdd(false)} title={tt("Add relationship")} footer={<><button className="btn" onClick={() => setShowAdd(false)}>{tt("Cancel")}</button><Button className="btn-primary" disabled={!addA[0] || !addB[0]} loading={add.isPending} onClick={() => add.mutate({ s: addA[0], t: addB[0], type: addType }, { onSuccess: () => setShowAdd(false) })}>{tt("Create")}</Button></>}>
        <div className="space-y-3"><div><span className="label">{tt("From topic")}</span><TopicPicker single value={addA} onChange={setAddA} /></div><select className="field" value={addType} onChange={(e) => setAddType(e.target.value)} aria-label={tt("Relationship type")}>{RELATIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select><div><span className="label">{tt("To topic")}</span><TopicPicker single value={addB} onChange={setAddB} /></div></div>
      </Modal>
    </div>
  )
}

export default function GraphPage() {
  return <ReactFlowProvider><GraphInner /></ReactFlowProvider>
}
