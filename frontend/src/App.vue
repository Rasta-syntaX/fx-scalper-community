<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'

const baseUrl = import.meta.env.BASE_URL || '/'
const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ||
  `${baseUrl.replace(/\/+$/, '') || ''}/api/`
)
  .replace(/\/+$/, '/')

const api = axios.create({
  baseURL: apiBaseUrl,
})

const API_KEY_STORAGE = 'fx-scalper-community-api-key'

api.interceptors.request.use((config) => {
  const key = window.localStorage.getItem(API_KEY_STORAGE)
  if (key) {
    config.headers['X-API-Key'] = key
  }
  return config
})

api.interceptors.response.use(undefined, (error) => {
  const config = error?.config
  if (error?.response?.status !== 401 || !config || config._apiKeyRetried) {
    return Promise.reject(error)
  }
  const key = window.prompt('This backend requires an API key (COMMUNITY_API_KEY). Enter it:')
  if (!key) {
    return Promise.reject(error)
  }
  window.localStorage.setItem(API_KEY_STORAGE, key.trim())
  config._apiKeyRetried = true
  return api.request(config)
})

const loading = ref(true)
const busy = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const bootstrapData = ref({
  settings: {},
  market: [],
  signals: [],
  portfolio: [],
  trade_history: [],
  rules: [],
  rebalance_plan: { actions: [], current_weights: {}, target_weights: {} },
  last_backtest: null,
  last_broker_status: null,
  last_scan: null,
  symbols: [],
  stats: {},
  setup: {},
})

const settingsForm = reactive({
  trade_direction: 'both',
  daily_profit_target: 0,
  daily_loss_limit: 0,
  auto_scan_interval_seconds: 300,
  auto_hold_minutes: 25,
  auto_paper_exposure: 100,
  max_trades_per_day: 0,
  max_loss_streak: 0,
  loss_cooldown_minutes: 0,
  trading_hours_start: 0,
  trading_hours_end: 0,
  paper_trading_enabled: true,
  live_trading_enabled: false,
  broker_provider: 'deriv',
  deriv_app_id: '',
  deriv_token: '',
  deriv_api_url: 'https://api.derivws.com',
  deriv_ws_url: 'wss://ws.derivws.com/websockets/v3',
  deriv_options_account_mode: 'demo',
  deriv_options_account_id: '',
  risk_profile: 'balanced',
  max_open_positions: 6,
  live_trade_stake: 1,
  live_trade_currency: 'USD',
  live_trade_duration: 5,
  live_trade_duration_unit: 't',
  rebalance_enabled: true,
  rebalance_key_mode: 'asset_class',
  rebalance_tolerance_pct: 8,
})

const tradeForm = reactive({
  symbol: '',
  side: 'BUY',
  exposure: 250,
  price: 0,
})

const liveTradeForm = reactive({
  symbol: '',
  side: 'BUY',
  amount: 1,
  currency: 'USD',
  duration: 5,
  duration_unit: 't',
})

const allocationJson = ref('{}')
const symbolsJson = ref('[]')
const marketSnapshotsJson = ref('[]')
const liveOrderResult = ref(null)

const stats = computed(() => bootstrapData.value.stats || {})
const market = computed(() => bootstrapData.value.market || [])
const signals = computed(() => bootstrapData.value.signals || [])
const portfolio = computed(() => bootstrapData.value.portfolio || [])
const tradeHistory = computed(() => bootstrapData.value.trade_history || [])
const autoTrader = computed(() => bootstrapData.value.auto_trader || {})
const autoPerformance = computed(() => bootstrapData.value.auto_performance || {})

function sparkScale(points, height) {
  const low = Math.min(0, ...points)
  const span = Math.max(0, ...points) - low || 1
  return (value) => height - ((value - low) / span) * height
}

function sparkPath(points, width = 240, height = 48) {
  if (!points || points.length < 2) return ''
  const y = sparkScale(points, height)
  return points
    .map((value, index) => `${index ? 'L' : 'M'}${((index / (points.length - 1)) * width).toFixed(1)},${y(value).toFixed(1)}`)
    .join(' ')
}

function zeroLine(points, height = 48) {
  return points && points.length ? sparkScale(points, height)(0).toFixed(1) : height
}

async function startAuto(mode) {
  if (mode === 'live' && !window.confirm('Start LIVE auto-trading? Real trades will be placed on your broker account.')) {
    return
  }
  await runAction(() => api.post('auto/start', { mode }), `Auto-trader started (${mode}).`)
}

async function stopAuto() {
  await runAction(() => api.post('auto/stop'), 'Auto-trader stopped.')
}

async function exportJournal() {
  try {
    const { data } = await api.get('journal.csv', { responseType: 'blob' })
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = 'trade_log.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    setError(error)
  }
}
const rules = computed(() => bootstrapData.value.rules || [])
const rebalancePlan = computed(() => bootstrapData.value.rebalance_plan || { actions: [] })
const symbols = computed(() => bootstrapData.value.symbols || [])
const lastBacktest = computed(() => bootstrapData.value.last_backtest)
const candleBacktest = computed(() => lastBacktest.value?.candle_backtest || null)
const backtestOptions = ref({ horizon_bars: 5, candle_count: 1000, payout_pct: 0 })

function formatRate(value) {
  return value === null || value === undefined ? '–' : `${(value * 100).toFixed(1)}%`
}
const lastBrokerStatus = computed(() => bootstrapData.value.last_broker_status || null)
const setupStatus = computed(() => bootstrapData.value.setup || {})
const lastScan = computed(() => bootstrapData.value.last_scan || null)
const liveTradingReady = computed(() => Boolean(setupStatus.value.live_trading_ready))
const brokerStatusLabel = computed(() => {
  if (lastBrokerStatus.value?.connected) {
    return 'Connected'
  }
  if (lastBrokerStatus.value?.checked_at) {
    return 'Check Failed'
  }
  return 'Not Tested'
})
const brokerTokenLabel = computed(() => {
  if (lastBrokerStatus.value?.token_mode === 'pat') {
    return 'PAT'
  }
  if (lastBrokerStatus.value?.token_mode === 'legacy') {
    return 'Legacy'
  }
  if (settingsForm.deriv_token) {
    return settingsForm.deriv_token.startsWith('pat_') ? 'PAT' : 'Legacy'
  }
  return bootstrapData.value.settings?.deriv_token_mode === 'pat' ? 'PAT' : 'Legacy'
})

