<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  displayValue,
  fieldValues,
  isDrasticChange,
  isPending,
  isPictureRemovalPending,
  loadFolder,
  onDiskTitle,
  parseInput,
  selectOnly,
  selectRange,
  sortBy,
  stage,
  state,
  toggleSelected,
} from '../store'
import type { Track } from '../types'
import { basename, formatDims, formatLength, pictureLabel, relativeTo } from '../util'

interface Column {
  key: string
  label: string
  width: number
  visible: boolean
  field?: boolean
  right?: boolean
}

const DEFAULT_COLUMNS: Column[] = [
  { key: 'index', label: '#', width: 40, visible: true, right: true },
  { key: 'DISCNUMBER', label: 'Disc', width: 40, visible: true, field: true, right: true },
  { key: 'TRACKNUMBER', label: 'Track', width: 46, visible: true, field: true, right: true },
  { key: 'ARTIST', label: 'Artist', width: 140, visible: true, field: true },
  { key: 'TITLE', label: 'Title', width: 210, visible: true, field: true },
  { key: 'ALBUM', label: 'Album', width: 160, visible: true, field: true },
  { key: 'ALBUM ARTIST', label: 'Album artist', width: 130, visible: true, field: true },
  { key: 'DATE', label: 'Date', width: 74, visible: true, field: true },
  { key: 'GENRE', label: 'Genre', width: 100, visible: false, field: true },
  { key: 'COMPOSER', label: 'Composer', width: 130, visible: false, field: true },
  { key: 'LABEL', label: 'Label', width: 120, visible: false, field: true },
  { key: 'codec', label: 'Codec', width: 74, visible: true },
  { key: 'bitrate', label: 'Bitrate', width: 60, visible: false, right: true },
  { key: 'length', label: 'Length', width: 54, visible: true, right: true },
  { key: 'art', label: 'Art', width: 100, visible: true },
  { key: 'path', label: 'File', width: 220, visible: true },
]

const saved: Record<string, { width: number; visible: boolean }> = JSON.parse(localStorage.getItem('columns') || '{}')
const allColumns = ref<Column[]>(DEFAULT_COLUMNS.map((c) => ({ ...c, ...saved[c.key] })))
const columns = computed(() => allColumns.value.filter((c) => c.visible))
const editableKeys = computed(() => columns.value.filter((c) => c.field).map((c) => c.key))

// The last column absorbs the free space so the table always spans the pane.
const containerWidth = ref(0)
const baseWidth = computed(() => columns.value.reduce((s, c) => s + c.width, 0))
const extra = computed(() => Math.max(0, containerWidth.value - baseWidth.value - 2))
const tableWidth = computed(() => baseWidth.value + extra.value)
const widthOf = (col: Column, i: number) => col.width + (i === columns.value.length - 1 ? extra.value : 0)

const menu = ref<{ x: number; y: number } | null>(null)

function persistColumns() {
  const out = Object.fromEntries(allColumns.value.map((c) => [c.key, { width: c.width, visible: c.visible }]))
  localStorage.setItem('columns', JSON.stringify(out))
}

function openMenu(e: MouseEvent) {
  menu.value = { x: e.clientX, y: e.clientY }
}

function toggleColumn(col: Column) {
  if (col.key === 'index') return
  col.visible = !col.visible
  persistColumns()
}

let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver((entries) => (containerWidth.value = entries[0].contentRect.width))
  if (container.value) observer.observe(container.value)
})
onBeforeUnmount(() => observer?.disconnect())

const editing = ref<{ path: string; key: string } | null>(null)
const editText = ref('')
const editInput = ref<HTMLInputElement[]>([])
const container = ref<HTMLElement | null>(null)

function cell(track: Track, col: Column, index: number): string {
  switch (col.key) {
    case 'index':
      return String(index + 1)
    case 'codec':
      return track.info.codec + (track.info.codec_profile ? ` ${track.info.codec_profile}` : '')
    case 'length':
      return formatLength(track.info.length)
    case 'bitrate':
      return track.info.bitrate ? String(track.info.bitrate) : ''
    case 'art':
      return artLabel(track)
    case 'path':
      return relativeTo(track.path, state.folder)
    default:
      return displayValue(fieldValues(track, col.key))
  }
}

function artLabel(track: Track): string {
  const pics = track.pictures
  if (!pics.length) return ''
  if (isPictureRemovalPending(track)) return 'removed'
  if (pics.length > 1) return `${pics.length} pictures`
  return formatDims(pics[0].width, pics[0].height) || pics[0].type
}

