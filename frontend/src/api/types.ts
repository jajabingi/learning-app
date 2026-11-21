import { tt } from '@/i18n'
export type QuestionType =
  | 'open_ended' | 'multiple_choice' | 'true_false' | 'short_answer' | 'calculation' | 'formula'
  | 'definition' | 'conceptual' | 'case_study' | 'comparison' | 'scenario'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type Status = 'new' | 'learning' | 'reviewing' | 'mastered' | 'suspended'

export const QUESTION_TYPES: { value: QuestionType; label: string }[] = [
  { value: 'open_ended', label: tt('Open-ended') },
  { value: 'multiple_choice', label: tt('Multiple choice') },
  { value: 'true_false', label: tt('True / false') },
  { value: 'short_answer', label: tt('Short answer') },
  { value: 'calculation', label: tt('Calculation') },
  { value: 'formula', label: tt('Formula') },
  { value: 'definition', label: tt('Definition') },
  { value: 'conceptual', label: tt('Conceptual') },
  { value: 'case_study', label: tt('Case study') },
  { value: 'comparison', label: tt('Comparison') },
  { value: 'scenario', label: tt('Scenario-based') },
]

export interface User {
  id: string
  email: string
  display_name: string
  role: 'student' | 'teacher' | 'admin'
  permissions: string[]
  desired_retention: number
  daily_new_limit: number
  daily_review_goal: number
  timezone: string
  status?: string
  has_password?: boolean
  providers?: string[]
  email_verified?: boolean
}

export interface Tag { id: string; name: string; color: string; question_count?: number }
export interface Option { id?: string; text: string; is_correct: boolean; position?: number }
export interface Progress {
  status: Status
  state: string
  suspended: boolean
  stability: number
  difficulty: number
  reps: number
  lapses: number
  correct_count: number
  confidence: number | null
  last_review_at: string | null
  due_at: string | null
  retrievability: number | null
  mastery: number
}
export interface Question {
  id: string
  title: string
  content: string
  question_type: QuestionType
  difficulty: Difficulty
  source: string
  subject_id: string | null
  topics: { id: string; name: string }[]
  tags: Tag[]
  answer: { answer: string; explanation: string }
  options: Option[]
  attachments: { id: string; filename: string; content_type: string; size_bytes: number }[]
  archived: boolean
  created_at: string
  updated_at: string
  progress: Progress
}
export interface QuestionPage { items: Question[]; total: number; page: number; page_size: number }
export interface QuestionDraft {
  title: string
  content: string
  question_type: QuestionType
  difficulty: Difficulty
  source: string
  subject_id: string | null
  topic_ids: string[]
  tags: string[]
  answer: { answer: string; explanation: string }
  options: { text: string; is_correct: boolean }[]
}

export interface TopicNode {
  id: string
  name: string
  color: string
  icon: string
  archived: boolean
  subject_id: string
  chapter_id: string | null
  parent_id: string | null
  question_count: number
  mastery: number
  due: number
  children: TopicNode[]
}
export interface ChapterNode { id: string; name: string; description: string; archived: boolean; topics: TopicNode[] }
export interface CourseNode { id: string; name: string; description: string; archived: boolean; chapters: ChapterNode[] }
export interface SubjectNode {
  id: string
  name: string
  description: string
  color: string
  icon: string
  archived: boolean
  courses: CourseNode[]
  topics: TopicNode[]
  question_count: number
  mastery: number
  due: number
  topic_count: number
}

export interface TopicFlat { id: string; name: string; path: string; subject_id: string; subject_name: string }

export interface Note {
  id: string
  title: string
  content: string
  kind: 'note' | 'definition' | 'formula'
  subject_id: string | null
  course_id: string | null
  chapter_id: string | null
  topic_id: string | null
  question_id: string | null
  tags: Tag[]
  created_at: string
  updated_at: string
  links_to: { id: string; title: string }[]
}

export interface SessionSummary {
  id: string
  mode: string
  status: 'active' | 'paused' | 'completed' | 'abandoned'
  topic_id: string | null
  subject_id: string | null
  started_at: string
  ended_at: string | null
  last_activity_at: string
  total: number
  answered: number
  filters: Record<string, unknown>
}
export interface SessionItem {
  position: number
  answered: boolean
  rating: number | null
  question: Question
  intervals: Record<string, number>
}
export interface SessionDetail extends SessionSummary { items: SessionItem[] }

