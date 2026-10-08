<script setup lang="ts">
import { computed, ref, toRaw } from 'vue'
import { errorText, runPreset, state, targetTracks, toast, updateSettings } from '../store'
import type { TagAction, TagPreset } from '../types'
import Modal from './Modal.vue'

const emit = defineEmits<{ close: [] }>()
const s = state.settings!

// `saved` is the name the preset had when the dialog opened, so a rename can follow mb_preset.
interface Draft extends TagPreset {
  saved: string
}

const drafts = ref<Draft[]>(
  s.tag_presets.map((p) => ({ name: p.name, saved: p.name, actions: structuredClone(toRaw(p.actions)) })),
)
const current = ref(0)
const draft = computed<Draft | undefined>(() => drafts.value[current.value])
const busy = ref(false)

const ACTION_LABELS: Record<TagAction['type'], string> = {
  format: 'Format field',
  remove: 'Remove fields',
  pictures_to_folder: 'Embedded pictures to folder image',
}

const problem = computed(() => {
  const names = drafts.value.map((d) => d.name.trim())
  if (names.some((n) => !n)) return 'Every preset needs a name'
  if (new Set(names).size !== names.length) return 'Two presets have the same name'
  return ''
})

function addPreset() {
  drafts.value.push({ name: `Preset ${drafts.value.length + 1}`, saved: '', actions: [] })
  current.value = drafts.value.length - 1
}

function deletePreset() {
  drafts.value.splice(current.value, 1)
  current.value = Math.max(0, current.value - 1)
}

function addAction(type: TagAction['type']) {
  const action: TagAction =
    type === 'format' ? { type, field: '', template: '' } : type === 'remove' ? { type, fields: [] } : { type }
  draft.value?.actions.push(action)
}

function moveAction(i: number, delta: number) {
  const actions = draft.value!.actions
  const j = i + delta
  if (j < 0 || j >= actions.length) return
  ;[actions[i], actions[j]] = [actions[j], actions[i]]
}

const splitFields = (text: string) =>
  text
    .split(/[;,]/)
    .map((f) => f.trim().toUpperCase())
    .filter(Boolean)

async function persist() {
  const presets = drafts.value.map((d) => ({ name: d.name.trim(), actions: d.actions }))
  const followed = drafts.value.find((d) => d.saved && d.saved === s.mb_preset)
  await updateSettings({ tag_presets: presets, mb_preset: followed ? followed.name.trim() : '' })
}

async function saveAndClose() {
  await persist()
  emit('close')
}

async function saveAndRun() {
  if (!draft.value) return
  busy.value = true
  try {
    await persist()
    await runPreset(
      { name: draft.value.name.trim(), actions: draft.value.actions },
      targetTracks.value.map((t) => t.path),
    )
    emit('close')
  } catch (e) {
    toast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal title="Tag presets" width="980px" height="80vh" @close="emit('close')">
    <div class="layout">
      <section class="list">
        <button
          v-for="(d, i) in drafts"
          :key="i"
          class="preset"
          :class="{ active: i === current }"
          @click="current = i"
        >
          <span class="ellipsis">{{ d.name || '(no name)' }}</span>
          <span class="muted">{{ d.actions.length }}</span>
        </button>
        <div class="row">
          <button @click="addPreset">New</button>
          <button :disabled="!draft" @click="deletePreset">Delete</button>
        </div>
      </section>

      <section v-if="draft" class="editor">
        <div class="row">
          <label for="p-name">Name</label>
          <input id="p-name" v-model="draft.name" class="grow" />
        </div>
        <p class="muted">
          Actions run in order, each on the result of the previous one, starting from the current unsaved values.
          Templates use foobar2000 title formatting, and an empty result removes the field.
        </p>
        <div class="actions">
          <div v-for="(a, i) in draft.actions" :key="i" class="action">
            <span class="muted">{{ i + 1 }}.</span>
            <span class="kind">{{ ACTION_LABELS[a.type] }}</span>
            <template v-if="a.type === 'format'">
              <input v-model="a.field" placeholder="FIELD" class="field mono" spellcheck="false" />
              <span>=</span>
              <input v-model="a.template" placeholder="%title%" class="grow mono" spellcheck="false" />
            </template>
            <input
              v-else-if="a.type === 'remove'"
              :value="a.fields.join('; ')"
              placeholder="COMMENT; MUSICBRAINZ_*"
              class="grow mono"
              spellcheck="false"
              @change="a.fields = splitFields(($event.target as HTMLInputElement).value)"
            />
            <span v-else class="grow muted">
              Saved as <code>{{ s.cover_name }}.jpg/png</code> when the folder has none. Files whose folder ends up
              without an image keep their pictures.
            </span>
            <button class="link" title="Move up" :disabled="i === 0" @click="moveAction(i, -1)">↑</button>
            <button class="link" title="Move down" :disabled="i === draft.actions.length - 1" @click="moveAction(i, 1)">
              ↓
            </button>
            <button class="link" title="Remove action" @click="draft.actions.splice(i, 1)">✕</button>
          </div>
        </div>
        <div class="row">
          <button v-for="(label, type) in ACTION_LABELS" :key="type" @click="addAction(type)">+ {{ label }}</button>
        </div>
      </section>
      <p v-else class="muted">No presets yet.</p>
    </div>

    <template #footer>
      <span class="grow" :class="problem ? 'error' : 'muted'">
        {{ problem || `Runs on ${targetTracks.length}${state.selected.size ? ' selected' : ''} track(s)` }}
      </span>
      <button @click="emit('close')">Cancel</button>
      <button :disabled="!!problem" @click="saveAndClose">Save</button>
      <button class="primary" :disabled="!!problem || !draft || !targetTracks.length || busy" @click="saveAndRun">
        Save and run
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 14px;
  flex: 1;
  min-height: 0;
}

.list,
.editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  min-width: 0;
}

.editor {
  overflow: auto;
}

.preset {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  text-align: left;
}

.preset.active {
  background: var(--select);
}

p {
  margin: 0;
  font-size: 12px;
}

.error {
  color: var(--danger);
}

.actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.action {
  display: flex;
  align-items: center;
  gap: 6px;
}

.kind {
  flex: none;
  width: 130px;
  color: var(--muted);
  font-size: 12px;
}

.field {
  width: 150px;
}

.action span.grow {
  font-size: 12px;
}
</style>
