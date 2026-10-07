<script setup lang="ts">
import { computed, ref } from 'vue'
import { firstValue, stage, state, targetTracks, updateSettings } from '../store'
import type { FieldChange } from '../store'
import { basename, padNumber } from '../util'
import Modal from './Modal.vue'

const emit = defineEmits<{ close: [] }>()

const perDisc = ref(state.settings?.autonumber_per_disc ?? true)
const setTotal = ref(state.settings?.autonumber_total ?? true)
const padding = ref(state.settings?.track_padding ?? 2)
const start = ref(1)

const plan = computed(() => {
  const tracks = targetTracks.value
  const groups = new Map<string, typeof tracks>()
  for (const t of tracks) {
    const key = perDisc.value ? firstValue(t, 'DISCNUMBER') : ''
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(t)
  }
  return tracks.map((t) => {
    const group = groups.get(perDisc.value ? firstValue(t, 'DISCNUMBER') : '')!
    const n = group.indexOf(t) + start.value
    return {
      track: t,
      disc: firstValue(t, 'DISCNUMBER'),
      number: padNumber(n, padding.value),
      total: padNumber(group.length + start.value - 1, padding.value),
    }
  })
})

function apply() {
  const changes: FieldChange[] = []
  for (const p of plan.value) {
    changes.push({ path: p.track.path, field: 'TRACKNUMBER', values: [p.number] })
    if (setTotal.value) changes.push({ path: p.track.path, field: 'TOTALTRACKS', values: [p.total] })
  }
  stage(changes)
  void updateSettings({
    autonumber_per_disc: perDisc.value,
    autonumber_total: setTotal.value,
    track_padding: padding.value,
  })
  emit('close')
}
</script>

<template>
  <Modal title="Auto track number" width="620px" @close="emit('close')">
    <p class="muted">
      Numbers {{ state.selected.size ? 'the selected tracks' : 'all tracks' }} in the order shown in the list. Sort or
      reorder the list first (<kbd>Alt</kbd>+<kbd>↑</kbd>/<kbd>↓</kbd>).
    </p>
    <div class="row">
      <label><input v-model="perDisc" type="checkbox" /> Restart at each DISCNUMBER</label>
      <label><input v-model="setTotal" type="checkbox" /> Set TOTALTRACKS</label>
      <label>Digits <input v-model.number="padding" type="number" min="0" max="4" style="width: 50px" /></label>
      <label>Start at <input v-model.number="start" type="number" min="0" style="width: 60px" /></label>
    </div>
    <div class="preview">
      <table class="grid">
        <thead>
          <tr>
            <th>File</th>
            <th>Disc</th>
            <th>Track</th>
            <th v-if="setTotal">Total</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in plan" :key="p.track.path">
            <td class="ellipsis">{{ basename(p.track.path) }}</td>
            <td>{{ p.disc }}</td>
            <td>{{ p.number }}</td>
            <td v-if="setTotal">{{ p.total }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <template #footer>
      <button @click="emit('close')">Cancel</button>
      <button class="primary" @click="apply">Apply</button>
    </template>
  </Modal>
</template>

<style scoped>
.preview {
  max-height: 50vh;
  overflow: auto;
  border: 1px solid var(--border);
}

td.ellipsis {
  max-width: 340px;
}
</style>
