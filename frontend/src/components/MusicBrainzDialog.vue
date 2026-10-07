<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import {
  displayValue,
  errorText,
  firstValue,
  mergedTags,
  reloadTracks,
  stage,
  state,
  targetTracks,
  toast,
  updateSettings,
} from '../store'
import type { FieldChange } from '../store'
import type { MbMedium, MbRelease, MbReleaseSummary, MbTrack, Track } from '../types'
import { arraysEqual, basename, dirname, formatLength } from '../util'
import Modal from './Modal.vue'

const emit = defineEmits<{ close: [] }>()
const s = state.settings!
const locals: Track[] = [...targetTracks.value]

function mostCommon(field: string, fallback = ''): string {
  const counts = new Map<string, number>()
  for (const t of locals) {
    const v = firstValue(t, field)
    if (v) counts.set(v, (counts.get(v) ?? 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? fallback
}

/**
 * Guess "Artist - Album" from a folder name such as "Artist - 2001 - Album [FLAC]".
 */
function fromFolderName(): { artist: string; album: string } {
  const name = basename(dirname(locals[0]?.path ?? ''))
    .replace(/\s*[[(][^\])]*[\])]\s*$/g, '')
    .replace(/\s*[[(][^\])]*[\])]\s*$/g, '')
  const parts = name.split(' - ').map((p) => p.trim())
  if (parts.length >= 3 && /^\d{4}$/.test(parts[1])) return { artist: parts[0], album: parts.slice(2).join(' - ') }
  if (parts.length >= 2) return { artist: parts[0], album: parts.slice(1).join(' - ') }
  return { artist: '', album: name }
}

const guessed = mostCommon('ALBUM') ? { artist: '', album: '' } : fromFolderName()
const artist = ref(mostCommon('ALBUM ARTIST') || mostCommon('ARTIST') || guessed.artist)
const album = ref(mostCommon('ALBUM') || guessed.album)
const query = ref(mostCommon('MUSICBRAINZ_ALBUMID'))
const results = ref<MbReleaseSummary[]>([])
const total = ref(0)
const searching = ref(false)
const searchError = ref('')
const lastQuery = ref('')

const selectedId = ref('')
const release = ref<MbRelease | null>(null)
const loadingRelease = ref(false)
const releaseError = ref('')

const dateMode = ref(s.mb_date)
const groups = ref<string[]>([...s.mb_groups])
const discForSingle = ref(s.mb_disc_for_single)
const mapping = ref<string[]>([])
const disabled = ref<Set<string>>(new Set())
const showUnchanged = ref(false)

const saveCover = ref(s.mb_cover)
const coverSize = ref(s.mb_cover_size)
const coverOverwrite = ref(s.mb_cover_overwrite)
const applying = ref(false)

// --- search ------------------------------------------------------------------------

async function search(append = false) {
  searching.value = true
  searchError.value = ''
  try {
    const res = await api.mbSearch({
      artist: artist.value,
      album: album.value,
      query: query.value,
      offset: append ? results.value.length : 0,
    })
    results.value = append ? [...results.value, ...res.releases] : res.releases
    total.value = res.count
    lastQuery.value = res.query ?? ''
    if (!append && results.value.length) void select(results.value[0].id)
  } catch (e) {
    searchError.value = errorText(e)
  } finally {
    searching.value = false
  }
}

function searchByFields() {
  query.value = ''
  void search()
}

const trackMatch = (r: MbReleaseSummary) =>
  r.track_count === locals.length || r.media.some((m) => m.track_count === locals.length)

function onResultsKey(e: KeyboardEvent) {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  e.preventDefault()
  const i = results.value.findIndex((r) => r.id === selectedId.value)
  const next = results.value[Math.max(0, Math.min(results.value.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))]
  if (next) void select(next.id)
}

// --- release -----------------------------------------------------------------------

async function loadRelease(id: string, remap: boolean) {
  loadingRelease.value = true
  releaseError.value = ''
  try {
    const rel = await api.mbRelease(id, {
      date: dateMode.value,
      groups: groups.value.join(','),
      disc_for_single: discForSingle.value,
      padding: s.track_padding,
    })
    if (selectedId.value !== id) return
    release.value = rel
    if (remap) mapping.value = autoMap(rel)
  } catch (e) {
    releaseError.value = errorText(e)
  } finally {
    loadingRelease.value = false
  }
}

