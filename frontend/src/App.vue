<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AutoNumberDialog from './components/AutoNumberDialog.vue'
import FolderTree from './components/FolderTree.vue'
import FormatDialog from './components/FormatDialog.vue'
import GuessDialog from './components/GuessDialog.vue'
import MoveDialog from './components/MoveDialog.vue'
import MusicBrainzDialog from './components/MusicBrainzDialog.vue'
import PropertiesPanel from './components/PropertiesPanel.vue'
import RemovePicturesDialog from './components/RemovePicturesDialog.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import Toasts from './components/Toasts.vue'
import TrackTable from './components/TrackTable.vue'
import {
  canRedo,
  canUndo,
  loadSettings,
  moveSelection,
  pendingCount,
  redo,
  removeSelectedFromList,
  revert,
  save,
  selectAll,
  selectedTracks,
  state,
  undo,
} from './store'
import { formatLength, isEditableTarget } from './util'

type DialogName = 'autonumber' | 'guess' | 'format' | 'pictures' | 'mb' | 'move' | 'settings' | null
const dialog = ref<DialogName>(null)
const toolsOpen = ref(false)

const sidebarWidth = ref(Number(localStorage.getItem('sidebarWidth')) || 240)
const propsHeight = ref(Number(localStorage.getItem('propsHeight')) || 300)

const totalLength = computed(() => state.tracks.reduce((sum, t) => sum + (t.info.length || 0), 0))
const selectedLength = computed(() => selectedTracks.value.reduce((sum, t) => sum + (t.info.length || 0), 0))

function open(name: DialogName) {
  toolsOpen.value = false
  dialog.value = name
}

