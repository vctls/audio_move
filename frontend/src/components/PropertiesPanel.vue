<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import {
  displayValue,
  isDrasticChange,
  isPending,
  isPictureRemovalPending,
  mergedTags,
  onDiskTitle,
  parseInput,
  selectedTracks,
  stage,
  toast,
} from '../store'
import type { FieldChange } from '../store'
import type { Track } from '../types'
import { dirname, formatBytes, formatDims, formatLength, pictureLabel } from '../util'

// foobar2000 always lists these, even when empty.
const STANDARD = [
  'ARTIST',
  'TITLE',
  'ALBUM',
  'DATE',
  'GENRE',
  'COMPOSER',
  'PERFORMER',
  'ALBUM ARTIST',
  'TRACKNUMBER',
  'TOTALTRACKS',
  'DISCNUMBER',
  'TOTALDISCS',
  'COMMENT',
]

interface Row {
  field: string
  value: string
  multiple: boolean
  present: number
  pending: boolean
  drastic: boolean
  onDisk: string
}

const tracks = selectedTracks
const rows = computed<Row[]>(() => {
  const ts = tracks.value
  if (!ts.length) return []
  const merged = ts.map(mergedTags)
  const extra = new Set<string>()
  for (const m of merged) for (const k of Object.keys(m)) if (!STANDARD.includes(k)) extra.add(k)
  return [...STANDARD, ...[...extra].sort()].map((field) => {
    const values = merged.map((m) => displayValue(m[field]))
    const multiple = new Set(values).size > 1
    const pending = ts.some((t) => isPending(t, field))
    return {
      field,
      value: multiple ? '' : values[0],
      multiple,
      present: merged.filter((m) => m[field]?.length).length,
      pending,
      drastic: pending && ts.some((t) => isDrasticChange(t, field)),
      onDisk: pending ? onDiskTitle(ts, field) : '',
    }
  })
})

const editing = ref<{ field: string; part: 'value' | 'name' } | null>(null)
const editText = ref('')
const input = ref<HTMLInputElement[]>([])
const newName = ref('')
const newValue = ref('')

function focusInput() {
  void nextTick(() => {
    input.value[0]?.focus()
    input.value[0]?.select()
  })
}

function startEdit(row: Row, part: 'value' | 'name' = 'value') {
  editing.value = { field: row.field, part }
  editText.value = part === 'name' ? row.field : row.multiple ? '' : row.value
  focusInput()
}

function setField(field: string, values: string[] | null) {
  stage(tracks.value.map((t) => ({ path: t.path, field, values })))
}

function commit() {
  const e = editing.value
  if (!e) return
  editing.value = null
  const row = rows.value.find((r) => r.field === e.field)
  if (!row) return
  if (e.part === 'name') {
    renameField(row, editText.value)
    return
  }
  if (row.multiple && editText.value === '') return
  if (!row.multiple && editText.value === row.value) return
  const values = parseInput(row.field, editText.value)
  setField(row.field, values.length ? values : null)
}

function renameField(row: Row, name: string) {
  const target = name.trim().toUpperCase()
  if (!target || target === row.field) return
  const changes: FieldChange[] = []
  for (const t of tracks.value) {
    const values = mergedTags(t)[row.field]
    if (!values) continue
    changes.push({ path: t.path, field: row.field, values: null })
    changes.push({ path: t.path, field: target, values })
  }
  stage(changes)
}

function onKey(ev: KeyboardEvent) {
  const e = editing.value
  if (!e) return
  if (ev.key === 'Escape') {
    ev.stopPropagation()
    editing.value = null
    return
  }
  if (ev.key === 'Enter') {
    ev.preventDefault()
    commit()
    return
  }
  if (ev.key === 'Tab' && e.part === 'value') {
    ev.preventDefault()
    const idx = rows.value.findIndex((r) => r.field === e.field)
    commit()
    const next = rows.value[idx + (ev.shiftKey ? -1 : 1)]
    if (next) startEdit(next)
  }
}

function addField() {
  const name = newName.value.trim().toUpperCase()
  if (!name) return
  if (name.includes('=') || name.includes('~')) {
    toast('Field names cannot contain "=" or "~"', 'error')
    return
  }
  const values = parseInput(name, newValue.value)
  if (!values.length) return
  setField(name, values)
  newName.value = ''
  newValue.value = ''
}

function embeddedArt(ts: Track[]): string {
  const withArt = ts.filter((t) => t.pictures.length)
  if (!withArt.length) return 'none'
  const removing = withArt.filter(isPictureRemovalPending).length
  if (ts.length === 1) {
    const list = ts[0].pictures.map(pictureLabel).join('\n')
    return removing ? `removed on save\n${list}` : list
  }
  const bytes = withArt.reduce((sum, t) => sum + t.pictures.reduce((s, p) => s + p.size, 0), 0)
  const summary = `${withArt.length} of ${ts.length} files · ${formatBytes(bytes)}`
  return removing ? `${summary}\n${removing} removed on save` : summary
}

function folderImage(ts: Track[]): string {
  const byDir = new Map(ts.map((t) => [dirname(t.path), t.folder_image]))
  if (byDir.size > 1) {
    const withImage = [...byDir.values()].filter(Boolean).length
    return `${withImage} of ${byDir.size} folders`
  }
  const image = [...byDir.values()][0]
  if (!image) return 'none'
  return [image.names.join(', '), formatDims(image.width, image.height), formatBytes(image.size)]
    .filter(Boolean)
    .join(' · ')
}

