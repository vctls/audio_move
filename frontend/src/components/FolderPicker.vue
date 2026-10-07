<script setup lang="ts">
import { onMounted, ref } from 'vue'
import FolderNode from './FolderNode.vue'
import Modal from './Modal.vue'
import { loadRoots, reveal, tree } from './folderTree'

const props = defineProps<{ initial: string }>()
const emit = defineEmits<{ close: []; pick: [path: string] }>()
const selected = ref(props.initial)

onMounted(async () => {
  if (!tree.roots.length) await loadRoots()
  if (props.initial) await reveal(props.initial)
})

function confirm(path = selected.value) {
  if (!path) return
  emit('pick', path)
  emit('close')
}
</script>

<template>
  <Modal title="Choose destination folder" width="520px" height="70vh" @close="emit('close')">
    <div class="tree">
      <FolderNode
        v-for="root in tree.roots"
        :key="root.path"
        :dir="root"
        :depth="0"
        :active="selected"
        @pick="selected = $event"
        @confirm="confirm"
      />
    </div>
    <template #footer>
      <span class="grow ellipsis mono">{{ selected }}</span>
      <button @click="emit('close')">Cancel</button>
      <button class="primary" :disabled="!selected" @click="confirm()">Select</button>
    </template>
  </Modal>
</template>

<style scoped>
.tree {
  border: 1px solid var(--border);
  flex: 1;
  overflow: auto;
}
</style>