async function select(id: string) {
  if (selectedId.value === id) return
  selectedId.value = id
  release.value = null
  await loadRelease(id, true)
}

watch([dateMode, groups, discForSingle], () => {
  if (selectedId.value) void loadRelease(selectedId.value, false)
})

const keyOf = (m: MbMedium, t: MbTrack) => `${m.position}-${t.position}`

const flat = computed(() => {
  const map = new Map<string, { medium: MbMedium; track: MbTrack }>()
  for (const m of release.value?.media ?? []) for (const t of m.tracks) map.set(keyOf(m, t), { medium: m, track: t })
  return map
})

function discHint(t: Track): number {
  const tag = parseInt(firstValue(t, 'DISCNUMBER'), 10)
  if (tag) return tag
  const m = /(?:cd|dis[ck])\s*(\d+)/i.exec(basename(dirname(t.path)))
  return m ? parseInt(m[1], 10) : 0
}

/**
 * Map local tracks to release tracks: by disc/track tags, then by medium size, then in order.
 */
function autoMap(rel: MbRelease): string[] {
  const media = rel.media
  const byTags = locals.map((t) => {
    const n = parseInt(firstValue(t, 'TRACKNUMBER'), 10)
    const disc = discHint(t)
    const medium = disc ? media.find((m) => m.position === disc) : media.length === 1 ? media[0] : undefined
    const track = medium?.tracks.find((x) => x.position === n)
    return medium && track ? keyOf(medium, track) : ''
  })
  if (byTags.every(Boolean) && new Set(byTags).size === byTags.length) return byTags

  const totalTracks = media.reduce((sum, m) => sum + m.tracks.length, 0)
  if (media.length > 1 && locals.length !== totalTracks) {
    const candidates = media.filter((m) => m.tracks.length === locals.length)
    const hinted = candidates.find((m) => m.position === discHint(locals[0])) ?? candidates[0]
    if (hinted) return locals.map((_, i) => keyOf(hinted, hinted.tracks[i]))
  }
  const ordered = media.flatMap((m) => m.tracks.map((t) => keyOf(m, t)))
  return locals.map((_, i) => ordered[i] ?? '')
}

// --- diff ----------------------------------------------------------------------------

const allFields = computed(() => {
  const set = new Set<string>()
  for (const key of mapping.value) {
    const entry = key ? flat.value.get(key) : undefined
    if (entry) Object.keys(entry.track.tags).forEach((f) => set.add(f))
  }
  return [...set]
})

const rows = computed(() =>
  locals.map((track, i) => {
    const entry = mapping.value[i] ? flat.value.get(mapping.value[i]) : undefined
    const current = mergedTags(track)
    const changes = entry
      ? Object.entries(entry.track.tags)
          .filter(([f]) => !disabled.value.has(f))
          .map(([field, next]) => ({ field, old: current[field], next, changed: !arraysEqual(current[field], next) }))
      : []
    const lengthDiff = entry && entry.track.length ? Math.round(track.info.length - entry.track.length) : 0
    return { track, entry, changes, changed: changes.filter((c) => c.changed).length, lengthDiff }
  }),
)

// Fields proposed with the same value for every assigned file, shown once as an album block.
const commonFields = computed(() => {
  const mapped = rows.value.filter((r) => r.entry)
  if (mapped.length < 2) return new Set<string>()
  const first = mapped[0].entry!.track.tags
  return new Set(Object.keys(first).filter((f) => mapped.every((r) => arraysEqual(r.entry!.track.tags[f], first[f]))))
})

const albumRows = computed(() => {
  const mapped = rows.value.filter((r) => r.entry)
  return [...commonFields.value]
    .filter((f) => !disabled.value.has(f))
    .map((field) => {
      const olds = mapped.map((r) => displayValue(mergedTags(r.track)[field]))
      const next = mapped[0].entry!.track.tags[field]
      const multiple = new Set(olds).size > 1
      const changed = mapped.some((r) => r.changes.find((c) => c.field === field)?.changed)
      return { field, old: multiple ? '<multiple values>' : olds[0], next, changed, multiple }
    })
})

