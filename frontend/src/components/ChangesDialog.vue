<script setup lang="ts">
import { computed } from 'vue'
import {
  discard,
  discardPictureRemoval,
  displayValue,
  isDrasticChange,
  pendingCount,
  revert,
  save,
  state,
} from '../store'
import { relativeTo } from '../util'
import Modal from './Modal.vue'

const emit = defineEmits<{ close: [] }>()

const files = computed(() =>
  state.tracks
    .filter((t) => state.pending[t.path] || state.pictureRemovals[t.path])
    .map((t) => ({
      track: t,
      fields: Object.entries(state.pending[t.path] ?? {}).map(([field, next]) => ({
        field,
        old: t.tags[field],
        next,
        drastic: isDrasticChange(t, field),
      })),
      pictures: state.pictureRemovals[t.path] ? t.pictures.length : 0,
    })),
)

const changeCount = computed(() => files.value.reduce((sum, f) => sum + f.fields.length + (f.pictures ? 1 : 0), 0))

async function saveAll() {
  if (await save()) emit('close')
}
</script>

<template>
  <Modal title="Unsaved changes" width="900px" @close="emit('close')">
    <p v-if="!files.length" class="muted">No unsaved changes.</p>
    <template v-else>
      <p>{{ changeCount }} change(s) on {{ files.length }} file(s).</p>
      <div class="diff">
        <div v-for="f in files" :key="f.track.path" class="trow">
          <div class="row thead">
            <span class="mono ellipsis grow file" :title="f.track.path">{{
              relativeTo(f.track.path, state.folder)
            }}</span>
            <button class="link" title="Discard every change to this file" @click="discard(f.track.path)">
              Revert file
            </button>
          </div>
          <table>
            <tr v-for="c in f.fields" :key="c.field">
              <td class="f">{{ c.field }}</td>
              <td class="old" :class="{ empty: !c.old?.length }">{{ displayValue(c.old) || '—' }}</td>
              <td class="arrow">→</td>
              <td
                class="new"
                :class="{ removed: c.next === null, drastic: c.drastic }"
                :title="c.drastic ? 'Very different from the value on disk' : undefined"
              >
                {{ c.next === null ? 'removed' : displayValue(c.next) }}
              </td>
              <td class="act">
                <button class="link" title="Keep the value on disk" @click="discard(f.track.path, c.field)">↺</button>
              </td>
            </tr>
            <tr v-if="f.pictures">
              <td class="f">Embedded pictures</td>
              <td class="old">{{ f.pictures }} picture(s)</td>
              <td class="arrow">→</td>
              <td class="new removed">removed</td>
              <td class="act">
                <button class="link" title="Keep the embedded pictures" @click="discardPictureRemoval(f.track.path)">
                  ↺
                </button>
              </td>
            </tr>
          </table>
        </div>
      </div>
    </template>
    <template #footer>
      <button @click="emit('close')">Close</button>
      <button :disabled="!pendingCount" title="Discard all pending changes" @click="revert()">Revert all</button>
      <button class="primary" :disabled="!pendingCount || state.saving" @click="saveAll">
        {{ state.saving ? 'Saving…' : `Save ${pendingCount} file(s)` }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
p {
  margin: 0;
}

.diff {
  min-height: 0;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 4px;
}

.trow {
  border-bottom: 1px solid var(--border);
  padding: 4px 8px 6px;
}

.trow:last-child {
  border-bottom: none;
}

.thead {
  margin-bottom: 2px;
}

.file {
  font-weight: 600;
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
  width: 190px;
  color: var(--muted);
}

td.old {
  width: 40%;
  color: var(--muted);
  text-decoration: line-through;
  word-break: break-word;
}

td.old.empty {
  text-decoration: none;
}

td.arrow {
  width: 20px;
  color: var(--muted);
}

td.new {
  color: var(--pending);
  word-break: break-word;
}

td.new.removed {
  font-style: italic;
}

td.new.drastic {
  color: var(--danger);
}

td.act {
  width: 24px;
  text-align: right;
}
</style>
