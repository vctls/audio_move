import { computed, reactive } from 'vue'
import { api, ApiError } from './api'
import type { AppConfig, PendingFields, Settings, TagPreset, Tags, Track } from './types'
import { arraysEqual, naturalCompare } from './util'

export interface Toast {
  id: number
  kind: 'info' | 'error' | 'success'
  text: string
}

export interface LargeFolder {
  path: string
  recursive: boolean
  reason: 'tracks' | 'folders'
  limit: number
  forced: boolean
}

export interface FieldChange {
  path: string
  field: string
  values: string[] | null
}

export const state = reactive({
  config: null as AppConfig | null,
  settings: null as Settings | null,
  folder: '',
  recursive: true,
  tracks: [] as Track[],
  selected: new Set<string>(),
  anchor: null as string | null,
  cursor: null as string | null,
  pending: {} as Record<string, PendingFields>,
  // Paths whose embedded pictures are removed on the next save.
  pictureRemovals: {} as Record<string, true>,
  loading: false,
  loadingPath: '',
  largeFolder: null as LargeFolder | null,
  saving: false,
  sort: null as { key: string; dir: 1 | -1 } | null,
  toasts: [] as Toast[],
  treeVersion: 0,
})

const undoStack: string[] = []
const redoStack: string[] = []
const history = reactive({ undo: 0, redo: 0 })
let toastId = 0

export function toast(text: string, kind: Toast['kind'] = 'info', ms = 4000) {
  const id = ++toastId
  state.toasts.push({ id, kind, text })
  setTimeout(() => dismissToast(id), kind === 'error' ? ms * 2 : ms)
}

export function dismissToast(id: number) {
  const i = state.toasts.findIndex((t) => t.id === id)
  if (i >= 0) state.toasts.splice(i, 1)
}

export function errorText(e: unknown): string {
  return e instanceof ApiError || e instanceof Error ? e.message : String(e)
}

// --- tags ------------------------------------------------------------------------

export function mergedTags(track: Track): Tags {
  const pending = state.pending[track.path]
  if (!pending) return track.tags
  const out: Tags = { ...track.tags }
  for (const [field, values] of Object.entries(pending)) {
    if (values === null) delete out[field]
    else out[field] = values
  }
  return out
}

export function fieldValues(track: Track, field: string): string[] | undefined {
  const pending = state.pending[track.path]
  if (pending && field in pending) return pending[field] ?? undefined
  return track.tags[field]
}

export const firstValue = (track: Track, field: string) => fieldValues(track, field)?.[0] ?? ''

export const isPending = (track: Track, field?: string) => {
  const p = state.pending[track.path]
  if (field === undefined) return (!!p && Object.keys(p).length > 0) || isPictureRemovalPending(track)
  return !!p && field in p
}

export const isPictureRemovalPending = (track: Track) => !!state.pictureRemovals[track.path]

/**
 * Describe what the files hold on disk for a field, for tooltips on staged values.
 */
export function onDiskTitle(tracks: Track[], field: string): string {
  const values = new Set(tracks.map((t) => displayValue(t.tags[field])))
  if (values.size > 1) return 'On disk: <multiple values>'
  return `On disk: ${[...values][0] || '(empty)'}`
}

const serialize = () => JSON.stringify({ pending: state.pending, pictures: state.pictureRemovals })

function restore(json: string) {
  const saved = JSON.parse(json)
  state.pending = saved.pending
  state.pictureRemovals = saved.pictures
}

function snapshot() {
  undoStack.push(serialize())
  if (undoStack.length > 200) undoStack.shift()
  redoStack.length = 0
  history.undo = undoStack.length
  history.redo = 0
}

/**
 * Stage tag edits. Values equal to what is on disk drop the pending entry.
 */
export function stage(changes: FieldChange[]) {
  if (!changes.length) return
  const byPath = new Map(state.tracks.map((t) => [t.path, t]))
  snapshot()
  for (const { path, field, values } of changes) {
    const track = byPath.get(path)
    if (!track) continue
    const key = field.toUpperCase()
    const clean = values?.map((v) => v.trim()).filter((v) => v !== '') ?? null
    const next = clean && clean.length ? clean : null
    const onDisk = track.tags[key]
    const pending = { ...(state.pending[path] ?? {}) }
    if ((next === null && onDisk === undefined) || (next !== null && arraysEqual(next, onDisk))) {
      delete pending[key]
    } else {
      pending[key] = next
    }
    if (Object.keys(pending).length) state.pending[path] = pending
    else delete state.pending[path]
  }
}

