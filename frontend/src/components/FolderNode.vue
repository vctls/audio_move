<script setup lang="ts">
import { computed } from 'vue'
import type { DirEntry } from '../types'
import { tree, toggle } from './folderTree'

const props = defineProps<{ dir: DirEntry; depth: number; active: string }>()
const emit = defineEmits<{ pick: [path: string]; confirm: [path: string] }>()

const node = computed(() => tree.nodes[props.dir.path])
const expanded = computed(() => node.value?.expanded ?? false)
</script>

<template>
  <div>
    <div
      class="node"
      :class="{ active: active === dir.path }"
      :style="{ paddingLeft: depth * 14 + 4 + 'px' }"
      :title="dir.path"
      @click="emit('pick', dir.path)"
      @dblclick="emit('confirm', dir.path)"
    >
      <span class="twisty" @click.stop="dir.has_children && toggle(dir.path)">
        {{ dir.has_children ? (expanded ? '▾' : '▸') : '' }}
      </span>
      <span class="name ellipsis">{{ dir.name }}</span>
      <span v-if="dir.audio" class="count">{{ dir.audio }}</span>
    </div>
    <template v-if="expanded">
      <div v-if="node?.loading && !node.children" class="loading" :style="{ paddingLeft: depth * 14 + 22 + 'px' }">
        Loading…
      </div>
      <FolderNode
        v-for="child in node?.children ?? []"
        :key="child.path"
        :dir="child"
        :depth="depth + 1"
        :active="active"
        @pick="emit('pick', $event)"
        @confirm="emit('confirm', $event)"
      />
    </template>
  </div>
</template>

<style scoped>
.node {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px 6px 2px 4px;
  cursor: default;
  white-space: nowrap;
}

.node:hover {
  background: var(--panel-2);
}

.node.active {
  background: var(--select-strong);
}

.twisty {
  width: 14px;
  flex: none;
  text-align: center;
  color: var(--muted);
  cursor: pointer;
}

.name {
  flex: 1;
}

.count {
  font-size: 11px;
  color: var(--muted);
  margin-left: 6px;
}

.loading {
  color: var(--muted);
  font-size: 12px;
  padding: 2px;
}
</style>
