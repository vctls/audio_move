<script lang="ts">
// Only the topmost modal reacts to Escape when dialogs are nested.
const stack: symbol[] = []
</script>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

withDefaults(defineProps<{ title: string; width?: string; height?: string }>(), {
  width: '640px',
  height: 'auto',
})
const emit = defineEmits<{ close: [] }>()
const id = Symbol()

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && stack[stack.length - 1] === id) {
    e.stopPropagation()
    emit('close')
  }
}

onMounted(() => {
  stack.push(id)
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  stack.splice(stack.indexOf(id), 1)
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div class="backdrop">
    <div class="modal" :style="{ width, height }" role="dialog" :aria-label="title">
      <header>
        <strong>{{ title }}</strong>
        <button class="link close" title="Close (Esc)" @click="emit('close')">✕</button>
      </header>
      <div class="body">
        <slot />
      </div>
      <footer v-if="$slots.footer">
        <slot name="footer" />
      </footer>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  background: rgb(0 0 0 / 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.modal {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 32px);
}

header {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}

header strong {
  flex: 1;
}

.close {
  color: var(--muted);
  font-size: 15px;
}

.body {
  padding: 12px 14px;
  overflow: auto;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid var(--border);
}
</style>