/**
 * Stage the removal of every embedded picture from these files.
 */
export function stagePictureRemoval(paths: string[]) {
  const withPictures = state.tracks.filter((t) => paths.includes(t.path) && t.pictures.length)
  if (!withPictures.length) return
  snapshot()
  const next = { ...state.pictureRemovals }
  for (const t of withPictures) next[t.path] = true
  state.pictureRemovals = next
}

/**
 * Save embedded pictures as folder images where a folder has none, then stage their removal.
 * Files whose folder still has no image afterwards keep their pictures.
 */
export async function picturesToFolder(paths: string[]): Promise<{ removed: number; kept: number }> {
  const wanted = new Set(paths)
  const withArt = () => state.tracks.filter((t) => wanted.has(t.path) && t.pictures.length)
  const missing = withArt().filter((t) => !t.folder_image)
  if (missing.length) {
    await api.extractPictures(missing.map((t) => t.path))
    await reloadTracks()
    state.treeVersion++
  }
  const safe = withArt().filter((t) => t.folder_image)
  stagePictureRemoval(safe.map((t) => t.path))
  return { removed: safe.length, kept: withArt().length - safe.length }
}

/**
 * Run a tag preset on these tracks, starting from their unsaved values, and stage the result.
 */
export async function runPreset(preset: TagPreset, paths: string[]) {
  const wanted = new Set(paths)
  const tracks = state.tracks.filter((t) => wanted.has(t.path))
  const tagActions = preset.actions.filter((a) => a.type !== 'pictures_to_folder')
  const changes: FieldChange[] = []
  if (tagActions.length && tracks.length) {
    const { results } = await api.runPreset(
      tagActions,
      tracks.map((t) => ({ path: t.path, tags: mergedTags(t), info: t.info })),
    )
    tracks.forEach((t, i) => {
      const before = mergedTags(t)
      const after = results[i]
      for (const field of new Set([...Object.keys(before), ...Object.keys(after)])) {
        if (!arraysEqual(before[field], after[field]))
          changes.push({ path: t.path, field, values: after[field] ?? null })
      }
    })
    stage(changes)
  }
  const pictures = preset.actions.some((a) => a.type === 'pictures_to_folder')
    ? await picturesToFolder(paths)
    : { removed: 0, kept: 0 }
  const parts = [`${changes.length} change(s) on ${new Set(changes.map((c) => c.path)).size} file(s)`]
  if (pictures.removed) parts.push(`pictures removed from ${pictures.removed} file(s)`)
  if (pictures.kept) parts.push(`${pictures.kept} file(s) keep their pictures, no folder image could be saved`)
  toast(`${preset.name}: ${parts.join(', ')}`, pictures.kept ? 'error' : 'info')
}

export function undo() {
  const prev = undoStack.pop()
  if (prev === undefined) return
  redoStack.push(serialize())
  restore(prev)
  history.undo = undoStack.length
  history.redo = redoStack.length
}

export function redo() {
  const next = redoStack.pop()
  if (next === undefined) return
  undoStack.push(serialize())
  restore(next)
  history.undo = undoStack.length
  history.redo = redoStack.length
}

export const canUndo = computed(() => history.undo > 0)
export const canRedo = computed(() => history.redo > 0)

const pendingPaths = computed(() => [
  ...new Set([...Object.keys(state.pending), ...Object.keys(state.pictureRemovals)]),
])

export const pendingCount = computed(() => pendingPaths.value.length)

export function revert() {
  if (!pendingCount.value) return
  snapshot()
  state.pending = {}
  state.pictureRemovals = {}
}

/**
 * Drop the staged changes of one file, or only those to one of its fields.
 */
export function discard(path: string, field?: string) {
  const fields = state.pending[path]
  if (field === undefined) {
    if (!fields && !state.pictureRemovals[path]) return
    snapshot()
    delete state.pending[path]
    delete state.pictureRemovals[path]
    return
  }
  if (!fields || !(field in fields)) return
  snapshot()
  const next = { ...fields }
  delete next[field]
  if (Object.keys(next).length) state.pending[path] = next
  else delete state.pending[path]
}

