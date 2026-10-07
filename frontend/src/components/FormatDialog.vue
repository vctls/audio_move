<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import {
  displayValue,
  errorText,
  fieldValues,
  mergedTags,
  parseInput,
  stage,
  state,
  targetTracks,
  updateSettings,
} from '../store'
import { basename, debounce } from '../util'
import Modal from './Modal.vue'

const emit = defineEmits<{ close: [] }>()

const field = ref('TITLE')
const template = ref(state.settings?.format_presets[0] ?? '$caps2(%title%)')
const results = ref<string[]>([])
const error = ref('')

const knownFields = computed(() => {
  const set = new Set<string>()
  for (const t of state.tracks) Object.keys(mergedTags(t)).forEach((k) => set.add(k))
  return [...set].sort()
})

const changed = computed(
  () => targetTracks.value.filter((t, i) => results.value[i] !== undefined && results.value[i] !== current(t)).length,
)

function current(t: (typeof state.tracks)[number]) {
  return displayValue(fieldValues(t, field.value.trim().toUpperCase()))
}

const refresh = debounce(async () => {
  try {
    const res = await api.format(
      template.value,
      targetTracks.value.map((t) => ({ path: t.path, tags: mergedTags(t), info: t.info })),
    )
    results.value = res.results
    error.value = ''
  } catch (e) {
    error.value = errorText(e)
  }
}, 200)

watch(template, refresh)
onMounted(refresh)

function apply() {
  const name = field.value.trim().toUpperCase()
  if (!name) return
  stage(
    targetTracks.value.map((t, i) => {
      const values = parseInput(name, results.value[i] ?? '')
      return { path: t.path, field: name, values: values.length ? values : null }
    }),
  )
  const presets = [template.value, ...(state.settings?.format_presets ?? []).filter((p) => p !== template.value)]
  void updateSettings({ format_presets: presets.slice(0, 20) })
  emit('close')
}
</script>

<template>
  <Modal title="Format field from other fields" width="900px" @close="emit('close')">
    <div class="row">
      <label>Field</label>
      <input v-model="field" list="format-fields" style="width: 180px" spellcheck="false" />
      <datalist id="format-fields">
        <option v-for="f in knownFields" :key="f" :value="f" />
      </datalist>
      <label>=</label>
      <input v-model="template" class="grow mono" list="format-presets" spellcheck="false" />
      <datalist id="format-presets">
        <option v-for="p in state.settings?.format_presets ?? []" :key="p" :value="p" />
      </datalist>
    </div>
    <p class="muted">
      foobar2000 title formatting, evaluated on the current (unsaved) values. An empty result removes the field.
    </p>
    <p v-if="error" class="pending">{{ error }}</p>
    <div class="preview">
      <table class="grid">
        <thead>
          <tr>
            <th>File</th>
            <th>Current</th>
            <th>New</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(t, i) in targetTracks" :key="t.path">
            <td class="ellipsis cell">{{ basename(t.path) }}</td>
            <td class="ellipsis cell">{{ current(t) }}</td>
            <td class="ellipsis cell" :class="{ pending: results[i] !== current(t) }">{{ results[i] }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <template #footer>
      <span class="muted grow">{{ changed }} value(s) will change</span>
      <button @click="emit('close')">Cancel</button>
      <button class="primary" :disabled="!changed" @click="apply">Apply</button>
    </template>
  </Modal>
</template>

<style scoped>
.preview {
  max-height: 55vh;
  overflow: auto;
  border: 1px solid var(--border);
}

.cell {
  max-width: 280px;
}

p {
  margin: 0;
}
</style>
