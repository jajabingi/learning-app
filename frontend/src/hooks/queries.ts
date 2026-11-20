import { useQuery, useQueryClient } from '@tanstack/react-query'
import { get } from '@/api/client'
import type { SubjectNode, Tag, TopicFlat } from '@/api/types'

export const useTree = (includeArchived = false) =>
  useQuery({ queryKey: ['tree', includeArchived], queryFn: () => get<SubjectNode[]>('/library/tree', { include_archived: includeArchived }) })

export const useTags = () => useQuery({ queryKey: ['tags'], queryFn: () => get<Tag[]>('/tags') })

export const useTopicList = () => useQuery({ queryKey: ['topics-flat'], queryFn: () => get<TopicFlat[]>('/topics') })

export const useAiStatus = () =>
  useQuery({ queryKey: ['ai-status'], queryFn: () => get<{ enabled: boolean; provider: string | null; model: string | null }>('/ai/status'), staleTime: 5 * 60_000 })

/** Invalidate every cache that depends on library/question/learning data. */
export function useInvalidateAll() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries()
}
