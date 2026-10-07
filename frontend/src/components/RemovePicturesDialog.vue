<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api'
import { errorText, reloadTracks, stagePictureRemoval, state, targetTracks, toast } from '../store'
import type { FolderImage, Picture, Track } from '../types'
import { basename, dirname, formatBytes, pictureLabel, relativeTo } from '../util'
import Modal from './Modal.vue'

const emit = defineEmits<{ close: [] }>()

const stem = computed(() => state.settings?.cover_name || 'folder')
const extract = ref(true)
const busy = ref(false)

interface FolderRow {
  dir: string
  files: Track[]
  image: FolderImage | null
  best: Picture | null
}

const withArt = computed(() => targetTracks.value.filter((t) => t.pictures.length))
const totalBytes = computed(() => withArt.value.reduce((sum, t) => sum + t.pictures.reduce((s, p) => s + p.size, 0), 0))

const folders = computed<FolderRow[]>(() => {
  const byDir = new Map<string, Track[]>()
  for (const t of withArt.value) {
    const d = dirname(t.path)
    if (!byDir.has(d)) byDir.set(d, [])
    byDir.get(d)!.push(t)
  }
  return [...byDir.entries()].map(([dir, files]) => {
    const usable = files.flatMap((t) => t.pictures).filter((p) => ['image/jpeg', 'image/png'].includes(p.mime))
    usable.sort((a, b) => Number(b.type === 'front') - Number(a.type === 'front') || b.size - a.size)
    return { dir, files, image: files[0].folder_image, best: usable[0] ?? null }
  })
})

const toExtract = computed(() => folders.value.filter((f) => !f.image && f.best))
const lost = computed(() => folders.value.filter((f) => !f.image && (!f.best || !extract.value)))

const folderLabel = (dir: string) => (dir === state.folder ? basename(dir) : relativeTo(dir, state.folder))
const extension = (p: Picture) => (p.mime === 'image/png' ? '.png' : '.jpg')

async function apply() {
  busy.value = true
  try {
    if (extract.value && toExtract.value.length) {
      const paths = toExtract.value.flatMap((f) => f.files.map((t) => t.path))
      const { results } = await api.extractPictures(paths)
      const written = results.filter((r) => r.ok).length
      const failed = results.filter((r) => !r.ok && !r.skipped)
      toast(
        `Saved ${written} folder image(s)${failed.length ? `, ${failed.length} failed: ${failed[0].message}` : ''}`,
        failed.length ? 'error' : 'success',
      )
      await reloadTracks()
      state.treeVersion++
    }
    stagePictureRemoval(withArt.value.map((t) => t.path))
    toast(`Embedded pictures will be removed from ${withArt.value.length} file(s) when you save.`)
    emit('close')
  } catch (e) {
    toast(errorText(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal title="Remove embedded pictures" width="820px" @close="emit('close')">
    <p v-if="!withArt.length">None of the {{ state.selected.size ? 'selected' : '' }} files have embedded pictures.</p>
    <template v-else>
      <p>
        {{ withArt.length }} of {{ targetTracks.length }} file(s) have embedded pictures ({{
          formatBytes(totalBytes)
        }}). They are removed when you save, and the files shrink accordingly.
      </p>
      <label>
        <input v-model="extract" type="checkbox" />
        First save the front cover as <code>{{ stem }}.jpg</code> or <code>{{ stem }}.png</code> in folders that have no
        folder image yet
      </label>
      <p class="muted small">Folder images are written right away. An existing folder image is never replaced.</p>
      <div class="preview">
        <table class="grid">
          <thead>
            <tr>
              <th>Folder</th>
              <th>Files with art</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in folders" :key="f.dir">
              <td class="mono cell" :title="f.dir">{{ folderLabel(f.dir) }}</td>
              <td>{{ f.files.length }}</td>
              <td v-if="f.image">keeps {{ f.image.names.join(', ') }}</td>
              <td v-else-if="f.best && extract">
                writes {{ stem }}{{ extension(f.best) }} <span class="muted">({{ pictureLabel(f.best) }})</span>
              </td>
              <td v-else class="warn">artwork lost{{ f.best ? '' : ': no JPEG or PNG picture to extract' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="lost.length" class="warn">{{ lost.length }} folder(s) will end up without any cover art.</p>
    </template>
    <template #footer>
      <button @click="emit('close')">Cancel</button>
      <button class="primary" :disabled="!withArt.length || busy" @click="apply">
        {{ busy ? 'Working…' : `Remove from ${withArt.length} file(s)` }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
p {
  margin: 0;
}

.small {
  font-size: 12px;
}

.preview {
  max-height: 45vh;
  overflow: auto;
  border: 1px solid var(--border);
}

.cell {
  overflow-wrap: anywhere;
}

.warn {
  color: var(--warn);
}
</style>
