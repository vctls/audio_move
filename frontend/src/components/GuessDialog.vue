<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { errorText, stage, state, targetTracks, updateSettings } from '../store'
import type { FieldChange } from '../store'
import { basename, debounce } from '../util'
import Modal from './Modal.vue'

const emit = defineEmits<{ close: [] }>()

const pattern = ref(state.settings?.guess_patterns[0] ?? '%tracknumber% - %title%')
const results = ref<(Record<string, string> | null)[]>([])
const error = ref('')

const fields = computed(() => {
  const set = new Set<string>()
  for (const r of results.value) if (r) Object.keys(r).forEach((k) => set.add(k))
  return [...set]
})
const matched = computed(() => results.value.filter(Boolean).length)

const refresh = debounce(async () => {
  try {
    const res = await api.guess(
      pattern.value,
      targetTracks.value.map((t) => t.path),
    )
    results.value = res.results
    error.value = ''
  } catch (e) {
    error.value = errorText(e)
  }
}, 200)

watch(pattern, refresh)
onMounted(refresh)

function apply() {
  const changes: FieldChange[] = []
  targetTracks.value.forEach((t, i) => {
    const r = results.value[i]
    if (r) for (const [field, value] of Object.entries(r)) changes.push({ path: t.path, field, values: [value] })
  })
  stage(changes)
  const patterns = [pattern.value, ...(state.settings?.guess_patterns ?? []).filter((p) => p !== pattern.value)]
  void updateSettings({ guess_patterns: patterns.slice(0, 20) })
  emit('close')
}
</script>

<template>
  <Modal title="Guess values from file name" width="900px" @close="emit('close')">
    <div class="row">
      <input v-model="pattern" class="grow mono" list="guess-patterns" spellcheck="false" />
      <datalist id="guess-patterns">
        <option v-for="p in state.settings?.guess_patterns ?? []" :key="p" :value="p" />
      </datalist>
    </div>
    <p class="muted">
      Matched against the file name without extension. Each <code>/</code> also matches one parent folder, e.g.
      <code>%album artist% - %album%/%tracknumber% - %title%</code>. Use <code>%dummy%</code> to skip a part.
    </p>
    <p v-if="error" class="pending">{{ error }}</p>
    <div class="preview">
      <table class="grid">
        <thead>
          <tr>
            <th>File</th>
            <th v-for="f in fields" :key="f">{{ f }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(t, i) in targetTracks" :key="t.path">
            <td class="ellipsis file">{{ basename(t.path) }}</td>
            <template v-if="results[i]">
              <td v-for="f in fields" :key="f">{{ results[i]?.[f] }}</td>
            </template>
            <td v-else :colspan="fields.length || 1" class="muted">no match</td>
          </tr>
        </tbody>
      </table>
    </div>
    <template #footer>
      <span class="muted grow">{{ matched }} / {{ targetTracks.length }} files match</span>
      <button @click="emit('close')">Cancel</button>
      <button class="primary" :disabled="!matched" @click="apply">Apply</button>
    </template>
  </Modal>
</template>

<style scoped>
.preview {
  max-height: 55vh;
  overflow: auto;
  border: 1px solid var(--border);
}

.file {
  max-width: 320px;
}

p {
  margin: 0;
}
</style>