const changedFiles = computed(() => rows.value.filter((r) => r.changed).length)
const changedValues = computed(() => rows.value.reduce((sum, r) => sum + r.changed, 0))
const unassigned = computed(() => {
  const used = new Set(mapping.value)
  return [...flat.value.keys()].filter((k) => !used.has(k))
})
const duplicates = computed(() => {
  const seen = new Set<string>()
  const dup = new Set<string>()
  for (const k of mapping.value) {
    if (!k) continue
    if (seen.has(k)) dup.add(k)
    seen.add(k)
  }
  return dup
})

function toggleField(field: string) {
  const next = new Set(disabled.value)
  if (next.has(field)) next.delete(field)
  else next.add(field)
  disabled.value = next
}

function trackLabel(m: MbMedium, t: MbTrack) {
  const disc = (release.value?.media.length ?? 0) > 1 ? `${m.position}.` : ''
  return `${disc}${String(t.position).padStart(2, '0')}  ${t.title}  (${formatLength(t.length)})`
}

const labels = (r: { labels: MbReleaseSummary['labels'] }) =>
  r.labels
    .map((l) => [l.name, l.catno].filter(Boolean).join(' '))
    .filter(Boolean)
    .join(', ')

// --- apply ---------------------------------------------------------------------------

async function apply() {
  if (!release.value) return
  const changes: FieldChange[] = []
  for (const r of rows.value) {
    for (const c of r.changes) if (c.changed) changes.push({ path: r.track.path, field: c.field, values: c.next })
  }
  const summary = `Staged ${changes.length} change(s) on ${changedFiles.value} file(s). Save to write them.`
  stage(changes)
  void updateSettings({
    mb_date: dateMode.value,
    mb_groups: groups.value,
    mb_disc_for_single: discForSingle.value,
    mb_cover: saveCover.value,
    mb_cover_size: coverSize.value,
    mb_cover_overwrite: coverOverwrite.value,
  })
  if (saveCover.value && release.value.cover_art) {
    applying.value = true
    try {
      const dirs = [...new Set(rows.value.filter((r) => r.entry).map((r) => dirname(r.track.path)))]
      const res = await api.mbCover({
        release_id: release.value.id,
        dirs,
        size: coverSize.value,
        overwrite: coverOverwrite.value,
      })
      const ok = res.results.filter((r) => r.ok).length
      const skipped = res.results.filter((r) => !r.ok)
      toast(
        `Cover saved in ${ok} folder(s)${skipped.length ? `, skipped ${skipped.length}: ${skipped[0].error}` : ''}`,
        skipped.length && !ok ? 'error' : 'success',
      )
      await reloadTracks()
      state.treeVersion++
    } catch (e) {
      toast(`Cover not saved: ${errorText(e)}`, 'error')
    } finally {
      applying.value = false
    }
  }
  toast(summary, 'info')
  emit('close')
}

onMounted(() => {
  if (artist.value || album.value || query.value) void search()
})
</script>

