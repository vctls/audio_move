<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, type FileOpRequest } from '../api'
import { errorText, pendingCount, relocateTracks, save, state, targetTracks, toast, updateSettings } from '../store'
import type { ExecuteResult, HistoryEntry, Operation, Plan, PlanItem } from '../types'
import { debounce, dirname, relativeTo } from '../util'
import FolderPicker from './FolderPicker.vue'
import Modal from './Modal.vue'

const emit = defineEmits<{ close: [] }>()
const s = state.settings!

const paths = ref(targetTracks.value.map((t) => t.path))
const operation = ref<Operation>(s.operation)
const destination = ref(s.destination || state.config?.roots[0]?.path || '')
const pattern = ref(s.pattern)
const moveOther = ref(s.move_other_files)
const removeEmpty = ref(s.remove_empty_dirs)

const plan = ref<Plan | null>(null)
const previewError = ref('')
const previewing = ref(false)
const running = ref(false)
const result = ref<ExecuteResult | null>(null)
const picking = ref(false)
const showHelp = ref(false)
const history = ref<HistoryEntry[]>([])

const request = computed<FileOpRequest>(() => ({
  paths: paths.value,
  pattern: pattern.value,
  operation: operation.value,
  destination: destination.value,
  move_other_files: moveOther.value,
  remove_empty_dirs: removeEmpty.value,
  base_dir: state.folder || null,
}))

const tracksPlan = computed(() => plan.value?.items.filter((i) => i.kind === 'track') ?? [])
const othersPlan = computed(() => plan.value?.items.filter((i) => i.kind === 'other') ?? [])
const runnable = computed(() => plan.value?.items.filter((i) => i.status === 'ok').length ?? 0)
const problems = computed(() => plan.value?.items.filter((i) => !['ok', 'unchanged'].includes(i.status)).length ?? 0)
const verb = computed(() => ({ move: 'Move', copy: 'Copy', rename: 'Rename' })[operation.value])

const refresh = debounce(async () => {
  if (!pattern.value.trim() || (operation.value !== 'rename' && !destination.value)) {
    plan.value = null
    return
  }
  previewing.value = true
  try {
    plan.value = await api.preview(request.value)
    previewError.value = ''
  } catch (e) {
    previewError.value = errorText(e)
    plan.value = null
  } finally {
    previewing.value = false
  }
}, 300)

watch(request, refresh)
watch([pattern, operation, destination, moveOther, removeEmpty], () => (result.value = null))

async function loadHistory() {
  try {
    history.value = (await api.history()).slice(0, 5)
  } catch {
    history.value = []
  }
}

onMounted(() => {
  refresh()
  void loadHistory()
})

function srcLabel(item: PlanItem) {
  const root = state.config?.roots.find((r) => item.src.startsWith(r.path + '/'))
  return relativeTo(
    item.src,
    state.folder && item.src.startsWith(state.folder + '/') ? state.folder : (root?.path ?? ''),
  )
}

function dstParts(item: PlanItem): [string, string] {
  if (!item.dst) return ['', '']
  const base = operation.value === 'rename' ? dirname(item.src) : destination.value
  const rel = relativeTo(item.dst, base)
  const cut = rel.lastIndexOf('/')
  return cut >= 0 ? [rel.slice(0, cut + 1), rel.slice(cut + 1)] : ['', rel]
}

const statusLabel: Record<PlanItem['status'], string> = {
  ok: 'ok',
  unchanged: 'same',
  exists: 'exists',
  duplicate: 'duplicate',
  error: 'error',
}
const statusClass = (st: PlanItem['status']) => (st === 'ok' ? 'ok' : st === 'unchanged' ? 'muted' : 'err')

function savePreset() {
  const p = pattern.value.trim()
  if (!p || s.patterns.includes(p)) return
  void updateSettings({ patterns: [...(state.settings?.patterns ?? []), p] })
  toast('Pattern saved', 'success', 1500)
}

function deletePreset() {
  void updateSettings({ patterns: (state.settings?.patterns ?? []).filter((p) => p !== pattern.value) })
}

