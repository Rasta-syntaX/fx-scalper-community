<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  api: { type: Function, required: true },
  refreshKey: { type: [String, Number], default: 0 },
})
defineEmits(['export'])

const entries = ref([])
const error = ref('')
const query = ref('')
const typeFilter = ref('')
const sideFilter = ref('')
const newestFirst = ref(true)

async function load() {
  try {
    const { data } = await props.api.get('journal', { params: { limit: 500 } })
    entries.value = data.entries || []
    error.value = ''
  } catch (err) {
    error.value = err?.response?.data?.error || err?.message || 'Could not load the journal.'
  }
}

watch(() => props.refreshKey, load, { immediate: true })

const types = computed(() => [...new Set(entries.value.map((row) => row.type).filter(Boolean))].sort())
const rows = computed(() => {
  const needle = query.value.trim().toLowerCase()
  const filtered = entries.value.filter(
    (row) =>
      (!typeFilter.value || row.type === typeFilter.value) &&
      (!sideFilter.value || row.side === sideFilter.value) &&
      (!needle || `${row.symbol || ''} ${row.note || ''}`.toLowerCase().includes(needle)),
  )
  const sorted = [...filtered].sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)))
  return newestFirst.value ? sorted.reverse() : sorted
})
</script>

<template>
  <article class="card section-card journal-card">
    <div class="section-head">
      <h2>Journal</h2>
      <p>Every trade event the bot recorded, newest first. The full history is in the CSV export.</p>
    </div>
    <div class="section-body">
      <div class="journal-filters">
        <input v-model="query" class="input" type="search" placeholder="Search symbol or note" aria-label="Search journal" />
        <select v-model="typeFilter" class="select" aria-label="Event type">
          <option value="">All events</option>
          <option v-for="type in types" :key="type" :value="type">{{ type }}</option>
        </select>
        <select v-model="sideFilter" class="select" aria-label="Side">
          <option value="">Both sides</option>
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
        <button class="button secondary" type="button" @click="load">Refresh</button>
        <button class="button secondary" type="button" @click="$emit('export')">Export CSV</button>
      </div>
      <div v-if="error" class="note">{{ error }}</div>
      <div v-else-if="!rows.length" class="empty-state">No journal entries match. Run a scan or open a paper trade.</div>
      <div v-else class="table-wrap">
        <table class="journal-table">
          <thead>
            <tr>
              <th>
                <button class="sort-button" type="button" :aria-label="newestFirst ? 'Sort oldest first' : 'Sort newest first'" @click="newestFirst = !newestFirst">
                  Time {{ newestFirst ? '↓' : '↑' }}
                </button>
              </th>
              <th>Event</th>
              <th>Symbol</th>
              <th>Side</th>
              <th class="num">Exposure</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in rows" :key="`${row.timestamp}-${i}`">
              <td class="nowrap">{{ String(row.timestamp || '').replace('T', ' ').slice(0, 19) }}</td>
              <td><span class="pill">{{ row.type }}</span></td>
              <td>{{ row.symbol || '–' }}</td>
              <td :class="row.side === 'BUY' ? 'up' : row.side === 'SELL' ? 'down' : ''">{{ row.side || '–' }}</td>
              <td class="num">{{ row.exposure ?? '–' }}</td>
              <td class="note-cell">{{ row.note || '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </article>
</template>