<template>
  <Modal title="MusicBrainz lookup" width="1360px" height="92vh" @close="emit('close')">
    <div class="layout">
      <section class="left">
        <form class="search" @submit.prevent="searchByFields">
          <input v-model="artist" placeholder="Artist" />
          <input v-model="album" placeholder="Album" />
          <button class="primary" type="submit" :disabled="searching">Search</button>
        </form>
        <form class="search" @submit.prevent="search()">
          <input v-model="query" placeholder="MBID, musicbrainz.org URL or Lucene query" class="mono" />
          <button type="submit" :disabled="searching || !query.trim()">Go</button>
        </form>
        <p v-if="searchError" class="error">{{ searchError }}</p>
        <p v-else class="muted small">
          {{ searching ? 'Searching…' : `${total} release(s)` }} · {{ locals.length }} local track(s)
          <span v-if="lastQuery" class="mono" :title="lastQuery">· {{ lastQuery }}</span>
        </p>
        <div class="results" tabindex="0" @keydown="onResultsKey">
          <div
            v-for="r in results"
            :key="r.id"
            class="result"
            :class="{ active: r.id === selectedId }"
            @click="select(r.id)"
          >
            <div class="row">
              <strong class="grow ellipsis">{{ r.title }}</strong>
              <span class="chip" :class="trackMatch(r) ? 'ok' : 'muted'">{{ r.track_count }} tr</span>
            </div>
            <div class="ellipsis">
              {{ r.artist }}<span v-if="r.disambiguation" class="muted"> ({{ r.disambiguation }})</span>
            </div>
            <div class="muted small ellipsis">
              {{ [r.date, r.country, r.format].filter(Boolean).join(' · ') }}
            </div>
            <div class="muted small ellipsis">
              {{
                [labels(r), r.barcode, [r.type, ...r.secondary_types].filter(Boolean).join(' + '), r.status]
                  .filter(Boolean)
                  .join(' · ')
              }}
            </div>
          </div>
          <button v-if="results.length < total" class="more" :disabled="searching" @click="search(true)">
            Load more
          </button>
        </div>
      </section>

      <section class="right">
        <p v-if="releaseError" class="error">{{ releaseError }}</p>
        <p v-else-if="!release" class="muted">{{ loadingRelease ? 'Loading release…' : 'Pick a release.' }}</p>
        <template v-if="release">
          <header class="release">
            <img
              v-if="release.cover_art"
              :src="`https://coverartarchive.org/release/${release.id}/front-250`"
              alt=""
              class="cover"
              @error="($event.target as HTMLImageElement).style.display = 'none'"
            />
            <div class="grow">
              <h3>{{ release.title }}</h3>
              <div>{{ release.artist }}</div>
              <div class="muted small">
                {{
                  [release.date, release.country, release.format, labels(release), release.barcode]
                    .filter(Boolean)
                    .join(' · ')
                }}
              </div>
              <a :href="`https://musicbrainz.org/release/${release.id}`" target="_blank" rel="noopener" class="small">
                Open on MusicBrainz ↗
              </a>
            </div>
          </header>

          <div class="row options">
            <label>
              Date
              <select v-model="dateMode">
                <option value="year">Year only</option>
                <option value="full">Full date</option>
              </select>
            </label>
            <label><input v-model="groups" type="checkbox" value="basic" /> Basic</label>
            <label><input v-model="groups" type="checkbox" value="release" /> Release info</label>
            <label><input v-model="groups" type="checkbox" value="ids" /> MusicBrainz IDs</label>
            <label><input v-model="discForSingle" type="checkbox" /> Disc number on single-disc releases</label>
            <span class="grow" />
            <label><input v-model="showUnchanged" type="checkbox" /> Show unchanged</label>
          </div>

          <div class="fields">
            <button
              v-for="f in allFields"
              :key="f"
              class="field-chip"
              :class="{ off: disabled.has(f) }"
              :title="disabled.has(f) ? 'Click to write this field' : 'Click to leave this field untouched'"
              @click="toggleField(f)"
            >
              {{ f }}
            </button>
          </div>

          <div class="diff">
            <div v-if="albumRows.length" class="trow album">
              <div class="row thead">
                <strong>Album</strong>
                <span class="muted">same for all {{ rows.filter((r) => r.entry).length }} assigned files</span>
              </div>
              <table>
                <template v-for="c in albumRows" :key="c.field">
                  <tr v-if="c.changed || showUnchanged" :class="{ same: !c.changed }">
                    <td class="f">{{ c.field }}</td>
                    <td class="old" :class="{ multi: c.multiple }">{{ c.old || '—' }}</td>
                    <td class="arrow">→</td>
                    <td class="new">{{ displayValue(c.next) }}</td>
                  </tr>
                </template>
              </table>
            </div>
            <div v-for="(r, i) in rows" :key="r.track.path" class="trow" :class="{ unmapped: !r.entry }">
              <div class="row thead">
                <span class="mono ellipsis file" :title="r.track.path">{{ basename(r.track.path) }}</span>
                <span class="muted">{{ formatLength(r.track.info.length) }}</span>
                <span>→</span>
                <select v-model="mapping[i]" class="grow" :class="{ dup: duplicates.has(mapping[i]) }">
                  <option value="">— leave untouched —</option>
                  <optgroup
                    v-for="m in release.media"
                    :key="m.position"
                    :label="`Disc ${m.position}${m.format ? ' · ' + m.format : ''}${m.title ? ' · ' + m.title : ''}`"
                  >
                    <option v-for="t in m.tracks" :key="t.id" :value="keyOf(m, t)">{{ trackLabel(m, t) }}</option>
                  </optgroup>
                </select>
                <span v-if="Math.abs(r.lengthDiff) > 5" class="chip warn" title="Length differs from MusicBrainz">
                  {{ r.lengthDiff > 0 ? '+' : '' }}{{ r.lengthDiff }}s
                </span>
                <span v-if="r.entry" class="chip" :class="r.changed ? 'warn' : 'muted'">{{ r.changed }} change(s)</span>
              </div>
              <table v-if="r.entry">
                <template v-for="c in r.changes" :key="c.field">
                  <tr v-if="!commonFields.has(c.field) && (c.changed || showUnchanged)" :class="{ same: !c.changed }">
                    <td class="f">{{ c.field }}</td>
                    <td class="old">{{ displayValue(c.old) || '—' }}</td>
                    <td class="arrow">→</td>
                    <td class="new">{{ displayValue(c.next) }}</td>
                  </tr>
                </template>
              </table>
            </div>
            <p v-if="unassigned.length" class="muted small">
              {{ unassigned.length }} release track(s) not assigned to a file.
            </p>
          </div>
        </template>
      </section>
    </div>

    <template #footer>
      <label
        :class="{ muted: !release?.cover_art }"
        :title="release?.cover_art ? '' : 'No front cover on the Cover Art Archive'"
      >
        <input v-model="saveCover" type="checkbox" :disabled="!release?.cover_art" />
        Save cover as <code>{{ state.settings?.cover_name || 'folder' }}.jpg/png</code>
      </label>
      <select v-model="coverSize" :disabled="!saveCover">
        <option value="500">500 px</option>
        <option value="1200">1200 px</option>
        <option value="original">Original</option>
      </select>
      <label title="Replace an existing folder image">
        <input v-model="coverOverwrite" type="checkbox" :disabled="!saveCover" /> replace existing
      </label>
      <span class="grow muted">
        <template v-if="release">{{ changedValues }} change(s) on {{ changedFiles }} file(s)</template>
        <span v-if="duplicates.size" class="error"> · a release track is assigned twice</span>
      </span>
      <button @click="emit('close')">Cancel</button>
      <button class="primary" :disabled="!release || !changedFiles || applying" @click="apply">Apply</button>
    </template>
  </Modal>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 14px;
  flex: 1;
  min-height: 0;
}