const derivTokenSaved = computed(() => Boolean(bootstrapData.value.settings?.deriv_token_set))

const marketMap = computed(() => {
  return Object.fromEntries(market.value.map((row) => [row.symbol, row]))
})

const portfolioExposureLabel = computed(() => formatCurrency(stats.value.total_exposure || 0))
const rebalanceDriftLabel = computed(() => formatPercent(rebalancePlan.value.drift_score || 0))
const passRateLabel = computed(() => {
  if (candleBacktest.value?.trades) {
    return `${formatRate(candleBacktest.value.win_rate)} of ${candleBacktest.value.trades}`
  }
  if (!lastBacktest.value?.scenario_total) {
    return 'Not run'
  }
  return `${lastBacktest.value.scenario_passes}/${lastBacktest.value.scenario_total}`
})

function clearMessages() {
  errorMessage.value = ''
  successMessage.value = ''
}

function setSuccess(message) {
  errorMessage.value = ''
  successMessage.value = message
}

function setError(error) {
  successMessage.value = ''
  errorMessage.value =
    error?.response?.data?.error ||
    error?.response?.data?.message ||
    error?.message ||
    'Unexpected error.'
}

function formatCurrency(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(Number(value || 0))
}

function formatPercent(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}

async function refreshBootstrapState() {
  const { data } = await api.get('bootstrap')
  bootstrapData.value = data
  syncFromBootstrap()
}

function syncFromBootstrap() {
  const settings = bootstrapData.value.settings || {}
  settingsForm.paper_trading_enabled = Boolean(settings.paper_trading_enabled)
  settingsForm.live_trading_enabled = Boolean(settings.live_trading_enabled)
  settingsForm.broker_provider = settings.broker_provider || 'deriv'
  settingsForm.deriv_app_id = settings.deriv_app_id || ''
  settingsForm.deriv_token = settings.deriv_token || ''
  settingsForm.deriv_api_url = settings.deriv_api_url || 'https://api.derivws.com'
  settingsForm.deriv_ws_url = settings.deriv_ws_url || 'wss://ws.derivws.com/websockets/v3'
  settingsForm.deriv_options_account_mode = settings.deriv_options_account_mode || 'demo'
  settingsForm.deriv_options_account_id = settings.deriv_options_account_id || ''
  settingsForm.risk_profile = settings.risk_profile || 'balanced'
  settingsForm.trade_direction = settings.trade_direction || 'both'
  settingsForm.daily_profit_target = Number(settings.daily_profit_target || 0)
  settingsForm.daily_loss_limit = Number(settings.daily_loss_limit || 0)
  settingsForm.auto_scan_interval_seconds = Number(settings.auto_scan_interval_seconds || 300)
  settingsForm.auto_hold_minutes = Number(settings.auto_hold_minutes || 25)
  settingsForm.auto_paper_exposure = Number(settings.auto_paper_exposure || 100)
  settingsForm.max_trades_per_day = Number(settings.max_trades_per_day || 0)
  settingsForm.max_loss_streak = Number(settings.max_loss_streak || 0)
  settingsForm.loss_cooldown_minutes = Number(settings.loss_cooldown_minutes || 0)
  settingsForm.trading_hours_start = Number(settings.trading_hours_start || 0)
  settingsForm.trading_hours_end = Number(settings.trading_hours_end || 0)
  settingsForm.max_open_positions = Number(settings.max_open_positions || 6)
  settingsForm.live_trade_stake = Number(settings.live_trade_stake || 1)
  settingsForm.live_trade_currency = settings.live_trade_currency || 'USD'
  settingsForm.live_trade_duration = Number(settings.live_trade_duration || 5)
  settingsForm.live_trade_duration_unit = settings.live_trade_duration_unit || 't'
  settingsForm.rebalance_enabled = Boolean(settings.rebalance_enabled)
  settingsForm.rebalance_key_mode = settings.rebalance_key_mode || 'asset_class'
  settingsForm.rebalance_tolerance_pct = Number(settings.rebalance_tolerance || 0.08) * 100
  allocationJson.value = JSON.stringify(settings.target_allocations || {}, null, 2)
  symbolsJson.value = JSON.stringify(settings.symbols || [], null, 2)
  marketSnapshotsJson.value = JSON.stringify(settings.market_snapshots || [], null, 2)

  if (symbols.value.length) {
    if (!symbols.value.some((item) => item.symbol === tradeForm.symbol)) {
      tradeForm.symbol = symbols.value[0].symbol
    }
  } else {
    tradeForm.symbol = ''
  }
  if (!tradeForm.symbol && symbols.value.length) {
    tradeForm.symbol = symbols.value[0].symbol
  }
  if (symbols.value.length) {
    if (!symbols.value.some((item) => item.symbol === liveTradeForm.symbol)) {
      liveTradeForm.symbol = symbols.value[0].symbol
    }
  } else {
    liveTradeForm.symbol = ''
  }
  liveTradeForm.amount = Number(settings.live_trade_stake || 1)
  liveTradeForm.currency = settings.live_trade_currency || 'USD'
  liveTradeForm.duration = Number(settings.live_trade_duration || 5)
  liveTradeForm.duration_unit = settings.live_trade_duration_unit || 't'
  updateTradePrice()
}

function updateTradePrice() {
  const selected = marketMap.value[tradeForm.symbol]
  if (selected) {
    tradeForm.price = Number(selected.price)
    return
  }
  tradeForm.price = 0
}

async function fetchBootstrap() {
  try {
    await refreshBootstrapState()
  } catch (error) {
    setError(error)
  } finally {
    loading.value = false
  }
}

async function runAction(action, successText) {
  clearMessages()
  busy.value = true
  try {
    await action()
    await refreshBootstrapState()
    if (successText) {
      setSuccess(successText)
    }
  } catch (error) {
    setError(error)
  } finally {
    busy.value = false
  }
}

async function forgetDerivToken() {
  await runAction(() => api.post('config', { clear_deriv_token: true }), 'Saved Deriv token removed.')
}