export function discardPictureRemoval(path: string) {
  if (!state.pictureRemovals[path]) return
  snapshot()
  delete state.pictureRemovals[path]
}

export async function save(): Promise<boolean> {
  const items = pendingPaths.value.map((path) => {
    const fields = state.pending[path] ?? {}
    return {
      path,
      set: Object.fromEntries(Object.entries(fields).filter(([, v]) => v !== null)) as Tags,
      remove: Object.entries(fields)
        .filter(([, v]) => v === null)
        .map(([k]) => k),
      remove_pictures: !!state.pictureRemovals[path],
    }
  })
  if (!items.length) return true
  state.saving = true
  try {
    const { results } = await api.saveTags(items)
    const failed = results.filter((r) => !r.ok)
    for (const r of results) {
      if (!r.ok || !r.track) continue
      replaceTrack(r.path, r.track)
      delete state.pending[r.path]
      delete state.pictureRemovals[r.path]
    }
    if (failed.length) {
      toast(`${failed.length} file(s) could not be saved: ${failed[0].error}`, 'error')
      return false
    }
    toast(`Saved ${results.length} file(s)`, 'success', 2500)
    undoStack.length = 0
    redoStack.length = 0
    history.undo = history.redo = 0
    return true
  } catch (e) {
    toast(`Save failed: ${errorText(e)}`, 'error')
    return false
  } finally {
    state.saving = false
  }
}

function replaceTrack(oldPath: string, track: Track) {
  const i = state.tracks.findIndex((t) => t.path === oldPath)
  if (i >= 0) state.tracks[i] = track
  if (oldPath !== track.path) {
    if (state.selected.delete(oldPath)) state.selected.add(track.path)
    if (state.cursor === oldPath) state.cursor = track.path
    if (state.anchor === oldPath) state.anchor = track.path
  }
}

// --- loading -------------------------------------------------------------------------

let loadController: AbortController | null = null

/**
 * Load a folder's tracks, aborting any load still in flight.
 * A folder over the server's size limit only sets state.largeFolder, so the user confirms first.
 */
export async function loadFolder(
  path: string,
  opts: { force?: boolean; recursive?: boolean; confirmed?: boolean } = {},
) {
  if (!opts.confirmed && pendingCount.value && !confirm('Discard unsaved tag changes?')) return
  loadController?.abort()
  const controller = new AbortController()
  loadController = controller
  const recursive = opts.recursive ?? state.recursive
  state.loading = true
  state.loadingPath = path
  state.largeFolder = null
  try {
    const res = await api.tracks(path, recursive, !!opts.force, controller.signal)
    if (res.too_many) {
      state.largeFolder = {
        path,
        recursive,
        reason: res.reason ?? 'tracks',
        limit: res.limit ?? 0,
        forced: !!res.forced,
      }
      return
    }
    state.folder = path
    state.tracks = res.tracks
    state.pending = {}
    state.pictureRemovals = {}
    state.selected = new Set()
    state.anchor = state.cursor = null
    state.sort = null
    undoStack.length = redoStack.length = 0
    history.undo = history.redo = 0
    if (res.errors.length) toast(`${res.errors.length} file(s) could not be read: ${res.errors[0].error}`, 'error')
  } catch (e) {
    if (!controller.signal.aborted) toast(errorText(e), 'error')
  } finally {
    if (loadController === controller) {
      loadController = null
      state.loading = false
      state.loadingPath = ''
    }
  }
}

/**
 * Re-read moved tracks from their new location, keeping list order and selection.
 */
export async function relocateTracks(moves: Record<string, string>) {
  const newPaths = Object.values(moves)
  if (!newPaths.length) return
  const { tracks } = await api.readTracks(newPaths)
  const byPath = new Map(tracks.map((t) => [t.path, t]))
  for (const [src, dst] of Object.entries(moves)) {
    const track = byPath.get(dst)
    if (track) replaceTrack(src, track)
  }
}

export async function reloadTracks() {
  if (!state.tracks.length) return
  const { tracks } = await api.readTracks(state.tracks.map((t) => t.path))
  const byPath = new Map(tracks.map((t) => [t.path, t]))
  state.tracks = state.tracks.map((t) => byPath.get(t.path)).filter((t): t is Track => !!t)
}

// --- selection & ordering -----------------------------------------------------------------

