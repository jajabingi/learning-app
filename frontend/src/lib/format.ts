import { t, tt } from '@/i18n'

export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`

export function duration(seconds: number) {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} ${t('common.secondsShort')}`
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} ${t('common.minutesShort')}`
  const h = Math.floor(m / 60)
  return `${h} ${t('common.hoursShort')} ${m % 60} ${t('common.minutesShort')}`
}

/** Interval in days (can be fractional for minutes) -> compact Hebrew label. */
export function interval(days: number) {
  if (days < 1 / 24) return `${Math.max(1, Math.round(days * 1440))} ${t('common.minutesShort')}`
  if (days < 1) return `${Math.round(days * 24)} ${t('common.hoursShort')}`
  if (days < 14) return `${Math.round(days)} ימים`
  if (days < 60) return `${Math.round(days / 7)} שבועות`
  if (days < 365) return `${Math.round(days / 30)} חודשים`
  return `${(days / 365).toFixed(1)} שנים`
}

export function relTime(iso: string) {
  const d = new Date(iso).getTime()
  const diff = (Date.now() - d) / 1000
  const abs = Math.abs(diff)
  const fut = diff < 0
  let s: string
  if (abs < 60) return fut ? 'בעוד רגע' : 'ממש עכשיו'
  if (abs < 3600) s = `${Math.round(abs / 60)} דק׳`
  else if (abs < 86400) s = `${Math.round(abs / 3600)} שע׳`
  else if (abs < 86400 * 30) s = `${Math.round(abs / 86400)} ימים`
  else return new Date(iso).toLocaleDateString('he-IL')
  return fut ? `בעוד ${s}` : `לפני ${s}`
}

export const shortDate = (iso: string) =>
  new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('he-IL', { month: 'short', day: 'numeric' })

export const plain = (md: string, n = 120) =>
  md.replace(/[#*_`>$\[\]!()-]/g, '').replace(/\s+/g, ' ').trim().slice(0, n)

export const masteryTone = (m: number) => (m >= 0.7 ? 'good' : m >= 0.35 ? 'warn' : 'bad')

export const REASONS: Record<string, string> = {
  low_accuracy: tt('Low accuracy'),
  low_mastery: tt('Low mastery'),
  repeated_mistakes: tt('Repeated mistakes'),
  forgotten: tt('Forgotten answers'),
  insufficient_practice: tt('Insufficient practice'),
}