async function saveSettings() {
  let targetAllocations = {}
  let configuredSymbols = []
  let configuredMarketSnapshots = []
  try {
    targetAllocations = JSON.parse(allocationJson.value || '{}')
  } catch (error) {
    setError(new Error('Target allocations must be valid JSON.'))
    return
  }
  try {
    configuredSymbols = JSON.parse(symbolsJson.value || '[]')
    if (!Array.isArray(configuredSymbols)) {
      throw new Error('Configured symbols must be a JSON array.')
    }
  } catch (error) {
    setError(new Error('Configured symbols must be a valid JSON array.'))
    return
  }
  try {
    configuredMarketSnapshots = JSON.parse(marketSnapshotsJson.value || '[]')
    if (!Array.isArray(configuredMarketSnapshots)) {
      throw new Error('Market snapshots must be a JSON array.')
    }
  } catch (error) {
    setError(new Error('Market snapshots must be a valid JSON array.'))
    return
  }

  await runAction(
    () =>
      api.post('config', {
        paper_trading_enabled: settingsForm.paper_trading_enabled,
        live_trading_enabled: settingsForm.live_trading_enabled,
        broker_provider: settingsForm.broker_provider,
        deriv_app_id: settingsForm.deriv_app_id,
        deriv_token: settingsForm.deriv_token,
        deriv_api_url: settingsForm.deriv_api_url,
        deriv_ws_url: settingsForm.deriv_ws_url,
        deriv_options_account_mode: settingsForm.deriv_options_account_mode,
        deriv_options_account_id: settingsForm.deriv_options_account_id,
        risk_profile: settingsForm.risk_profile,
        trade_direction: settingsForm.trade_direction,
        daily_profit_target: Number(settingsForm.daily_profit_target),
        daily_loss_limit: Number(settingsForm.daily_loss_limit),
        auto_scan_interval_seconds: Number(settingsForm.auto_scan_interval_seconds),
        auto_hold_minutes: Number(settingsForm.auto_hold_minutes),
        auto_paper_exposure: Number(settingsForm.auto_paper_exposure),
        max_trades_per_day: Number(settingsForm.max_trades_per_day),
        max_loss_streak: Number(settingsForm.max_loss_streak),
        loss_cooldown_minutes: Number(settingsForm.loss_cooldown_minutes),
        trading_hours_start: Number(settingsForm.trading_hours_start),
        trading_hours_end: Number(settingsForm.trading_hours_end),
        max_open_positions: settingsForm.max_open_positions,
        live_trade_stake: Number(settingsForm.live_trade_stake),
        live_trade_currency: settingsForm.live_trade_currency,
        live_trade_duration: Number(settingsForm.live_trade_duration),
        live_trade_duration_unit: settingsForm.live_trade_duration_unit,
        rebalance_enabled: settingsForm.rebalance_enabled,
        rebalance_key_mode: settingsForm.rebalance_key_mode,
        rebalance_tolerance: Number(settingsForm.rebalance_tolerance_pct || 0) / 100,
        target_allocations: targetAllocations,
        symbols: configuredSymbols,
        market_snapshots: configuredMarketSnapshots,
      }),
    'Settings saved.',
  )
}

async function scanMarket() {
  clearMessages()
  busy.value = true
  try {
    const { data } = await api.post('scan')
    await refreshBootstrapState()
    setSuccess(data?.message || 'Market scan complete.')
  } catch (error) {
    await refreshBootstrapState()
    setError(error)
  } finally {
    busy.value = false
  }
}

async function testBrokerConnection() {
  clearMessages()
  busy.value = true
  try {
    const { data } = await api.post('broker/test')
    await refreshBootstrapState()
    if (data?.ok) {
      setSuccess(data.message || 'Deriv connection verified.')
      return
    }
    setError(new Error(data?.message || 'Deriv connection failed.'))
  } catch (error) {
    await refreshBootstrapState()
    setError(error)
  } finally {
    busy.value = false
  }
}

async function openPaperTrade() {
  await runAction(
    () =>
      api.post('paper-trades/open', {
        symbol: tradeForm.symbol,
        side: tradeForm.side,
        exposure: Number(tradeForm.exposure),
        price: Number(tradeForm.price),
      }),
    'Paper trade opened.',
  )
}

async function quickTrade(signal) {
  tradeForm.symbol = signal.symbol
  tradeForm.side = signal.decision
  tradeForm.exposure = 250
  tradeForm.price = Number(signal.price)
  await openPaperTrade()
}

async function submitLiveTrade() {
  clearMessages()
  busy.value = true
  liveOrderResult.value = null
  try {
    const { data } = await api.post('live-trades/open', {
      symbol: liveTradeForm.symbol,
      side: liveTradeForm.side,
      amount: Number(liveTradeForm.amount),
      currency: liveTradeForm.currency,
      duration: Number(liveTradeForm.duration),
      duration_unit: liveTradeForm.duration_unit,
    })
    liveOrderResult.value = data
    await refreshBootstrapState()
    setSuccess(data?.message || 'Live trade submitted.')
  } catch (error) {
    liveOrderResult.value = error?.response?.data || null
    await refreshBootstrapState()
    setError(error)
  } finally {
    busy.value = false
  }
}

async function quickLiveTrade(signal) {
  liveTradeForm.symbol = signal.symbol
  liveTradeForm.side = signal.decision
  await submitLiveTrade()
}

async function applyRebalance() {
  await runAction(() => api.post('paper-trades/rebalance'), 'Rebalance actions applied.')
}

async function runBacktests() {
  await runAction(() => api.post('backtests/run', backtestOptions.value), 'Backtests completed.')
}

async function resetDemo() {
  await runAction(() => api.post('reset'), 'Demo state reset.')
}

onMounted(fetchBootstrap)
</script>

