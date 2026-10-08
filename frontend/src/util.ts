const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

export const naturalCompare = (a: string, b: string) => collator.compare(a, b)

export function formatLength(seconds: number): string {
  if (!seconds && seconds !== 0) return ''
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const ss = String(s).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}

export const basename = (p: string) => p.slice(p.lastIndexOf('/') + 1)
export const dirname = (p: string) => p.slice(0, Math.max(p.lastIndexOf('/'), 0)) || '/'

export function relativeTo(path: string, base: string): string {
  if (!base) return path
  const prefix = base.endsWith('/') ? base : base + '/'
  return path.startsWith(prefix) ? path.slice(prefix.length) : path
}

export function arraysEqual(a: readonly string[] | undefined | null, b: readonly string[] | undefined | null) {
  const x = a ?? []
  const y = b ?? []
  return x.length === y.length && x.every((v, i) => v === y[i])
}

export function padNumber(n: number, width: number): string {
  return width > 0 ? String(n).padStart(width, '0') : String(n)
}

export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined
  return (...args: A) => {
    clearTimeout(timer)
    timer = setTimeout(() => fn(...args), ms)
  }
}

export const isEditableTarget = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export const formatDims = (w: number, h: number) => (w && h ? `${w}×${h}` : '')

export function pictureLabel(p: { type: string; mime: string; width: number; height: number; size: number }) {
  const format = p.mime.replace('image/', '').toUpperCase()
  return [p.type, format, formatDims(p.width, p.height), formatBytes(p.size)].filter(Boolean).join(' · ')
}

/**
 * Count the single-character insertions, deletions and substitutions that turn one string into the other.
 */
export function levenshtein(a: string, b: string): number {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j)
  for (let i = 1; i <= a.length; i++) {
    const row = [i]
    for (let j = 1; j <= b.length; j++)
      row[j] = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
    prev = row
  }
  return prev[b.length]
}