function dragSidebar(e: MouseEvent) {
  const start = e.clientX
  const initial = sidebarWidth.value
  const move = (ev: MouseEvent) => {
    sidebarWidth.value = Math.max(160, Math.min(600, initial + ev.clientX - start))
  }
  const up = () => {
    localStorage.setItem('sidebarWidth', String(sidebarWidth.value))
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

function dragProps(e: MouseEvent) {
  const start = e.clientY
  const initial = propsHeight.value
  const move = (ev: MouseEvent) => {
    propsHeight.value = Math.max(120, Math.min(window.innerHeight - 200, initial - (ev.clientY - start)))
  }
  const up = () => {
    localStorage.setItem('propsHeight', String(propsHeight.value))
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

function onKey(e: KeyboardEvent) {
  const mod = e.ctrlKey || e.metaKey
  if (mod && e.key.toLowerCase() === 's') {
    e.preventDefault()
    void save()
    return
  }
  if (dialog.value || isEditableTarget(e.target)) return
  if (mod && e.key.toLowerCase() === 'a') {
    e.preventDefault()
    selectAll()
  } else if (mod && e.key.toLowerCase() === 'z' && !e.shiftKey) {
    e.preventDefault()
    undo()
  } else if (mod && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
    e.preventDefault()
    redo()
  } else if (e.key === 'Delete') {
    removeSelectedFromList()
  } else if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
    e.preventDefault()
    moveSelection(e.key === 'ArrowUp' ? -1 : 1)
  }
}

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (pendingCount.value) e.preventDefault()
}

onMounted(() => {
  void loadSettings()
  window.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', onBeforeUnload)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('beforeunload', onBeforeUnload)
})
</script>

<template>
  <div class="app" :style="{ '--sidebar': sidebarWidth + 'px', '--props': propsHeight + 'px' }">
    <header class="toolbar">
      <span class="brand">audio-move</span>
      <button
        :class="{ primary: pendingCount > 0 }"
        :disabled="!pendingCount || state.saving"
        title="Write pending tag changes to the files (Ctrl+S)"
        @click="save()"
      >
        Save{{ pendingCount ? ` (${pendingCount})` : '' }}
      </button>
      <button :disabled="!pendingCount" title="Discard all pending changes" @click="revert()">Revert</button>
      <button :disabled="!canUndo" title="Undo (Ctrl+Z)" @click="undo()">Undo</button>
      <button :disabled="!canRedo" title="Redo (Ctrl+Y)" @click="redo()">Redo</button>
      <span class="sep" />
      <button
        :disabled="!state.tracks.length"
        title="Number the selected tracks in list order"
        @click="open('autonumber')"
      >
        Auto track number
      </button>
      <div class="menu">
        <button :disabled="!state.tracks.length" @click="toolsOpen = !toolsOpen">Tools ▾</button>
        <div v-if="toolsOpen" class="menu-list" @mouseleave="toolsOpen = false">
          <button @click="open('guess')">Guess values from file name…</button>
          <button @click="open('format')">Format field from other fields…</button>
          <button @click="open('pictures')">Remove embedded pictures…</button>
        </div>
      </div>
      <span class="sep" />
      <button :disabled="!state.tracks.length" @click="open('mb')">MusicBrainz…</button>
      <button :disabled="!state.tracks.length" @click="open('move')">Move / rename…</button>
      <span class="grow" />
      <button title="Settings" @click="open('settings')">Settings</button>
    </header>

    <aside class="sidebar">
      <FolderTree />
    </aside>
    <div class="splitter-v" @mousedown.prevent="dragSidebar" />

    <main class="main">
      <TrackTable />
      <div class="splitter-h" @mousedown.prevent="dragProps" />
      <PropertiesPanel />
    </main>

    <footer class="statusbar">
      <span class="ellipsis grow">{{ state.folder || 'Pick a folder on the left to load its tracks' }}</span>
      <span v-if="state.loading">Loading…</span>
      <span>{{ state.tracks.length }} tracks · {{ formatLength(totalLength) }}</span>
      <span v-if="state.selected.size"> {{ state.selected.size }} selected · {{ formatLength(selectedLength) }} </span>
      <span v-if="pendingCount" class="pending">{{ pendingCount }} unsaved</span>
    </footer>

    <AutoNumberDialog v-if="dialog === 'autonumber'" @close="dialog = null" />
    <GuessDialog v-if="dialog === 'guess'" @close="dialog = null" />
    <FormatDialog v-if="dialog === 'format'" @close="dialog = null" />
    <RemovePicturesDialog v-if="dialog === 'pictures'" @close="dialog = null" />
    <MusicBrainzDialog v-if="dialog === 'mb'" @close="dialog = null" />
    <MoveDialog v-if="dialog === 'move'" @close="dialog = null" />
    <SettingsDialog v-if="dialog === 'settings'" @close="dialog = null" />
    <Toasts />
  </div>
</template>

<style scoped>
.app {
  display: grid;
  grid-template-columns: var(--sidebar) 4px 1fr;
  grid-template-rows: auto 1fr auto;
  height: 100vh;
}

.toolbar {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}

.brand {
  font-weight: 700;
  margin-right: 8px;
}

.sep {
  width: 1px;
  height: 20px;
  background: var(--border);
  margin: 0 4px;
}

.menu {
  position: relative;
}

.menu-list {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: var(--shadow);
  padding: 4px;
  min-width: 240px;
}

.menu-list button {
  border: none;
  text-align: left;
  padding: 5px 10px;
}

.menu-list button:hover {
  background: var(--select);
}

.sidebar {
  overflow: auto;
  background: var(--panel);
  border-right: 1px solid var(--border);
}

.splitter-v {
  cursor: col-resize;
  background: var(--bg);
}

.main {
  display: grid;
  grid-template-rows: 1fr 4px var(--props);
  min-width: 0;
  min-height: 0;
}

.splitter-h {
  cursor: row-resize;
  background: var(--bg);
}

.statusbar {
  grid-column: 1 / -1;
  display: flex;
  gap: 16px;
  padding: 3px 10px;
  border-top: 1px solid var(--border);
  background: var(--panel);
  color: var(--muted);
  font-size: 12px;
}
</style>