async function run() {
  if (pendingCount.value) return
  running.value = true
  try {
    const res = await api.execute(request.value)
    result.value = res
    const moves: Record<string, string> = {}
    for (const d of res.done) if (d.kind === 'track') moves[d.src] = d.dst
    if (operation.value !== 'copy') {
      await relocateTracks(moves)
      paths.value = paths.value.map((p) => moves[p] ?? p)
      const dirs = new Set(Object.values(moves).map(dirname))
      if (dirs.size === 1 && state.folder && !paths.value.some((p) => p.startsWith(state.folder + '/'))) {
        state.folder = [...dirs][0]
      }
    }
    state.treeVersion++
    void updateSettings({
      operation: operation.value,
      destination: destination.value,
      pattern: pattern.value,
      move_other_files: moveOther.value,
      remove_empty_dirs: removeEmpty.value,
    })
    const failed = res.plan.items.filter((i) => i.status === 'error').length
    toast(
      `${verb.value}d ${res.done.length} item(s)${failed ? `, ${failed} failed` : ''}`,
      failed ? 'error' : 'success',
    )
    await loadHistory()
  } catch (e) {
    toast(errorText(e), 'error')
  } finally {
    running.value = false
  }
}

async function undoEntry(entry: HistoryEntry) {
  try {
    const res = await api.undo(entry.id)
    const moves: Record<string, string> = {}
    for (const r of res.restored) if (r.kind === 'track') moves[r.dst] = r.src
    await relocateTracks(moves)
    paths.value = paths.value.map((p) => moves[p] ?? p)
    if (state.folder && !paths.value.some((p) => p.startsWith(state.folder + '/'))) {
      const dirs = new Set(Object.values(moves).map(dirname))
      if (dirs.size === 1) state.folder = [...dirs][0]
    }
    state.treeVersion++
    toast(
      `Restored ${res.restored.length} item(s)${res.errors.length ? `, ${res.errors.length} failed: ${res.errors[0].error}` : ''}`,
      res.errors.length ? 'error' : 'success',
    )
    result.value = null
    await loadHistory()
    refresh()
  } catch (e) {
    toast(errorText(e), 'error')
  }
}
</script>