const info = computed(() => {
  const ts = tracks.value
  if (!ts.length) return []
  const length = ts.reduce((s, t) => s + (t.info.length || 0), 0)
  const size = ts.reduce((s, t) => s + (t.info.filesize || 0), 0)
  const uniq = (f: (t: (typeof ts)[number]) => string | number) => {
    const set = new Set(ts.map(f))
    return set.size === 1 ? String([...set][0]) : '(various)'
  }
  const rowsOut: [string, string][] = [
    ['Codec', uniq((t) => t.info.codec + (t.info.codec_profile ? ` ${t.info.codec_profile}` : ''))],
    ['Bitrate', uniq((t) => (t.info.bitrate ? `${t.info.bitrate} kbps` : ''))],
    ['Sample rate', uniq((t) => (t.info.samplerate ? `${t.info.samplerate} Hz` : ''))],
    ['Channels', uniq((t) => t.info.channels)],
    ['Bits per sample', uniq((t) => t.info.bitspersample || '')],
    ['Length', formatLength(length)],
    ['File size', `${(size / 1024 / 1024).toFixed(2)} MB`],
    ['Embedded art', embeddedArt(ts)],
    ['Folder image', folderImage(ts)],
  ]
  if (ts.length === 1) {
    rowsOut.push(['Modified', ts[0].info.last_modified], ['Path', ts[0].path])
  }
  return rowsOut
})
</script>

<template>
  <section class="props">
    <div v-if="!tracks.length" class="empty muted">Select tracks to view and edit their tags.</div>
    <template v-else>
      <div class="meta">
        <table>
          <colgroup>
            <col style="width: 190px" />
            <col />
            <col style="width: 26px" />
          </colgroup>
          <thead>
            <tr>
              <th>Name</th>
              <th>Value — {{ tracks.length }} track{{ tracks.length > 1 ? 's' : '' }}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.field" :class="{ pending: row.pending, drastic: row.drastic }">
              <td class="name" title="Double-click to rename this field" @dblclick="startEdit(row, 'name')">
                <input
                  v-if="editing?.field === row.field && editing.part === 'name'"
                  ref="input"
                  v-model="editText"
                  @keydown="onKey"
                  @blur="commit"
                />
                <template v-else>{{ row.field }}</template>
              </td>
              <td
                class="value"
                :title="row.onDisk || undefined"
                @click="editing?.field !== row.field && startEdit(row)"
              >
                <input
                  v-if="editing?.field === row.field && editing.part === 'value'"
                  ref="input"
                  v-model="editText"
                  :placeholder="row.multiple ? '<multiple values> — type to replace them all' : ''"
                  @keydown="onKey"
                  @blur="commit"
                />
                <span v-else-if="row.multiple" class="multiple">
                  &lt;multiple values&gt;
                  <span v-if="row.present < tracks.length" class="muted"
                    >(missing in {{ tracks.length - row.present }})</span
                  >
                </span>
                <span v-else>{{ row.value }}</span>
              </td>
              <td>
                <button
                  v-if="row.present"
                  class="link remove"
                  title="Remove this field from the selected tracks"
                  @click="setField(row.field, null)"
                >
                  ✕
                </button>
              </td>
            </tr>
            <tr class="add">
              <td><input v-model="newName" placeholder="New field…" @keydown.enter="addField" /></td>
              <td><input v-model="newValue" placeholder="Value" @keydown.enter="addField" /></td>
              <td><button class="link" title="Add field" @click="addField">+</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <aside class="info">
        <table>
          <tbody>
            <tr v-for="[k, v] in info" :key="k">
              <th>{{ k }}</th>
              <td :class="{ mono: k === 'Path', lines: k === 'Embedded art' }">{{ v }}</td>
            </tr>
          </tbody>
        </table>
      </aside>
    </template>
  </section>
</template>

<style scoped>
.props {
  display: flex;
  min-height: 0;
  background: var(--panel);
  overflow: hidden;
}

.empty {
  padding: 16px;
}

.meta {
  flex: 1;
  overflow: auto;
  min-width: 0;
}

.meta table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
}

.meta th {
  position: sticky;
  top: 0;
  background: var(--panel-2);
  text-align: left;
  font-weight: 600;
  padding: 3px 6px;
  border-bottom: 1px solid var(--border);
  z-index: 1;
}

.meta td {
  padding: 1px 6px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  height: 23px;
}

.meta td.name {
  color: var(--muted);
  font-size: 12px;
}

.meta td.value {
  cursor: text;
}

.meta tr.pending td.value,
.meta tr.pending td.name {
  color: var(--pending);
}

.meta tr.pending {
  background: var(--pending-bg);
}

.meta tr.drastic td.value {
  color: var(--danger);
}

.meta input {
  width: 100%;
  padding: 0 4px;
}

.multiple {
  color: var(--muted);
  font-style: italic;
}

.remove {
  color: var(--muted);
  visibility: hidden;
}

tr:hover .remove {
  visibility: visible;
}

.add td {
  border-bottom: none;
  padding-top: 4px;
}

.info {
  width: 280px;
  flex: none;
  border-left: 1px solid var(--border);
  overflow: auto;
  padding: 4px 8px;
  font-size: 12px;
}

.info th {
  text-align: left;
  color: var(--muted);
  font-weight: normal;
  padding: 2px 8px 2px 0;
  vertical-align: top;
  white-space: nowrap;
}

.info td {
  word-break: break-all;
  padding: 2px 0;
}

.info td.lines {
  white-space: pre-line;
  word-break: normal;
}
</style>