function cellTitle(track: Track, col: Column): string | undefined {
  if (col.key === 'path') return track.path
  if (col.key === 'art' && track.pictures.length) return track.pictures.map(pictureLabel).join('\n')
  if (col.field && isPending(track, col.key)) return onDiskTitle([track], col.key)
  return undefined
}

function onRowClick(e: MouseEvent, track: Track) {
  if (editing.value) return
  if (e.shiftKey) selectRange(track.path, e.ctrlKey || e.metaKey)
  else if (e.ctrlKey || e.metaKey) toggleSelected(track.path)
  else selectOnly(track.path)
}

function startEdit(track: Track, key: string) {
  if (!editableKeys.value.includes(key)) return
  selectOnly(track.path)
  editing.value = { path: track.path, key }
  editText.value = displayValue(fieldValues(track, key))
  void nextTick(() => {
    editInput.value[0]?.focus()
    editInput.value[0]?.select()
  })
}

function commitEdit() {
  const e = editing.value
  if (!e) return
  const track = state.tracks.find((t) => t.path === e.path)
  if (track && editText.value !== displayValue(fieldValues(track, e.key))) {
    stage([{ path: e.path, field: e.key, values: parseInput(e.key, editText.value) }])
  }
  editing.value = null
}

function onEditKey(ev: KeyboardEvent) {
  const e = editing.value
  if (!e) return
  if (ev.key === 'Escape') {
    ev.stopPropagation()
    editing.value = null
    container.value?.focus()
    return
  }
  if (ev.key !== 'Enter' && ev.key !== 'Tab') return
  ev.preventDefault()
  commitEdit()
  const rowIdx = state.tracks.findIndex((t) => t.path === e.path)
  const colIdx = editableKeys.value.indexOf(e.key)
  let [r, c] = [rowIdx, colIdx]
  if (ev.key === 'Enter') r += ev.shiftKey ? -1 : 1
  else c += ev.shiftKey ? -1 : 1
  const next = state.tracks[r]
  if (next && c >= 0 && c < editableKeys.value.length) startEdit(next, editableKeys.value[c])
  else container.value?.focus()
}

function onKey(e: KeyboardEvent) {
  if (editing.value || !state.tracks.length) return
  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown' && e.key !== 'Home' && e.key !== 'End') return
  if (e.altKey) return
  e.preventDefault()
  const paths = state.tracks.map((t) => t.path)
  const cur = state.cursor ? paths.indexOf(state.cursor) : -1
  let next = cur
  if (e.key === 'ArrowUp') next = Math.max(0, cur - 1)
  else if (e.key === 'ArrowDown') next = Math.min(paths.length - 1, cur + 1)
  else if (e.key === 'Home') next = 0
  else next = paths.length - 1
  if (e.shiftKey) selectRange(paths[next], false)
  else selectOnly(paths[next])
  void nextTick(() => container.value?.querySelector('tr.cursor')?.scrollIntoView({ block: 'nearest' }))
}