<template>
  <Modal title="Move / copy / rename files" width="1100px" height="88vh" @close="emit('close')">
    <div class="form">
      <label>Operation</label>
      <div class="row">
        <label><input v-model="operation" type="radio" value="move" /> Move</label>
        <label><input v-model="operation" type="radio" value="copy" /> Copy</label>
        <label><input v-model="operation" type="radio" value="rename" /> Rename in place</label>
        <span class="muted">— {{ paths.length }} track(s)</span>
      </div>

      <label>Destination</label>
      <div class="row">
        <input v-model="destination" class="grow mono" :disabled="operation === 'rename'" spellcheck="false" />
        <button :disabled="operation === 'rename'" @click="picking = true">Browse…</button>
      </div>

      <label>File name pattern</label>
      <div class="col">
        <div class="row">
          <input v-model="pattern" class="grow mono" list="move-patterns" spellcheck="false" />
          <datalist id="move-patterns">
            <option v-for="p in state.settings?.patterns ?? []" :key="p" :value="p" />
          </datalist>
          <button title="Save this pattern in the list" @click="savePreset">Save</button>
          <button title="Remove this pattern from the list" @click="deletePreset">Delete</button>
          <button class="link" @click="showHelp = !showHelp">{{ showHelp ? 'Hide help' : 'Syntax' }}</button>
        </div>
        <div v-if="showHelp" class="help muted">
          foobar2000 title formatting. <code>/</code> creates folders and the extension is added for you.
          <code>%album artist%</code> falls back to <code>%artist%</code>; <code>%tracknumber%</code> is zero-padded,
          <code>%track number%</code> is not; <code>%year%</code> reads YEAR or the year of DATE; <code>%codec%</code>,
          <code>%bitrate%</code>, <code>%filename%</code>, <code>%directoryname%</code>. <code>[...]</code> is dropped
          when the fields inside are missing, so literal brackets need quotes: <code>'['$caps(%codec%)']'</code>.
          Functions: <code>$if</code>, <code>$if2</code>, <code>$caps</code>, <code>$upper</code>, <code>$lower</code>,
          <code>$num(x,2)</code>, <code>$left</code>, <code>$replace(a,b,c)</code>, <code>$ascii</code>,
          <code>$year(%date%)</code>, <code>$swapprefix</code>, <code>$meta(field,0)</code>…
        </div>
      </div>

      <label>Options</label>
      <div class="row">
        <label :class="{ muted: operation === 'rename' }">
          <input v-model="moveOther" type="checkbox" />
          Also {{ operation === 'copy' ? 'copy' : 'move' }} other files from the source folders (covers, logs, scans…)
        </label>
        <label v-if="operation !== 'copy'">
          <input v-model="removeEmpty" type="checkbox" /> Remove emptied source folders
        </label>
      </div>
    </div>

    <div v-if="pendingCount" class="banner">
      {{ pendingCount }} file(s) have unsaved tag changes. The preview uses the tags saved on disk.
      <button class="primary" @click="save()">Save tags now</button>
    </div>
    <p v-if="previewError" class="banner error">{{ previewError }}</p>
    <ul v-if="plan?.warnings.length" class="warnings">
      <li v-for="w in plan.warnings" :key="w">{{ w }}</li>
    </ul>

    <div class="preview">
      <table class="grid">
        <thead>
          <tr>
            <th style="width: 44%">Source</th>
            <th>Destination{{ operation === 'rename' ? ' (relative to its folder)' : '' }}</th>
            <th style="width: 80px">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in tracksPlan" :key="item.src" :title="item.message">
            <td class="mono cell">{{ srcLabel(item) }}</td>
            <td class="mono cell">
              <template v-if="item.dst">
                <span class="muted">{{ dstParts(item)[0] }}</span
                >{{ dstParts(item)[1] }}
              </template>
              <template v-else>{{ item.message }}</template>
            </td>
            <td>
              <span class="chip" :class="statusClass(item.status)">{{ statusLabel[item.status] }}</span>
            </td>
          </tr>
          <tr v-if="othersPlan.length" class="section">
            <td colspan="3">Other files</td>
          </tr>
          <tr v-for="item in othersPlan" :key="item.src" :title="item.message">
            <td class="mono cell">{{ srcLabel(item) }}</td>
            <td class="mono cell">
              <span class="muted">{{ dstParts(item)[0] }}</span
              >{{ dstParts(item)[1] }}
            </td>
            <td>
              <span class="chip" :class="statusClass(item.status)">{{ statusLabel[item.status] }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="previewing && !plan" class="muted pad">Computing preview…</p>
    </div>

    <div v-if="history.length" class="history">
      <strong>Recent operations</strong>
      <div v-for="h in history" :key="h.id" class="row">
        <span class="muted">{{ h.time.replace('T', ' ') }}</span>
        <span>{{ h.operation }} · {{ h.count }} item(s)</span>
        <span class="mono ellipsis grow muted">{{ h.sample ? relativeTo(h.sample.dst, destination) : '' }}</span>
        <span v-if="h.undone" class="chip muted">undone</span>
        <button v-else @click="undoEntry(h)">Undo</button>
      </div>
    </div>

    <template #footer>
      <span class="grow muted">
        <template v-if="result"
          >Done: {{ result.done.length }} item(s), {{ result.removed_dirs.length }} empty folder(s) removed.</template
        >
        <template v-else-if="plan">
          {{ runnable }} item(s) to {{ operation }}<template v-if="problems">, {{ problems }} skipped</template>
        </template>
      </span>
      <button @click="emit('close')">Close</button>
      <button class="primary" :disabled="!runnable || running || pendingCount > 0 || !!result" @click="run">
        {{ running ? 'Working…' : `${verb} ${runnable} item(s)` }}
      </button>
    </template>
    <FolderPicker v-if="picking" :initial="destination" @pick="destination = $event" @close="picking = false" />
  </Modal>
</template>

<style scoped>
.form {
  display: grid;
  grid-template-columns: 130px 1fr;
  gap: 8px 12px;
  align-items: center;
}

.col {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.help {
  font-size: 12px;
  line-height: 1.6;
}

.banner {
  background: var(--pending-bg);
  color: var(--pending);
  border-radius: 4px;
  padding: 6px 10px;
  margin: 0;
  display: flex;
  gap: 12px;
  align-items: center;
}

.banner.error {
  color: var(--danger);
}

.warnings {
  margin: 0;
  color: var(--warn);
}

.preview {
  flex: 1;
  min-height: 160px;
  overflow: auto;
  border: 1px solid var(--border);
}

.cell {
  overflow-wrap: anywhere;
}

.section td {
  background: var(--panel-2);
  font-weight: 600;
}

.pad {
  padding: 8px;
}

.history {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
</style>
