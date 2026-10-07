<script setup lang="ts">
import { dismissToast, state } from '../store'
</script>

<template>
  <div class="toasts">
    <div v-for="t in state.toasts" :key="t.id" class="toast" :class="t.kind" @click="dismissToast(t.id)">
      {{ t.text }}
    </div>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  right: 16px;
  bottom: 36px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 100;
  max-width: min(480px, calc(100vw - 32px));
}

.toast {
  background: var(--panel);
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent);
  border-radius: 4px;
  padding: 8px 12px;
  box-shadow: var(--shadow);
  cursor: pointer;
}

.toast.error {
  border-left-color: var(--danger);
}

.toast.success {
  border-left-color: var(--ok);
}
</style>
