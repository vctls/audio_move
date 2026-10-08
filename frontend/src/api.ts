import type {
  AppConfig,
  DirEntry,
  DirSummary,
  ExecuteResult,
  HistoryEntry,
  MbRelease,
  MbSearchResult,
  Operation,
  Plan,
  Settings,
  TagAction,
  Tags,
  Track,
  TrackInfo,
  TracksResponse,
} from './types'

export class ApiError extends Error {}

async function request<T>(method: string, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(url, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const data = await resp.json()
      if (typeof data.detail === 'string') detail = data.detail
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg: string }) => d.msg).join(', ')
    } catch {
      // The body was not JSON; keep the status line.
    }
    throw new ApiError(detail)
  }
  return resp.json() as Promise<T>
}

const qs = (params: Record<string, string | number | boolean>) =>
  new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()

export interface FileOpRequest {
  paths: string[]
  pattern: string
  operation: Operation
  destination: string
  move_other_files: boolean
  remove_empty_dirs: boolean
  base_dir: string | null
}

export const api = {
  config: () => request<AppConfig>('GET', '/api/config'),
  browse: (path: string) => request<{ path: string; dirs: DirEntry[] }>('GET', `/api/browse?${qs({ path })}`),
  browseSummary: (paths: string[]) =>
    request<{ summaries: Record<string, DirSummary> }>('POST', '/api/browse/summary', { paths }),
  tracks: (path: string, recursive: boolean, force: boolean, signal?: AbortSignal) =>
    request<TracksResponse>('GET', `/api/tracks?${qs({ path, recursive, force })}`, undefined, signal),
  readTracks: (paths: string[]) =>
    request<{ tracks: Track[]; errors: { path: string; error: string }[] }>('POST', '/api/tracks/read', { paths }),
  saveTags: (items: { path: string; set: Tags; remove: string[]; remove_pictures: boolean }[]) =>
    request<{ results: { path: string; ok: boolean; error?: string; track?: Track }[] }>('POST', '/api/tags', {
      items,
    }),
  format: (template: string, items: { path: string; tags: Tags; info: TrackInfo }[]) =>
    request<{ results: string[] }>('POST', '/api/format', { template, items }),
  runPreset: (actions: TagAction[], items: { path: string; tags: Tags; info: TrackInfo }[]) =>
    request<{ results: Tags[] }>('POST', '/api/presets/run', { actions, items }),
  guess: (pattern: string, paths: string[]) =>
    request<{ results: (Record<string, string> | null)[] }>('POST', '/api/guess', { pattern, paths }),
  preview: (body: FileOpRequest) => request<Plan>('POST', '/api/fileops/preview', body),
  execute: (body: FileOpRequest) => request<ExecuteResult>('POST', '/api/fileops/execute', body),
  history: () => request<HistoryEntry[]>('GET', '/api/fileops/history'),
  undo: (id: string) =>
    request<{ restored: { src: string; dst: string; kind: string }[]; errors: { src: string; error: string }[] }>(
      'POST',
      '/api/fileops/undo',
      { id },
    ),
  settings: () => request<Settings>('GET', '/api/settings'),
  saveSettings: (s: Settings) => request<Settings>('PUT', '/api/settings', s),
  mbSearch: (body: {
    artist?: string
    album?: string
    query?: string
    offset?: number
    tracks?: { path: string; tags: Tags; info: TrackInfo }[]
  }) => request<MbSearchResult>('POST', '/api/mb/search', body),
  mbRelease: (id: string, opts: { date: string; groups: string; disc_for_single: boolean; padding: number }) =>
    request<MbRelease>('GET', `/api/mb/release/${id}?${qs(opts)}`),
  mbCover: (body: { release_id: string; dirs: string[]; size: string; overwrite: boolean }) =>
    request<{ results: { path: string; ok: boolean; error?: string }[] }>('POST', '/api/mb/cover', body),
  extractPictures: (paths: string[]) =>
    request<{ results: { dir: string; ok: boolean; skipped?: boolean; path?: string; message?: string }[] }>(
      'POST',
      '/api/pictures/extract',
      { paths },
    ),
}