<template>
  <main class="page-shell">
    <section class="hero-panel">
      <div class="hero-copy">
        <div class="eyebrow">Hosted Community Edition</div>
        <h1>Community Edition</h1>
        <p>
          Bring your own Deriv credentials, symbol universe, and market snapshots to run a
          configurable paper-trading workflow without editing source code.
        </p>
      </div>

      <div class="hero-badges">
        <span class="badge">Paper + Live Optional</span>
        <span class="badge">Deriv Broker Test</span>
        <span class="badge">Vue 3 + Flask</span>
        <span class="badge">Self-Hosted</span>
      </div>

      <div class="stats-grid">
        <article class="card stat-card">
          <div class="stat-label">Open Signals</div>
          <div class="stat-value">{{ stats.signal_count || 0 }}</div>
        </article>
        <article class="card stat-card">
          <div class="stat-label">Open Positions</div>
          <div class="stat-value">{{ stats.open_positions || 0 }}</div>
        </article>
        <article class="card stat-card">
          <div class="stat-label">Portfolio Exposure</div>
          <div class="stat-value stat-value-sm">{{ portfolioExposureLabel }}</div>
        </article>
        <article class="card stat-card">
          <div class="stat-label">Rebalance Drift</div>
          <div class="stat-value">{{ rebalanceDriftLabel }}</div>
        </article>
        <article class="card stat-card">
          <div class="stat-label">Backtest Pass Rate</div>
          <div class="stat-value stat-value-sm">{{ passRateLabel }}</div>
        </article>
      </div>

      <div v-if="errorMessage" class="status-banner error">{{ errorMessage }}</div>
      <div v-if="successMessage" class="status-banner success">{{ successMessage }}</div>

      <div class="actions">
        <button class="button" :disabled="busy" @click="runBacktests">Run Backtests</button>
        <button class="button secondary" :disabled="busy" @click="applyRebalance">
          Apply Rebalance
        </button>
        <button class="button secondary" :disabled="busy" @click="resetDemo">Reset Demo</button>
      </div>

      <div class="card section-card">
        <div class="section-head">
          <h2>Auto-Trader</h2>
          <p>
            Scans every {{ settingsForm.auto_scan_interval_seconds }}s and acts on signals in the allowed direction.
            Stops opening trades for the day when a daily limit is hit. Stop is the kill switch.
          </p>
        </div>
        <div class="section-body stack-list">
          <div class="item-row">
            <div class="item-title">
              {{ autoTrader.running ? `Running (${autoTrader.mode})` : 'Stopped' }}
            </div>
            <div class="actions">
              <button class="button" :disabled="busy || autoTrader.running" @click="startAuto('paper')">Start Paper</button>
              <button class="button secondary" :disabled="busy || autoTrader.running" @click="startAuto('live')">Start Live</button>
              <button class="button secondary" :disabled="busy || !autoTrader.running" @click="stopAuto">Stop</button>
            </div>
          </div>
          <div class="item-row">
            <span>Today {{ autoTrader.day || '–' }}: {{ formatCurrency(autoTrader.realized_pnl || 0) }} realized</span>
            <span>{{ autoTrader.trades_today || 0 }} trades · {{ (autoTrader.pending_live || []).length }} live pending</span>
          </div>
          <div v-if="autoTrader.halted_reason" class="status-banner error">{{ autoTrader.halted_reason }}</div>
          <div v-if="autoTrader.last_error" class="note">Last error: {{ autoTrader.last_error }}</div>
          <div v-if="autoTrader.paused_reason" class="note">Paused: {{ autoTrader.paused_reason }}</div>
          <div class="kv">Last tick {{ autoTrader.last_tick || 'never' }} · loss streak {{ autoTrader.loss_streak || 0 }}</div>
          <div v-if="autoPerformance.trades" class="item-card">
            <div class="item-row">
              <div class="item-title">Performance (last {{ autoPerformance.trades }} closed trades)</div>
              <div class="kv">win {{ formatRate(autoPerformance.win_rate) }} · {{ formatCurrency(autoPerformance.pnl) }}</div>
            </div>
            <svg v-if="(autoPerformance.equity_curve || []).length > 1" viewBox="0 0 240 48" preserveAspectRatio="none" style="width: 100%; height: 48px" role="img" :aria-label="'Auto-trader equity curve'">
              <line x1="0" x2="240" :y1="zeroLine(autoPerformance.equity_curve)" :y2="zeroLine(autoPerformance.equity_curve)" stroke="currentColor" stroke-opacity="0.25" stroke-dasharray="4 4" />
              <path :d="sparkPath(autoPerformance.equity_curve)" fill="none" :stroke="(autoPerformance.equity_curve)[(autoPerformance.equity_curve).length - 1] >= 0 ? '#22c55e' : '#ef4444'" stroke-width="2" vector-effect="non-scaling-stroke" />
            </svg>
            <div v-for="row in autoPerformance.by_symbol" :key="`perf-${row.symbol}`" class="item-row">
              <span>{{ row.symbol }}</span>
              <span class="muted">{{ row.trades }} trades · win {{ formatRate(row.win_rate) }} · {{ formatCurrency(row.pnl) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card section-card">
        <div class="section-head">
          <h2>Setup Checklist</h2>
          <p>{{ setupStatus.recommended_next_step || 'Review the configuration before trading.' }}</p>
        </div>
        <div class="section-body">
          <div class="stack-list">
            <div class="item-row">
              <span>Deriv credentials</span>
              <span class="kv">{{ setupStatus.broker_configured ? 'Configured' : 'Missing' }}</span>
            </div>
            <div class="item-row">
              <span>Configured symbols</span>
              <span class="kv">{{ setupStatus.symbols_configured ? 'Ready' : 'Missing' }}</span>
            </div>
            <div class="item-row">
              <span>Market snapshots</span>
              <span class="kv">{{ setupStatus.market_snapshots_configured ? 'Ready' : 'Missing' }}</span>
            </div>
            <div class="item-row">
              <span>Paper-trading flow</span>
              <span class="kv">{{ setupStatus.paper_trading_ready ? 'Available' : 'Blocked' }}</span>
            </div>
            <div class="item-row">
              <span>Live trading enabled</span>
              <span class="kv">{{ settingsForm.live_trading_enabled ? 'Yes' : 'No' }}</span>
            </div>
            <div class="item-row">
              <span>Live-trading flow</span>
              <span class="kv">{{ setupStatus.live_trading_ready ? 'Ready' : 'Blocked' }}</span>
            </div>
            <div class="item-row">
              <span>Broker status</span>
              <span class="kv">{{ brokerStatusLabel }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <div v-if="loading" class="card section-card">
      <div class="empty-state">Loading community edition bootstrap data...</div>
    </div>

    <template v-else>
      <section class="two-col section-stack">
        <article class="card section-card">
          <div class="section-head">
            <h2>Settings</h2>
            <p>Store your own runtime configuration locally, including Deriv credentials, symbol definitions, and live-trade defaults.</p>
          </div>
          <div class="section-body">
            <div class="form-grid">
              <div class="field">
                <label>Broker Provider</label>
                <input v-model="settingsForm.broker_provider" class="input" type="text" readonly />
              </div>
              <div class="field">
                <label>Deriv App ID</label>
                <input v-model="settingsForm.deriv_app_id" class="input" type="text" placeholder="Enter your Deriv app ID" />
              </div>
              <div class="field">
                <label>Deriv API Token</label>
                <input
                  v-model="settingsForm.deriv_token"
                  class="input"
                  type="password"
                  autocomplete="off"
                  :placeholder="derivTokenSaved ? 'Saved — leave blank to keep it' : 'Paste your Deriv token'"
                />
                <button
                  v-if="derivTokenSaved"
                  class="button secondary"
                  type="button"
                  :disabled="busy"
                  @click="forgetDerivToken"
                >
                  Forget saved token
                </button>
              </div>
              <div class="field">
                <label>Deriv REST URL</label>
                <input v-model="settingsForm.deriv_api_url" class="input" type="text" />
              </div>
              <div class="field">
                <label>Deriv WebSocket URL</label>
                <input v-model="settingsForm.deriv_ws_url" class="input" type="text" />
              </div>
              <div class="field">
                <label>Options Account Mode</label>
                <select v-model="settingsForm.deriv_options_account_mode" class="select">
                  <option value="demo">Demo</option>
                  <option value="real">Real</option>
                </select>
              </div>
              <div class="field">
                <label>Resolved Options Account ID</label>
                <input
                  v-model="settingsForm.deriv_options_account_id"
                  class="input"
                  type="text"
                  placeholder="Optional account ID override"
                />
              </div>
            </div>

            <div class="form-grid">
              <div class="field">
                <label>Risk Profile</label>
                <select v-model="settingsForm.risk_profile" class="select">
                  <option value="conservative">Conservative</option>
                  <option value="balanced">Balanced</option>
                  <option value="aggressive">Aggressive</option>
                </select>
              </div>
              <div class="field">
                <label>Max Open Positions</label>
                <input v-model.number="settingsForm.max_open_positions" class="input" type="number" min="1" max="20" />
              </div>
              <div class="field">
                <label>Trade Direction</label>
                <select v-model="settingsForm.trade_direction" class="select">
                  <option value="both">Buy and sell</option>
                  <option value="buy">Buy only</option>
                  <option value="sell">Sell only</option>
                </select>
              </div>
              <div class="field">
                <label>Daily Profit Target (0 = off)</label>
                <input v-model.number="settingsForm.daily_profit_target" class="input" type="number" min="0" step="0.01" />
              </div>
              <div class="field">
                <label>Daily Loss Limit (0 = off)</label>
                <input v-model.number="settingsForm.daily_loss_limit" class="input" type="number" min="0" step="0.01" />
              </div>
              <div class="field">
                <label>Auto Scan Every (seconds)</label>
                <input v-model.number="settingsForm.auto_scan_interval_seconds" class="input" type="number" min="30" max="3600" />
              </div>
              <div class="field">
                <label>Auto Paper Hold (minutes)</label>
                <input v-model.number="settingsForm.auto_hold_minutes" class="input" type="number" min="1" max="1440" />
              </div>
              <div class="field">
                <label>Auto Paper Exposure</label>
                <input v-model.number="settingsForm.auto_paper_exposure" class="input" type="number" min="1" />
              </div>
              <div class="field">
                <label>Max Trades Per Day (0 = off)</label>
                <input v-model.number="settingsForm.max_trades_per_day" class="input" type="number" min="0" max="1000" />
              </div>
              <div class="field">
                <label>Halt After Losses In A Row (0 = off)</label>
                <input v-model.number="settingsForm.max_loss_streak" class="input" type="number" min="0" max="100" />
              </div>
              <div class="field">
                <label>Cooldown After A Loss (minutes)</label>
                <input v-model.number="settingsForm.loss_cooldown_minutes" class="input" type="number" min="0" max="1440" />
              </div>
              <div class="field">
                <label>Trade From (UTC hour)</label>
                <input v-model.number="settingsForm.trading_hours_start" class="input" type="number" min="0" max="23" />
              </div>
              <div class="field">
                <label>Trade Until (UTC hour, same = all day)</label>
                <input v-model.number="settingsForm.trading_hours_end" class="input" type="number" min="0" max="24" />
              </div>
              <div class="field">
                <label>Rebalance Tolerance %</label>
                <input
                  v-model.number="settingsForm.rebalance_tolerance_pct"
                  class="input"
                  type="number"
                  min="0"
                  max="50"
                  step="0.5"
                />
              </div>
              <div class="field">
                <label>Allocation Mode</label>
                <select v-model="settingsForm.rebalance_key_mode" class="select">
                  <option value="asset_class">Asset Class</option>
                  <option value="symbol">Symbol</option>
                </select>
              </div>
              <div class="field">
                <label>Live Stake</label>
                <input v-model.number="settingsForm.live_trade_stake" class="input" type="number" min="0.35" step="0.01" />
              </div>
              <div class="field">
                <label>Live Currency</label>
                <input v-model="settingsForm.live_trade_currency" class="input" type="text" maxlength="10" />
              </div>
              <div class="field">
                <label>Live Duration</label>
                <input v-model.number="settingsForm.live_trade_duration" class="input" type="number" min="1" max="365" />
              </div>
              <div class="field">
                <label>Live Duration Unit</label>
                <select v-model="settingsForm.live_trade_duration_unit" class="select">
                  <option value="t">Ticks</option>
                  <option value="s">Seconds</option>
                  <option value="m">Minutes</option>
                  <option value="h">Hours</option>
                  <option value="d">Days</option>
                </select>
              </div>
            </div>

            <div class="toggle-row">
              <label class="check-line">
                <input v-model="settingsForm.paper_trading_enabled" type="checkbox" />
                <span>Paper trading enabled</span>
              </label>
              <label class="check-line">
                <input v-model="settingsForm.live_trading_enabled" type="checkbox" />
                <span>Live trading enabled</span>
              </label>
              <label class="check-line">
                <input v-model="settingsForm.rebalance_enabled" type="checkbox" />
                <span>Auto rebalance enabled</span>
              </label>
            </div>

            <div class="field">
              <label>Target Allocations JSON</label>
              <textarea
                v-model="allocationJson"
                class="textarea code-block"
                spellcheck="false"
                placeholder='{"FOREX": 0.4, "SYNTHETICS": 0.25}'
              />
            </div>

            <div class="field">
              <label>Configured Symbols JSON</label>
              <textarea
                v-model="symbolsJson"
                class="textarea code-block"
                spellcheck="false"
                placeholder='[{"symbol":"frxEURUSD","label":"EUR/USD","asset_class":"FOREX"}]'
              />
            </div>

            <div class="field">
              <label>Market Snapshots JSON</label>
              <textarea
                v-model="marketSnapshotsJson"
                class="textarea code-block"
                spellcheck="false"
                placeholder='[{"symbol":"frxEURUSD","price":1.0865,"ema_fast":1.0862,"ema_slow":1.0851,"adx":22,"rsi":55,"atr_ratio":1.04,"price_vs_vwap":"above","candle_quality":"clean","distance_to_band":0.45}]'
              />
            </div>

            <div class="actions">
              <button class="button" :disabled="busy" @click="saveSettings">Save Settings</button>
              <button
                class="button secondary"
                :disabled="busy || !symbols.length"
                @click="scanMarket"
              >
                Scan Market Now
              </button>
            </div>
          </div>
        </article>

        <article class="card section-card">
          <div class="section-head">
            <h2>Broker Connection</h2>
            <p>Verify your saved Deriv settings before attempting a live order.</p>
          </div>
          <div class="section-body">
            <div class="item-card">
              <div class="item-row">
                <div class="item-title">Connection State</div>
                <span
                  class="signal-pill"
                  :class="lastBrokerStatus?.connected ? 'buy' : lastBrokerStatus?.checked_at ? 'sell' : 'hold'"
                >
                  {{ brokerStatusLabel }}
                </span>
              </div>
              <div class="item-row">
                <span class="muted">Last checked</span>
                <span class="kv">{{ lastBrokerStatus?.checked_at || 'Never' }}</span>
              </div>
              <div class="item-row">
                <span class="muted">Token mode</span>
                <span class="kv">{{ brokerTokenLabel }}</span>
              </div>
              <div class="item-row">
                <span class="muted">Account</span>
                <span class="kv">{{ lastBrokerStatus?.loginid || lastBrokerStatus?.options_account_id || 'Unknown' }}</span>
              </div>
              <div class="item-row">
                <span class="muted">Balance</span>
                <span class="kv">
                  {{
                    lastBrokerStatus?.balance !== undefined
                      ? `${lastBrokerStatus.balance} ${lastBrokerStatus.currency || ''}`.trim()
                      : 'Unavailable'
                  }}
                </span>
              </div>
              <p class="note">
                {{ lastBrokerStatus?.message || 'No Deriv test has been run yet for this local workspace.' }}
              </p>
            </div>
            <div class="actions">
              <button class="button" :disabled="busy" @click="testBrokerConnection">Test Deriv Connection</button>
              <button class="button secondary" :disabled="busy" @click="fetchBootstrap">Refresh Dashboard</button>
            </div>
            <div class="empty-state">
              PAT tokens use the configured Deriv options-account flow. Legacy tokens use WebSocket authorize.
            </div>
          </div>
        </article>
      </section>

      <section class="two-col section-stack">
        <article class="card section-card">
          <div class="section-head">
            <h2>Paper Trade Entry</h2>
            <p>Open paper positions against the symbols and prices you configured.</p>
          </div>
          <div class="section-body">
            <div class="form-grid">
              <div class="field">
                <label>Symbol</label>
                <select v-model="tradeForm.symbol" class="select" @change="updateTradePrice">
                  <option v-for="item in symbols" :key="item.symbol" :value="item.symbol">
                    {{ item.label }} ({{ item.asset_class }})
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Side</label>
                <select v-model="tradeForm.side" class="select">
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                </select>
              </div>
              <div class="field">
                <label>Exposure</label>
                <input v-model.number="tradeForm.exposure" class="input" type="number" min="50" step="50" />
              </div>
              <div class="field">
                <label>Entry Price</label>
                <input v-model.number="tradeForm.price" class="input" type="number" min="0.0001" step="0.0001" />
              </div>
            </div>
            <div class="actions">
              <button class="button" :disabled="busy || !tradeForm.symbol" @click="openPaperTrade">Open Paper Trade</button>
            </div>
            <div v-if="!symbols.length" class="empty-state">
              Add at least one symbol in Settings before opening a paper trade.
            </div>
          </div>
        </article>

        <article class="card section-card">
          <div class="section-head">
            <h2>Live Trade Entry</h2>
            <p>Send an optional Deriv order using the saved broker settings and live defaults.</p>
          </div>
          <div class="section-body">
            <div class="form-grid">
              <div class="field">
                <label>Symbol</label>
                <select v-model="liveTradeForm.symbol" class="select">
                  <option v-for="item in symbols" :key="`live-${item.symbol}`" :value="item.symbol">
                    {{ item.label }} ({{ item.asset_class }})
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Direction</label>
                <select v-model="liveTradeForm.side" class="select">
                  <option value="BUY">BUY / CALL</option>
                  <option value="SELL">SELL / PUT</option>
                </select>
              </div>
              <div class="field">
                <label>Stake</label>
                <input v-model.number="liveTradeForm.amount" class="input" type="number" min="0.35" step="0.01" />
              </div>
              <div class="field">
                <label>Currency</label>
                <input v-model="liveTradeForm.currency" class="input" type="text" maxlength="10" />
              </div>
              <div class="field">
                <label>Duration</label>
                <input v-model.number="liveTradeForm.duration" class="input" type="number" min="1" max="365" />
              </div>
              <div class="field">
                <label>Unit</label>
                <select v-model="liveTradeForm.duration_unit" class="select">
                  <option value="t">Ticks</option>
                  <option value="s">Seconds</option>
                  <option value="m">Minutes</option>
                  <option value="h">Hours</option>
                  <option value="d">Days</option>
                </select>
              </div>
            </div>
            <div class="actions">
              <button class="button" :disabled="busy || !liveTradeForm.symbol || !liveTradingReady" @click="submitLiveTrade">
                Submit Live Trade
              </button>
            </div>
            <div class="empty-state">
              Live trading remains opt-in. Save settings, enable live trading, and test the broker connection first.
            </div>
            <div v-if="liveOrderResult" class="item-card">
              <div class="item-row">
                <div class="item-title">Last Live Response</div>
                <span class="kv">{{ liveOrderResult.message || liveOrderResult.error || 'Response captured' }}</span>
              </div>
              <div class="item-row">
                <span class="muted">Proposal</span>
                <span class="kv">
                  {{ liveOrderResult.proposal?.id || liveOrderResult.request?.symbol || 'Unavailable' }}
                </span>
              </div>
              <div class="item-row">
                <span class="muted">Contract</span>
                <span class="kv">
                  {{ liveOrderResult.buy?.contract_id || liveOrderResult.buy?.transaction_id || 'Pending' }}
                </span>
              </div>
            </div>
          </div>
        </article>
      </section>

      <section class="two-col section-stack">
        <article class="card section-card">
          <div class="section-head">
            <h2>Signal Feed</h2>
            <p>Each saved market snapshot is evaluated with the simplified public rule stack.</p>
            <p v-if="lastScan" class="note">
              Last scan {{ lastScan.at }} · source {{ lastScan.source }} ·
              {{ lastScan.scanned }}/{{ lastScan.configured_symbols }} symbol(s) ·
              {{ (lastScan.errors || []).length }} error(s)
            </p>
            <p v-if="lastScan && lastScan.errors && lastScan.errors.length" class="note">
              {{ lastScan.errors.map((item) => item.symbol + ': ' + item.error).join(' | ') }}
            </p>
          </div>
          <div class="section-body grid-cards">
            <div v-for="row in market" :key="row.symbol" class="item-card">
              <div class="item-row">
                <div>
                  <div class="item-title">{{ row.symbol }}</div>
                  <div class="muted">{{ row.asset_class }} · {{ row.regime }}</div>
                </div>
                <span class="signal-pill" :class="row.decision.toLowerCase()">{{ row.decision }}</span>
              </div>
              <div class="metric-grid">
                <div class="metric">
                  <span class="metric-label">Price</span>
                  <span class="metric-value">{{ row.price }}</span>
                </div>
                <div class="metric">
                  <span class="metric-label">ADX</span>
                  <span class="metric-value">{{ row.adx }}</span>
                </div>
                <div class="metric">
                  <span class="metric-label">RSI</span>
                  <span class="metric-value">{{ row.rsi }}</span>
                </div>
                <div class="metric">
                  <span class="metric-label">VWAP</span>
                  <span class="metric-value">{{ row.price_vs_vwap }}</span>
                </div>
              </div>
              <p class="note">{{ row.reason }}</p>
              <div class="actions">
                <button
                  class="button secondary"
                  :disabled="busy || row.decision === 'HOLD'"
                  @click="quickTrade(row)"
                >
                  Open From Signal
                </button>
                <button
                  class="button secondary"
                  :disabled="busy || row.decision === 'HOLD' || !liveTradingReady"
                  @click="quickLiveTrade(row)"
                >
                  Send Live Order
                </button>
              </div>
            </div>
            <div v-if="!market.length" class="empty-state">
              No market snapshots yet. Add symbols in Settings, then press Scan Market Now to read
              candles and generate signals. You can also paste snapshot JSON in Settings by hand.
            </div>
          </div>
        </article>

        <article class="card section-card">
          <div class="section-head">
            <h2>Rebalancing</h2>
            <p>Track drift versus target allocations and apply one-step corrective actions.</p>
          </div>
          <div class="section-body">
            <div class="item-card">
              <div class="item-row">
                <div class="item-title">Mode</div>
                <div class="kv">{{ rebalancePlan.key_mode || 'asset_class' }}</div>
              </div>
              <div class="item-row">
                <div class="item-title">Tolerance</div>
                <div class="kv">{{ formatPercent(rebalancePlan.tolerance || 0) }}</div>
              </div>
              <div class="item-row">
                <div class="item-title">Enabled</div>
                <div class="kv">{{ rebalancePlan.enabled ? 'Yes' : 'No' }}</div>
              </div>
            </div>

            <div class="weight-grid">
              <div class="item-card">
                <div class="item-title">Current Weights</div>
                <div v-if="Object.keys(rebalancePlan.current_weights || {}).length" class="stack-list">
                  <div
                    v-for="(value, key) in rebalancePlan.current_weights"
                    :key="`current-${key}`"
                    class="item-row"
                  >
                    <span>{{ key }}</span>
                    <span>{{ formatPercent(value) }}</span>
                  </div>
                </div>
                <div v-else class="empty-state">No current exposure.</div>
              </div>

              <div class="item-card">
                <div class="item-title">Target Weights</div>
                <div v-if="Object.keys(rebalancePlan.target_weights || {}).length" class="stack-list">
                  <div
                    v-for="(value, key) in rebalancePlan.target_weights"
                    :key="`target-${key}`"
                    class="item-row"
                  >
                    <span>{{ key }}</span>
                    <span>{{ formatPercent(value) }}</span>
                  </div>
                </div>
                <div v-else class="empty-state">No target weights configured.</div>
              </div>
            </div>

            <div class="stack-list">
              <div v-for="action in rebalancePlan.actions" :key="`${action.action}-${action.allocation_key}`" class="item-card">
                <div class="item-row">
                  <div class="item-title">{{ action.action }}</div>
                  <div class="kv">{{ action.allocation_key }}</div>
                </div>
                <div class="note">{{ action.reason }}</div>
              </div>
              <div v-if="!rebalancePlan.actions?.length" class="empty-state">
                Rebalance is within tolerance.
              </div>
            </div>
          </div>
        </article>
      </section>

      <section class="two-col section-stack">
        <article class="card section-card">
          <div class="section-head">
            <h2>Portfolio</h2>
            <p>Current demo positions with refreshed market prices.</p>
          </div>
          <div class="section-body stack-list">
            <div v-for="position in portfolio" :key="position.id" class="item-card">
              <div class="item-row">
                <div>
                  <div class="item-title">{{ position.symbol }}</div>
                  <div class="muted">{{ position.asset_class }} · {{ position.side }}</div>
                </div>
                <div class="signal-pill" :class="position.side.toLowerCase()">{{ position.side }}</div>
              </div>
              <div class="metric-grid">
                <div class="metric">
                  <span class="metric-label">Exposure</span>
                  <span class="metric-value">{{ formatCurrency(position.exposure) }}</span>
                </div>
                <div class="metric">
                  <span class="metric-label">Entry</span>
                  <span class="metric-value">{{ position.entry_price }}</span>
                </div>
                <div class="metric">
                  <span class="metric-label">Current</span>
                  <span class="metric-value">{{ position.current_price }}</span>
                </div>
              </div>
            </div>
            <div v-if="!portfolio.length" class="empty-state">No paper positions are open.</div>
          </div>
        </article>

        <article class="card section-card">
          <div class="section-head">
            <h2>Backtests</h2>
            <p>
              Walk-forward replay of the live rules over real candles: enter at the next open, exit after a fixed
              number of bars. Price moves only; payouts and spreads are not modelled.
            </p>
            <div class="item-row">
              <label>Exit after (bars) <input v-model.number="backtestOptions.horizon_bars" type="number" min="1" max="100" /></label>
              <label>Candles <input v-model.number="backtestOptions.candle_count" type="number" min="150" max="5000" /></label>
              <label>Payout % (0 = off) <input v-model.number="backtestOptions.payout_pct" type="number" min="0" max="500" /></label>
            </div>
          </div>
          <div class="section-body">
            <div v-if="lastBacktest" class="stack-list">
              <div class="item-card">
                <div class="item-row">
                  <div class="item-title">Last Run</div>
                  <div class="kv">{{ lastBacktest.run_at }}</div>
                </div>
                <div v-if="candleBacktest" class="item-row">
                  <div class="item-title">Candle Backtest</div>
                  <div class="kv">
                    {{ candleBacktest.trades || 0 }} trades · win {{ formatRate(candleBacktest.win_rate) }} ·
                    {{ candleBacktest.source }} {{ candleBacktest.granularity }}s
                  </div>
                </div>
                <div class="item-row">
                  <div class="item-title">Rule Self-checks</div>
                  <div class="kv">{{ lastBacktest.scenario_passes }} / {{ lastBacktest.scenario_total }}</div>
                </div>
                <div class="item-row">
                  <div class="item-title">Rebalance Check</div>
                  <div class="kv">{{ lastBacktest.rebalance_check?.action_count || 0 }} actions</div>
                </div>
              </div>

              <div v-for="row in candleBacktest?.results || []" :key="`bt-${row.symbol}`" class="item-card">
                <div class="item-row">
                  <div class="item-title">{{ row.symbol }}</div>
                  <div class="kv">{{ row.trades }} trades · win {{ formatRate(row.win_rate) }}</div>
                </div>
                <div class="item-row">
                  <span class="muted">Total {{ row.total_return_pct }}% · max DD {{ row.max_drawdown_pct }}%</span>
                  <span class="muted">{{ row.bars_evaluated }} bars over {{ row.candles }} candles</span>
                </div>
                <div v-if="row.payout" class="item-row">
                  <span class="muted">At {{ Math.round(row.payout * 100) }}% payout: {{ row.net_per_stake >= 0 ? '+' : '' }}{{ row.net_per_stake }} per $1 staked</span>
                  <span class="muted">break-even win rate {{ formatRate(row.break_even_win_rate) }}</span>
                </div>
                <svg v-if="(row.equity_curve || []).length > 1" viewBox="0 0 240 48" preserveAspectRatio="none" style="width: 100%; height: 48px" role="img" :aria-label="`${row.symbol} equity curve`">
                  <line x1="0" x2="240" :y1="zeroLine(row.equity_curve)" :y2="zeroLine(row.equity_curve)" stroke="currentColor" stroke-opacity="0.25" stroke-dasharray="4 4" />
                  <path :d="sparkPath(row.equity_curve)" fill="none" :stroke="(row.equity_curve)[(row.equity_curve).length - 1] >= 0 ? '#22c55e' : '#ef4444'" stroke-width="2" vector-effect="non-scaling-stroke" />
                </svg>
              </div>
              <div v-for="error in candleBacktest?.errors || []" :key="`bterr-${error.symbol}`" class="item-card">
                <div class="item-row">
                  <div class="item-title">{{ error.symbol }}</div>
                  <span class="signal-pill sell">ERROR</span>
                </div>
                <div class="note">{{ error.error }}</div>
              </div>

              <div v-for="result in lastBacktest.scenario_results" :key="result.name" class="item-card">
                <div class="item-row">
                  <div class="item-title">{{ result.name }}</div>
                  <span class="signal-pill" :class="result.passed ? 'buy' : 'sell'">
                    {{ result.passed ? 'PASS' : 'FAIL' }}
                  </span>
                </div>
                <div class="item-row">
                  <span class="muted">Expected {{ result.expected }}</span>
                  <span class="muted">Actual {{ result.actual }}</span>
                </div>
                <div class="note">{{ result.reason }}</div>
              </div>
            </div>
            <div v-else class="empty-state">Run backtests to generate the latest scenario report.</div>
          </div>
        </article>
      </section>

      <section class="two-col section-stack">
        <article class="card section-card">
          <div class="section-head">
            <h2>Rule Registry</h2>
            <p>Public documentation for the simplified rule stack shipped in the community repo.</p>
          </div>
          <div class="section-body stack-list">
            <div v-for="rule in rules" :key="rule.id" class="item-card">
              <div class="item-title">{{ rule.name }}</div>
              <p class="note">{{ rule.purpose }}</p>
              <div class="tag-row">
                <span v-for="item in rule.inputs" :key="`${rule.id}-${item}`" class="badge subtle">{{ item }}</span>
              </div>
            </div>
          </div>
        </article>

        <article class="card section-card">
          <div class="section-head">
            <h2>Recent Activity</h2>
            <p>The latest paper-trade and rebalance events. The full history is kept in the CSV journal.</p>
            <button class="button secondary" type="button" @click="exportJournal">Export CSV</button>
          </div>
          <div class="section-body stack-list">
            <div v-for="entry in tradeHistory" :key="`${entry.timestamp}-${entry.symbol}-${entry.type}`" class="item-card">
              <div class="item-row">
                <div class="item-title">{{ entry.type }}</div>
                <div class="kv">{{ entry.timestamp }}</div>
              </div>
              <div class="item-row">
                <span>{{ entry.symbol || 'SYSTEM' }}</span>
                <span>{{ entry.side || 'N/A' }}</span>
              </div>
              <div class="item-row">
                <span>{{ formatCurrency(entry.exposure) }}</span>
                <span class="muted">{{ entry.note }}</span>
              </div>
            </div>
            <div v-if="!tradeHistory.length" class="empty-state">No trade history recorded yet.</div>
          </div>
        </article>
      </section>
    </template>
  </main>
</template>
