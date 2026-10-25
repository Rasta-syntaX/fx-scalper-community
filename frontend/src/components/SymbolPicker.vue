<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '[]' },
  source: { type: String, default: 'deriv' },
})
const emit = defineEmits(['update:modelValue'])

const PRESETS = {
  deriv: [
    ['frxEURUSD', 'FOREX', 'EUR/USD'],
    ['frxGBPUSD', 'FOREX', 'GBP/USD'],
    ['frxUSDJPY', 'FOREX', 'USD/JPY'],
    ['frxAUDUSD', 'FOREX', 'AUD/USD'],
    ['frxXAUUSD', 'COMMODITIES', 'Gold/USD'],
    ['cryBTCUSD', 'CRYPTO', 'BTC/USD'],
  ],
  binance: [
    ['BTCUSDT', 'CRYPTO', 'Bitcoin'],
    ['ETHUSDT', 'CRYPTO', 'Ethereum'],
    ['SOLUSDT', 'CRYPTO', 'Solana'],
    ['BNBUSDT', 'CRYPTO', 'BNB'],
    ['XRPUSDT', 'CRYPTO', 'XRP'],
    ['ADAUSDT', 'CRYPTO', 'Cardano'],
  ],
  replay: [['frxEURUSD', 'FOREX', 'EUR/USD (demo)']],
}

const draft = ref('')
const draftClass = ref('FOREX')

const current = computed(() => {
  try {
    const parsed = JSON.parse(props.modelValue || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return null
  }
})
const presets = computed(() => (PRESETS[props.source] || PRESETS.deriv).filter(
  ([symbol]) => !(current.value || []).some((item) => item.symbol === symbol),
))

function write(list) {
  emit('update:modelValue', JSON.stringify(list, null, 2))
}

function add(symbol, assetClass, label) {
  const clean = String(symbol || '').trim()
  if (!clean || current.value === null || current.value.some((item) => item.symbol === clean)) return
  write([...current.value, { symbol: clean, asset_class: assetClass, ...(label ? { display_name: label } : {}) }])
  draft.value = ''
}

function remove(symbol) {
  write((current.value || []).filter((item) => item.symbol !== symbol))
}
</script>

<template>
  <div class="field field-wide symbol-picker">
    <label>Symbols</label>
    <div v-if="current === null" class="note">The raw JSON below is invalid; fix it to use the picker.</div>
    <div v-else class="chip-row">
      <span v-for="item in current" :key="item.symbol" class="chip">
        {{ item.display_name || item.symbol }} <small>{{ item.asset_class }}</small>
        <button type="button" :aria-label="`Remove ${item.symbol}`" @click="remove(item.symbol)">×</button>
      </span>
      <span v-if="!current.length" class="muted">No symbols yet. Pick one below.</span>
    </div>
    <div class="chip-row">
      <button v-for="[symbol, assetClass, label] in presets" :key="symbol" class="chip chip-add" type="button" @click="add(symbol, assetClass, label)">
        + {{ label }}
      </button>
    </div>
    <div class="picker-custom">
      <input v-model="draft" class="input" type="text" placeholder="Custom symbol, e.g. frxEURJPY or DOGEUSDT" aria-label="Custom symbol" @keydown.enter.prevent="add(draft, draftClass)" />
      <select v-model="draftClass" class="select" aria-label="Asset class">
        <option>FOREX</option>
        <option>CRYPTO</option>
        <option>COMMODITIES</option>
        <option>INDICES</option>
        <option>SYNTHETIC</option>
      </select>
      <button class="button secondary" type="button" @click="add(draft, draftClass)">Add</button>
    </div>
  </div>
</template>
