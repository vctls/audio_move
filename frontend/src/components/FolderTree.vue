<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { loadFolder, state } from '../store'
import FolderNode from './FolderNode.vue'
import { loadRoots, refreshTree, tree } from './folderTree'

onMounted(loadRoots)
watch(
  () => state.treeVersion,
  () => refreshTree(),
)
</script>

<template>
  <div class="tree">
    <div class="head row">
      <strong class="grow">Folders</strong>
      <label title="Include tracks in subfolders, e.g. CD1/CD2">
        <input v-model="state.recursive" type="checkbox" /> Subfolders
      </label>
      <button class="link" title="Refresh" @click="refreshTree()">⟳</button>
    </div>
    <FolderNode
      v-for="root in tree.roots"
      :key="root.path"
      :dir="root"
      :depth="0"
      :active="state.folder"
      @pick="loadFolder"
    />
    <p v-if="!tree.roots.length" class="muted empty">No music folder is mounted.</p>
  </div>
</template>

<style scoped>
.tree {
  padding-bottom: 12px;
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