export interface WeakArea {
  topic_id: string
  name: string
  subject_id: string
  questions: number
  mastery: number
  accuracy: number | null
  reviews: number
  due: number
  reasons: string[]
}
export interface DailyPoint { date: string; reviews: number; accuracy: number | null; minutes: number; new_learned: number }
export interface SubjectStat {
  id: string; name: string; color: string; questions: number; mastery: number; mastered: number; due: number
  learning: number; reviewing: number; new: number; suspended: number
  reviews: number; accuracy: number | null; retention: number | null; minutes: number
}
export interface Dashboard {
  totals: {
    subjects: number; topics: number; questions: number; mastered: number; needs_review: number; due_today: number
    streak: number; longest_streak: number; mastery: number; reviewed_today: number; daily_goal: number
  }
  review_today: { due: number; estimated_seconds: number; new_available: number }
  status_distribution: Record<Status, number>
  continue_learning: { topic_id: string; name: string; subject_id: string; last_studied: string; mastery: number; questions: number; due: number }[]
  subjects: SubjectStat[]
  weak_areas: WeakArea[]
  recent_activity: { type: string; id: string; title: string; at: string }[]
  activity_series: DailyPoint[]
  retention_trend: { week_start: string; reviews: number; retention: number | null }[]
}
export interface Analytics {
  period_days: number
  summary: {
    total_questions: number; questions_answered: number; reviews: number; accuracy: number | null
    retention: number | null; retention_sample: number; mastery: number; mastered: number; streak: number
    longest_streak: number; study_minutes: number; completion_rate: number | null; active_days: number
  }
  status_distribution: Record<Status, number>
  daily: DailyPoint[]
  retention_trend: { week_start: string; reviews: number; retention: number | null }[]
  subjects: SubjectStat[]
  strongest_subjects: SubjectStat[]
  weakest_subjects: SubjectStat[]
  topics: { topic_id: string; name: string; subject_id: string; questions: number; mastery: number; accuracy: number | null; reviews: number; lapses: number; due: number }[]
  weak_topics: WeakArea[]
  most_forgotten: { question_id: string; title: string; subject_id: string | null; lapses: number; reviews: number }[]
  definitions: Record<string, string>
}
export interface ReviewQueue {
  due_now: number; overdue: number; due_today: number; reviewed_today: number; daily_goal: number
  completion_today: number; new_available: number; estimated_seconds: number; seconds_per_review: number
  items: { question_id: string; title: string; question_type: string; subject_id: string | null; due_at: string; overdue_days: number; status: Status; stability: number; lapses: number }[]
  upcoming: { date: string; count: number }[]
  open_sessions: SessionSummary[]
}
export interface GraphData {
  nodes: { id: string; name: string; subject_id: string; subject_name: string; color: string; questions: number; mastery: number; accuracy: number | null; due: number }[]
  edges: { id: string; source_topic_id: string; target_topic_id: string; relation_type: string; note: string }[]
}
export interface SearchResult { type: string; id: string; title: string; snippet: string; subject_id?: string }
export interface Evaluation {
  score: number
  correct_concepts: string[]
  missing_concepts: string[]
  incorrect_reasoning: string[]
  improved_answer: string
  explanation: string
  suggested_rating: number
}

export const RELATIONS = [
  { value: 'related_to', label: tt('Related to') },
  { value: 'prerequisite_for', label: tt('Prerequisite for') },
  { value: 'part_of', label: tt('Part of') },
  { value: 'contrasts_with', label: tt('Contrasts with') },
  { value: 'depends_on', label: tt('Depends on') },
  { value: 'applied_in', label: tt('Applied in') },
] as const

// ---------- LMS ----------
export type CourseStatus = 'draft' | 'published' | 'archived'
export interface Course {
  id: string; slug: string; title: string; subtitle: string; description: string; summary: string
  cover_attachment_id: string | null; institution_id?: string | null; instructor_name: string; category: string
  difficulty: 'beginner' | 'intermediate' | 'advanced' | 'all'; language: string; status: CourseStatus
  published_at: string | null; price_amount: number; discount_amount: number | null; currency: string
  enrollment_type: 'free' | 'paid' | 'manual'; payment_policy: 'full_payment' | 'any_payment' | 'none'
  access_days: number | null; objectives: string[]; requirements: string[]; target_audience: string
  estimated_minutes: number; completion_rule: { min_lesson_percent: number; require_quizzes: boolean }
  created_at: string; updated_at: string
  module_count?: number; lesson_count?: number; published_lesson_count?: number; enrollment_count?: number
}
export interface LessonBrief { id: string; title: string; position: number; estimated_minutes: number; is_free_preview: boolean; is_published?: boolean; block_count?: number; completed?: boolean }
export interface ModuleNode { id: string; title: string; description: string; summary: string; position: number; is_published?: boolean; lessons: LessonBrief[] }
export interface CourseDetail extends Course { curriculum: ModuleNode[] }
export type BlockType =
  | 'video' | 'text' | 'summary' | 'rich_text' | 'image' | 'pdf' | 'file' | 'formula' | 'table' | 'example'
  | 'question' | 'quiz' | 'assignment' | 'external_link' | 'callout' | 'resource'
export interface Block { id: string; type: BlockType; position: number; is_visible?: boolean; data: Record<string, any> }
export interface LessonDetail extends LessonBrief { summary: string; module_id: string; course_id: string; blocks: Block[]; preview?: boolean }
export interface TeamUser { id: string; email: string; display_name: string; role: 'student' | 'teacher' | 'admin'; is_active: boolean; status?: string; permissions: string[]; created_at: string }
