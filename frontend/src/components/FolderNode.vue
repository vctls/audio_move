<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watchEffect } from 'vue'
import type { DirEntry } from '../types'
import {
  PAGE_SIZE,
  cancelSummary,
  observeVisibility,
  requestSummary,
  showMore,
  toggle,
  tree,
  unobserveVisibility,
} from './folderTree'

const props = defineProps<{ dir: DirEntry; depth: number; active: string }>()
const emit = defineEmits<{ pick: [path: string]; confirm: [path: string] }>()

const node = computed(() => tree.nodes[props.dir.path])
const summary = computed(() => tree.summaries[props.dir.path])
const expanded = computed(() => node.value?.expanded ?? false)
// Until the summary arrives, every folder is assumed to have subfolders.
const expandable = computed(() => summary.value?.has_children ?? true)
const children = computed(() => node.value?.children ?? [])
const shown = computed(() => children.value.slice(0, node.value?.shown ?? PAGE_SIZE))
const remaining = computed(() => children.value.length - shown.value.length)

const row = ref<HTMLElement | null>(null)
const visible = ref(false)

onMounted(() => {
  if (row.value) observeVisibility(row.value, (v) => (visible.value = v))
})
onBeforeUnmount(() => {
  if (row.value) unobserveVisibility(row.value)
  cancelSummary(props.dir.path)
})
watchEffect(() => {
  if (!visible.value) cancelSummary(props.dir.path)
  else if (!summary.value) requestSummary(props.dir.path)
})
</script>

<template>
  <div>
    <div
      ref="row"
      class="node"
      :class="{ active: active === dir.path }"
      :style="{ paddingLeft: depth * 14 + 4 + 'px' }"
      :title="dir.path"
      @click="emit('pick', dir.path)"
      @dblclick="emit('confirm', dir.path)"
    >
      <span class="twisty" :class="{ unknown: !summary }" @click.stop="expandable && toggle(dir.path)">
        {{ expandable ? (expanded ? '▾' : '▸') : '' }}
      </span>
      <span class="name ellipsis">{{ dir.name }}</span>
      <span v-if="summary?.audio" class="count">{{ summary.audio }}</span>
    </div>
    <template v-if="expanded">
      <div v-if="node?.loading && !node.children" class="hint" :style="{ paddingLeft: depth * 14 + 22 + 'px' }">
        Loading…
      </div>
      <FolderNode
        v-for="child in shown"
        :key="child.path"
        :dir="child"
        :depth="depth + 1"
        :active="active"
        @pick="emit('pick', $event)"
        @confirm="emit('confirm', $event)"
      />
      <button
        v-if="remaining > 0"
        class="link more"
        :style="{ marginLeft: depth * 14 + 22 + 'px' }"
        @click="showMore(dir.path)"
      >
        Show {{ Math.min(remaining, PAGE_SIZE) }} more of {{ remaining }}…
      </button>
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

.twisty.unknown {
  opacity: 0.45;
}

.name {
  flex: 1;
}

.count {
  font-size: 11px;
  color: var(--muted);
  margin-left: 6px;
}

.hint {
  color: var(--muted);
  font-size: 12px;
  padding: 2px;
}

.more {
  font-size: 12px;
  padding: 2px 0;
}
</style>
