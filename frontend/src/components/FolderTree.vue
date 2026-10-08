<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { loadFolder, state } from '../store'
import FolderNode from './FolderNode.vue'
import { loadRoots, navigate, refreshTree, tree } from './folderTree'

// Each load reads the tags of every file on the server, so holding an arrow key must not start one per row.
const KEY_LOAD_DELAY = 300

onMounted(loadRoots)
watch(
  () => state.treeVersion,
  () => refreshTree(),
)

const el = ref<HTMLElement | null>(null)
const cursor = ref<string | null>(null)
const active = computed(() => cursor.value ?? (state.loadingPath || state.folder))
let loadTimer: ReturnType<typeof setTimeout> | undefined

function pick(path: string) {
  clearTimeout(loadTimer)
  cursor.value = null
  void loadFolder(path)
}

function onKey(e: KeyboardEvent) {
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return
  const next = navigate(active.value, e.key)
  if (next === undefined) return
  e.preventDefault()
  if (next !== active.value) {
    cursor.value = next
    clearTimeout(loadTimer)
    loadTimer = setTimeout(() => {
      if (next === (state.loadingPath || state.folder)) cursor.value = null
      else pick(next)
    }, KEY_LOAD_DELAY)
  }
  void nextTick(() => el.value?.querySelector('.node.active')?.scrollIntoView({ block: 'nearest' }))
}
</script>

<template>
  <div ref="el" class="tree" tabindex="0" @keydown="onKey">
    <div class="head row">
      <strong class="grow">Folders</strong>
      <label title="Include tracks in subfolders, e.g. CD1/CD2">
        <input v-model="state.recursive" type="checkbox" /> Subfolders
      </label>
      <button class="link" title="Refresh" @click="refreshTree()">⟳</button>
    </div>
    <FolderNode v-for="root in tree.roots" :key="root.path" :dir="root" :depth="0" :active="active" @pick="pick" />
    <p v-if="!tree.roots.length" class="muted empty">No music folder is mounted.</p>
  </div>
</template>

<style scoped>
.tree {
  padding-bottom: 12px;
  outline: none;
}

.tree :deep(.node) {
  /* Keeps rows reached by keyboard from scrolling under the sticky header. */
  scroll-margin-top: 34px;
}

.head {
  position: sticky;
  top: 0;
  background: var(--panel);
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  z-index: 1;
  font-size: 12px;
}

.empty {
  padding: 8px;
}
</style>
