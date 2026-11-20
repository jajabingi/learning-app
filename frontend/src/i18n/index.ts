import { he } from './he'

/** Current UI language. Hebrew only for now; add `en.ts` with the same shape and switch here to ship English. */
const dictionaries = { he } as const
export type Lang = keyof typeof dictionaries
export const lang: Lang = 'he'
export const dir = 'rtl'
const messages = dictionaries[lang]

/** t('student.lessonsOf', { a: 3, b: 10 }) — dotted key, {placeholders}. Missing keys render the key itself. */
export function t(key: string, vars?: Record<string, string | number>): string {
  let cur: unknown = messages
  for (const part of key.split('.')) cur = (cur as Record<string, unknown> | undefined)?.[part]
  let s = typeof cur === 'string' ? cur : key
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v))
  return s
}

/** Localise an API error message when we have a translation for it. */
export function tError(msg: string): string {
  return messages.errors[msg] ?? msg
}