export const selectedTracks = computed(() => state.tracks.filter((t) => state.selected.has(t.path)))

// The selection, or every track when nothing is selected.
export const targetTracks = computed(() => (state.selected.size ? selectedTracks.value : state.tracks))

export function selectOnly(path: string) {
  state.selected = new Set([path])
  state.anchor = state.cursor = path
}

export function selectAll() {
  state.selected = new Set(state.tracks.map((t) => t.path))
}

export function selectRange(toPath: string, additive: boolean) {
  const paths = state.tracks.map((t) => t.path)
  const from = paths.indexOf(state.anchor ?? toPath)
  const to = paths.indexOf(toPath)
  const [a, b] = from < to ? [from, to] : [to, from]
  const range = paths.slice(a, b + 1)
  state.selected = new Set(additive ? [...state.selected, ...range] : range)
  state.cursor = toPath
}

export function toggleSelected(path: string) {
  const next = new Set(state.selected)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  state.selected = next
  state.anchor = state.cursor = path
}

export function removeSelectedFromList() {
  if (!state.selected.size) return
  const dropped = [...state.selected].filter((p) => state.pending[p] || state.pictureRemovals[p])
  if (dropped.length && !confirm(`${dropped.length} removed file(s) have unsaved changes. Discard them?`)) return
  for (const p of dropped) {
    delete state.pending[p]
    delete state.pictureRemovals[p]
  }
  state.tracks = state.tracks.filter((t) => !state.selected.has(t.path))
  state.selected = new Set()
}

export function moveSelection(delta: -1 | 1) {
  const list = [...state.tracks]
  const idx = list.map((t, i) => (state.selected.has(t.path) ? i : -1)).filter((i) => i >= 0)
  if (!idx.length) return
  if (delta < 0 && idx[0] === 0) return
  if (delta > 0 && idx[idx.length - 1] === list.length - 1) return
  const order = delta < 0 ? idx : [...idx].reverse()
  for (const i of order) {
    const j = i + delta
    ;[list[i], list[j]] = [list[j], list[i]]
  }
  state.tracks = list
  state.sort = null
}

export function sortValue(track: Track, key: string): string | number {
  switch (key) {
    case 'path':
      return track.path
    case 'codec':
      return track.info.codec
    case 'length':
      return track.info.length
    case 'art':
      return track.pictures.reduce((sum, p) => sum + p.size, 0)
    case 'bitrate':
      return track.info.bitrate
    default:
      return (fieldValues(track, key) ?? []).join('; ')
  }
}

export function sortBy(key: string) {
  const dir: 1 | -1 = state.sort?.key === key && state.sort.dir === 1 ? -1 : 1
  state.sort = { key, dir }
  const withDisc = key === 'TRACKNUMBER'
  state.tracks = [...state.tracks].sort((a, b) => {
    if (withDisc) {
      const d = naturalCompare(firstValue(a, 'DISCNUMBER'), firstValue(b, 'DISCNUMBER'))
      if (d) return d * dir
    }
    const x = sortValue(a, key)
    const y = sortValue(b, key)
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : naturalCompare(String(x), String(y))
    return (c || naturalCompare(a.path, b.path)) * dir
  })
}

// --- settings ------------------------------------------------------------------------------

export async function loadSettings() {
  try {
    const [config, settings] = await Promise.all([api.config(), api.settings()])
    state.config = config
    state.settings = settings
  } catch (e) {
    toast(`Cannot reach the server: ${errorText(e)}`, 'error')
  }
}

export async function updateSettings(patch: Partial<Settings>) {
  if (!state.settings) return
  const next = { ...state.settings, ...patch }
  state.settings = next
  try {
    state.settings = await api.saveSettings(next)
  } catch (e) {
    toast(`Settings not saved: ${errorText(e)}`, 'error')
  }
}

export function isMultivalue(field: string) {
  return (state.settings?.multivalue_fields ?? []).some((f) => f.toUpperCase() === field.toUpperCase())
}

/**
 * Parse a properties-panel entry the way foobar2000 does: ";" splits multi-value fields only.
 */
export function parseInput(field: string, text: string): string[] {
  if (isMultivalue(field))
    return text
      .split(';')
      .map((v) => v.trim())
      .filter(Boolean)
  return text.trim() ? [text.trim()] : []
}

export const displayValue = (values: string[] | undefined) => (values ?? []).join('; ')