function startResize(e: MouseEvent, col: Column) {
  const start = e.clientX
  const initial = col.width
  const move = (ev: MouseEvent) => {
    col.width = Math.max(30, initial + ev.clientX - start)
  }
  const up = () => {
    persistColumns()
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

function onHeaderClick(col: Column) {
  if (col.key !== 'index') sortBy(col.key)
}
</script>

<template>
  <div class="pane">
    <div v-if="state.largeFolder" class="large">
      <span>
        <strong>{{ basename(state.largeFolder.path) }}</strong>
        {{
          state.largeFolder.reason === 'folders'
            ? `has too many subfolders to scan for tracks (over ${state.largeFolder.limit * 2}).`
            : `holds more than ${state.largeFolder.limit} tracks${state.largeFolder.recursive ? ' with its subfolders' : ''}.`
        }}
        {{ state.largeFolder.forced ? 'Pick a narrower folder.' : '' }}
      </span>
      <button
        v-if="!state.largeFolder.forced"
        class="primary"
        @click="
          loadFolder(state.largeFolder.path, { force: true, recursive: state.largeFolder.recursive, confirmed: true })
        "
      >
        Load up to {{ state.config?.max_tracks }} anyway
      </button>
      <button
        v-if="state.largeFolder.recursive"
        @click="loadFolder(state.largeFolder.path, { recursive: false, confirmed: true })"
      >
        Only its own files
      </button>
      <button class="link" @click="state.largeFolder = null">Dismiss</button>
    </div>
    <div ref="container" class="tracks" tabindex="0" @keydown="onKey">
      <table v-if="state.tracks.length" :style="{ width: tableWidth + 'px' }">
        <colgroup>
          <col v-for="(col, i) in columns" :key="col.key" :style="{ width: widthOf(col, i) + 'px' }" />
        </colgroup>
        <thead @contextmenu.prevent="openMenu">
          <tr>
            <th
              v-for="col in columns"
              :key="col.key"
              :class="{ right: col.right }"
              title="Click to sort, right-click to choose columns"
              @click="onHeaderClick(col)"
            >
              <span class="ellipsis">{{ col.label }}</span>
              <span v-if="state.sort?.key === col.key" class="sort">{{ state.sort.dir === 1 ? '▲' : '▼' }}</span>
              <span class="resizer" @click.stop @mousedown.stop.prevent="startResize($event, col)" />
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(track, i) in state.tracks"
            :key="track.path"
            :class="{
              selected: state.selected.has(track.path),
              cursor: state.cursor === track.path,
              dirty: isPending(track),
            }"
            @click="onRowClick($event, track)"
          >
            <td
              v-for="col in columns"
              :key="col.key"
              :class="{
                right: col.right,
                pending:
                  (col.field && isPending(track, col.key)) || (col.key === 'art' && isPictureRemovalPending(track)),
                drastic: col.field && isDrasticChange(track, col.key),
              }"
              :title="cellTitle(track, col)"
              @dblclick="startEdit(track, col.key)"
            >
              <input
                v-if="editing?.path === track.path && editing.key === col.key"
                ref="editInput"
                v-model="editText"
                class="cell-input"
                @keydown="onEditKey"
                @blur="commitEdit"
                @click.stop
              />
              <template v-else>
                <span v-if="col.key === 'index' && isPending(track)" class="dot" title="Unsaved changes">●</span>
                {{ cell(track, col, i) }}
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="menu" class="menu-backdrop" @mousedown="menu = null" @contextmenu.prevent="menu = null">
        <div class="column-menu" :style="{ left: menu.x + 'px', top: menu.y + 'px' }" @mousedown.stop>
          <label v-for="col in allColumns.filter((c) => c.key !== 'index')" :key="col.key">
            <input type="checkbox" :checked="col.visible" @change="toggleColumn(col)" /> {{ col.label }}
          </label>
        </div>
      </div>
      <div v-if="!state.tracks.length" class="empty muted">
        <p v-if="state.loading">Loading…</p>
        <template v-else>
          <p>Pick a folder on the left to load its tracks.</p>
          <p>
            <kbd>Ctrl</kbd>/<kbd>Shift</kbd>+click to select several tracks, double-click a cell to edit it,
            <kbd>Alt</kbd>+<kbd>↑</kbd>/<kbd>↓</kbd> to reorder, <kbd>Del</kbd> to drop tracks from the list.
          </p>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}

.tracks {
  flex: 1;
  overflow: auto;
  background: var(--panel);
  outline: none;
  min-height: 0;
}

table {
  table-layout: fixed;
  border-collapse: collapse;
  user-select: none;
}

th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--panel-2);
  border-bottom: 1px solid var(--border);
  border-right: 1px solid var(--border);
  font-weight: 600;
  text-align: left;
  padding: 3px 6px;
  white-space: nowrap;
  overflow: hidden;
  cursor: pointer;
}

th .sort {
  font-size: 9px;
  margin-left: 4px;
  color: var(--muted);
}

.resizer {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
}

td {
  padding: 1px 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-bottom: 1px solid transparent;
}

.right {
  text-align: right;
}

tbody tr:nth-child(even) {
  background: var(--row-alt);
}

tbody tr.selected {
  background: var(--select);
}

tbody tr.cursor td {
  border-bottom-color: var(--accent);
}

td.pending {
  color: var(--pending);
  font-style: italic;
}

td.drastic {
  color: var(--danger);
}

.dot {
  color: var(--pending);
  font-size: 8px;
  vertical-align: middle;
  margin-right: 3px;
}

.cell-input {
  width: 100%;
  padding: 0 3px;
  border-radius: 2px;
}

.large {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 8px 12px;
  background: var(--pending-bg);
  border-bottom: 1px solid var(--border);
}

.menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 30;
}

.column-menu {
  position: fixed;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: var(--shadow);
  padding: 6px 10px;
}

.empty {
  padding: 24px;
  max-width: 560px;
}
</style>
