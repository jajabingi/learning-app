import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-react'
import { patch, post } from '@/api/client'
import { QUESTION_TYPES, type Difficulty, type Question, type QuestionDraft, type QuestionType } from '@/api/types'
import { useTags, useTree } from '@/hooks/queries'
import { useToast } from '@/contexts/toast'
import { MarkdownEditor } from './MarkdownEditor'
import { TopicPicker } from './TopicPicker'
import { Button, Field, TagInput, cx } from './ui'

type Opt = { text: string; is_correct: boolean }

export function QuestionForm({ initial, defaults, onSaved, onCancel, saveLabel }: { initial?: Question; defaults?: Partial<QuestionDraft>; onSaved?(q: Question): void; onCancel?(): void; saveLabel?: string }) {
  const toast = useToast()
  const qc = useQueryClient()
  const { data: tree = [] } = useTree()
  const { data: tags = [] } = useTags()
  const [title, setTitle] = useState(initial?.title ?? defaults?.title ?? '')
  const [content, setContent] = useState(initial?.content ?? defaults?.content ?? '')
  const [answer, setAnswer] = useState(initial?.answer.answer ?? defaults?.answer?.answer ?? '')
  const [explanation, setExplanation] = useState(initial?.answer.explanation ?? defaults?.answer?.explanation ?? '')
  const [type, setType] = useState<QuestionType>(initial?.question_type ?? defaults?.question_type ?? 'open_ended')
  const [difficulty, setDifficulty] = useState<Difficulty>(initial?.difficulty ?? defaults?.difficulty ?? 'medium')
  const [subjectId, setSubjectId] = useState<string>(initial?.subject_id ?? defaults?.subject_id ?? '')
  const [topicIds, setTopicIds] = useState<string[]>(initial?.topics.map((t) => t.id) ?? defaults?.topic_ids ?? [])
  const [tagNames, setTagNames] = useState<string[]>(initial?.tags.map((t) => t.name) ?? defaults?.tags ?? [])
  const [source, setSource] = useState(initial?.source ?? defaults?.source ?? '')
  const [options, setOptions] = useState<Opt[]>(initial?.options.map((o) => ({ text: o.text, is_correct: o.is_correct })) ?? defaults?.options ?? [])
  const [more, setMore] = useState(!!(initial || defaults?.options?.length))
  const [error, setError] = useState('')

  const hasOptions = type === 'multiple_choice' || type === 'true_false'
  const effOptions: Opt[] =
    type === 'true_false'
      ? [{ text: 'True', is_correct: options.find((o) => o.text === 'True')?.is_correct ?? false }, { text: 'False', is_correct: options.find((o) => o.text === 'False')?.is_correct ?? false }]
      : options

  function changeType(t: QuestionType) {
    setType(t)
    if (t === 'multiple_choice' && options.length < 2) setOptions([{ text: '', is_correct: true }, { text: '', is_correct: false }, { text: '', is_correct: false }])
    if (t === 'true_false') setOptions([{ text: 'True', is_correct: true }, { text: 'False', is_correct: false }])
  }

  const save = useMutation({
    mutationFn: async () => {
      const opts = hasOptions ? effOptions.filter((o) => o.text.trim()) : []
      if (hasOptions && !opts.some((o) => o.is_correct)) throw new Error('Mark at least one option as correct')
      if (!title.trim() && !content.trim()) throw new Error('Add a title or the question text')
      const body = {
        title, content, question_type: type, difficulty, source,
        topic_ids: topicIds, tags: tagNames,
        answer: { answer, explanation }, options: opts,
      }
      if (initial) return patch<Question>(`/questions/${initial.id}`, { ...body, set_subject: true, subject_id: subjectId || null })
      return post<Question>('/questions', { ...body, subject_id: subjectId || null })
    },
    onSuccess: (q) => {
      qc.invalidateQueries()
      toast.ok(initial ? 'Question saved' : 'Question created')
      onSaved?.(q)
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Could not save'),
  })

  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); setError(''); save.mutate() }}>
      <Field label="Title (optional)">
        <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} placeholder="Short label, e.g. “Definition of variance”" autoFocus={!initial} />
      </Field>
      <div>
        <span className="label">Question</span>
        <MarkdownEditor value={content} onChange={setContent} label="Question" minRows={5} attach={initial ? { question_id: initial.id } : undefined} />
      </div>

      {hasOptions && (
        <div>
          <span className="label">{type === 'true_false' ? 'Correct value' : 'Answer options'}</span>
          <div className="space-y-1.5">
            {effOptions.map((o, i) => (
              <div key={i} className="flex items-center gap-2">
                <input type={type === 'true_false' ? 'radio' : 'checkbox'} name="correct" checked={o.is_correct} aria-label={`Option ${i + 1} is correct`}
                  onChange={() => setOptions(effOptions.map((x, j) => (type === 'true_false' ? { ...x, is_correct: i === j } : j === i ? { ...x, is_correct: !x.is_correct } : x)))} />
                {type === 'true_false' ? <span className="text-sm">{o.text}</span> : (
                  <input className="field" value={o.text} placeholder={`Option ${i + 1}`} onChange={(e) => setOptions(options.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
                )}
                {type === 'multiple_choice' && options.length > 2 && (
                  <button type="button" className="btn btn-ghost btn-icon" aria-label="Remove option" onClick={() => setOptions(options.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
                )}
              </div>
            ))}
            {type === 'multiple_choice' && options.length < 10 && (
              <button type="button" className="btn btn-ghost" onClick={() => setOptions([...options, { text: '', is_correct: false }])}><Plus size={14} /> Add option</button>
            )}
          </div>
        </div>
      )}

      <div>
        <span className="label">{hasOptions ? 'Answer notes (optional)' : 'Answer'}</span>
        <MarkdownEditor value={answer} onChange={setAnswer} label="Answer" minRows={4} attach={initial ? { question_id: initial.id } : undefined} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Subject">
          <select className="field" value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
            <option value="">— none —</option>
            {tree.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </Field>
        <div>
          <span className="label">Topics</span>
          <TopicPicker value={topicIds} onChange={setTopicIds} subjectId={subjectId || null} />
        </div>
      </div>

      <button type="button" className="flex items-center gap-1 text-sm font-medium text-muted hover:text-fg" onClick={() => setMore(!more)} aria-expanded={more}>
        {more ? <ChevronDown size={14} /> : <ChevronRight size={14} />} More details
      </button>
      {more && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Type">
              <select className="field" value={type} onChange={(e) => changeType(e.target.value as QuestionType)}>
                {QUESTION_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </Field>
            <Field label="Difficulty">
              <select className="field" value={difficulty} onChange={(e) => setDifficulty(e.target.value as Difficulty)}>
                <option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option>
              </select>
            </Field>
          </div>
          <div>
            <span className="label">Explanation</span>
            <MarkdownEditor value={explanation} onChange={setExplanation} label="Explanation" minRows={3} attach={initial ? { question_id: initial.id } : undefined} />
          </div>
          <div>
            <span className="label">Tags</span>
            <TagInput value={tagNames} onChange={setTagNames} suggestions={tags.map((t) => t.name)} />
          </div>
          <Field label="Source or reference">
            <input className="field" value={source} onChange={(e) => setSource(e.target.value)} maxLength={500} placeholder="Book, URL, lecture…" />
          </Field>
        </div>
      )}
      {!more && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          Type: <button type="button" className="underline" onClick={() => setMore(true)}>{QUESTION_TYPES.find((t) => t.value === type)?.label}</button>
          · Difficulty: <span className="capitalize">{difficulty}</span>
        </div>
      )}

      {error && <p role="alert" className={cx('text-sm text-bad')}>{error}</p>}
      <div className="flex justify-end gap-2">
        {onCancel && <button type="button" className="btn" onClick={onCancel}>Cancel</button>}
        <Button type="submit" className="btn-primary" loading={save.isPending}>{saveLabel ?? (initial ? 'Save changes' : 'Create question')}</Button>
      </div>
    </form>
  )
}
