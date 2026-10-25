<script setup>
defineProps({ toasts: { type: Array, default: () => [] } })
defineEmits(['dismiss'])
</script>

<template>
  <div class="toast-stack" role="status" aria-live="polite">
    <div v-for="toast in toasts" :key="toast.id" class="toast" :class="toast.kind">
      <span>{{ toast.text }}</span>
      <button class="toast-close" type="button" aria-label="Dismiss" @click="$emit('dismiss', toast.id)">×</button>
    </div>
  </div>
</template>
