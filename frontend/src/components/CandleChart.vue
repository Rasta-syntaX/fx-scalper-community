<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  api: { type: Function, required: true },
  symbols: { type: Array, default: () => [] },
  history: { type: Array, default: () => [] },
  refreshKey: { type: [String, Number], default: 0 },
})

const W = 600
const H = 220
const PAD = 12
const selected = ref('')
const candles = ref([])
const error = ref('')
const loadingChart = ref(false)

watch(
  () => props.symbols,
  (list) => {
    if (!list.some((item) => item.symbol === selected.value)) {
      selected.value = list[0]?.symbol || ''
    }
  },
  { immediate: true },
)

async function load() {
  if (!selected.value) {
    candles.value = []
    return
  }
  loadingChart.value = true
  try {
    const { data } = await props.api.get('candles', { params: { symbol: selected.value, count: 120 } })
    candles.value = data.candles || []
    error.value = ''
  } catch (err) {
    candles.value = []
    error.value = err?.response?.data?.error || err?.message || 'Could not load candles.'
  } finally {
    loadingChart.value = false
  }
}

watch([selected, () => props.refreshKey], load, { immediate: true })

const scale = computed(() => {
  const rows = candles.value
  if (!rows.length) return null
  const low = Math.min(...rows.map((c) => c.low))
  const high = Math.max(...rows.map((c) => c.high))
  const span = high - low || 1
  return { step: W / rows.length, y: (v) => PAD + (H - 2 * PAD) * (1 - (v - low) / span) }
})

const bars = computed(() => {
  const s = scale.value
  if (!s) return []
  return candles.value.map((c, i) => {
    const top = s.y(Math.max(c.open, c.close))
    const bottom = s.y(Math.min(c.open, c.close))
    return {
      x: i * s.step + s.step / 2,
      w: Math.max(1, s.step * 0.6),
      top,
      h: Math.max(1, bottom - top),
      hi: s.y(c.high),
      lo: s.y(c.low),
      up: c.close >= c.open,
    }
  })
})

const markers = computed(() => {
  const s = scale.value
  const rows = candles.value
  if (!s || rows.length < 2) return []
  const first = rows[0].epoch
  const step = rows[1].epoch - rows[0].epoch || 1
  return props.history
    .filter((e) => e.symbol === selected.value && /OPEN$/.test(e.type || '') && ['BUY', 'SELL'].includes(e.side))
    .map((e) => {
      const i = Math.floor((Date.parse(e.timestamp) / 1000 - first) / step)
      if (!(i >= 0 && i < rows.length)) return null
      const x = i * s.step + s.step / 2
      return e.side === 'BUY'
        ? { x, y: Math.min(H - 6, s.y(rows[i].low) + 10), buy: true }
        : { x, y: Math.max(6, s.y(rows[i].high) - 10), buy: false }
    })
    .filter(Boolean)
})

const last = computed(() => candles.value[candles.value.length - 1])
const change = computed(() => {
  const rows = candles.value
  return rows.length > 1 ? (rows[rows.length - 1].close / rows[0].open - 1) * 100 : null
})
</script>

<template>
  <article class="card section-card chart-card">
    <div class="section-head chart-head">
      <h2>Price Chart</h2>
      <select v-if="symbols.length" v-model="selected" class="select" aria-label="Chart symbol">
        <option v-for="item in symbols" :key="`chart-${item.symbol}`" :value="item.symbol">{{ item.label || item.symbol }}</option>
      </select>
      <span v-if="last" class="kv">
        {{ last.close }}
        <span v-if="change !== null" :class="change >= 0 ? 'up' : 'down'">{{ change >= 0 ? '+' : '' }}{{ change.toFixed(2) }}%</span>
      </span>
    </div>
    <div class="section-body">
      <div v-if="!symbols.length" class="empty-state">Add a symbol or press "Try demo data" to see a chart.</div>
      <div v-else-if="error" class="note">{{ error }}</div>
      <svg v-else-if="bars.length" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="candle-svg" role="img" :aria-label="`${selected} last ${bars.length} candles with trade markers`">
        <g v-for="(bar, i) in bars" :key="i" :class="bar.up ? 'candle-up' : 'candle-down'">
          <line :x1="bar.x" :x2="bar.x" :y1="bar.hi" :y2="bar.lo" stroke="currentColor" vector-effect="non-scaling-stroke" />
          <rect :x="bar.x - bar.w / 2" :y="bar.top" :width="bar.w" :height="bar.h" fill="currentColor" />
        </g>
        <polygon
          v-for="(m, i) in markers"
          :key="`m-${i}`"
          :points="m.buy ? `${m.x},${m.y - 6} ${m.x - 5},${m.y + 4} ${m.x + 5},${m.y + 4}` : `${m.x},${m.y + 6} ${m.x - 5},${m.y - 4} ${m.x + 5},${m.y - 4}`"
          :class="m.buy ? 'marker-buy' : 'marker-sell'"
        />
      </svg>
      <div v-else class="empty-state">{{ loadingChart ? 'Loading candles…' : 'No candles yet.' }}</div>
      <p class="muted chart-legend">▲ buy · ▼ sell entries from the journal</p>
    </div>
  </article>
</template>