.left,
.right {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  min-width: 0;
}

.search {
  display: flex;
  gap: 6px;
}

.search input {
  flex: 1;
}

.small {
  font-size: 12px;
}

p {
  margin: 0;
}

.error {
  color: var(--danger);
}

.results {
  flex: 1;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 4px;
  outline: none;
}

.result {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
}

.result:hover {
  background: var(--panel-2);
}

.result.active {
  background: var(--select);
}

.more {
  margin: 8px;
}

.release {
  display: flex;
  gap: 12px;
}

.release h3 {
  margin: 0 0 2px;
  font-size: 16px;
}

.cover {
  width: 96px;
  height: 96px;
  object-fit: cover;
  border-radius: 3px;
  border: 1px solid var(--border);
}

.options {
  flex-wrap: wrap;
}

.fields {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.field-chip {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 10px;
  background: var(--select);
  border-color: transparent;
}

.field-chip.off {
  background: none;
  border-color: var(--border);
  color: var(--muted);
  text-decoration: line-through;
}

.diff {
  flex: 1;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 4px;
}

.trow {
  border-bottom: 1px solid var(--border);
  padding: 4px 8px 6px;
}

.trow.unmapped {
  opacity: 0.6;
}

.thead {
  margin-bottom: 2px;
}

.file {
  max-width: 300px;
  font-weight: 600;
}

select.dup {
  outline: 2px solid var(--danger);
}

.trow table {
  border-collapse: collapse;
  width: 100%;
  font-size: 12px;
}

.trow td {
  padding: 1px 6px;
  vertical-align: top;
}

td.f {
  width: 210px;
  color: var(--muted);
}

td.old {
  width: 40%;
  color: var(--muted);
  text-decoration: line-through;
  word-break: break-word;
}

td.arrow {
  width: 20px;
  color: var(--muted);
}

td.new {
  color: var(--pending);
  word-break: break-word;
}

tr.same td.old {
  text-decoration: none;
}

td.old.multi {
  text-decoration: none;
  font-style: italic;
}

.trow.album {
  background: var(--panel-2);
}

tr.same td.new {
  color: var(--muted);
}
</style>
