<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: Boolean,
  title: { type: String, default: '' },
  body: { type: String, default: '' },
  confirmLabel: { type: String, default: 'Confirm' },
})
const emit = defineEmits(['confirm', 'cancel'])
const cancelButton = ref(null)

watch(
  () => props.open,
  async (value) => {
    if (value) {
      await nextTick()
      cancelButton.value?.focus()
    }
  },
)
</script>

<template>
  <div v-if="open" class="modal-backdrop" @click.self="emit('cancel')" @keydown.esc="emit('cancel')">
    <div class="modal card" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-body">
      <h2 id="confirm-title">{{ title }}</h2>
      <p id="confirm-body">{{ body }}</p>
      <div class="actions">
        <button ref="cancelButton" class="button secondary" type="button" @click="emit('cancel')">Cancel</button>
        <button class="button danger" type="button" @click="emit('confirm')">{{ confirmLabel }}</button>
      </div>
    </div>
  </div>
</template>
