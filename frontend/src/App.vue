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
  symbols: [],
  stats: {},
})

const settingsForm = reactive({
  paper_trading_enabled: true,
  risk_profile: 'balanced',
  max_open_positions: 6,
  rebalance_enabled: true,
  rebalance_key_mode: 'asset_class',
  rebalance_tolerance_pct: 8,
})

const tradeForm = reactive({
  symbol: 'frxEURUSD',
  side: 'BUY',
  exposure: 250,
  price: 0,
})

const allocationJson = ref('{}')

const stats = computed(() => bootstrapData.value.stats || {})
const market = computed(() => bootstrapData.value.market || [])
const signals = computed(() => bootstrapData.value.signals || [])
const portfolio = computed(() => bootstrapData.value.portfolio || [])
const tradeHistory = computed(() => bootstrapData.value.trade_history || [])
const rules = computed(() => bootstrapData.value.rules || [])
const rebalancePlan = computed(() => bootstrapData.value.rebalance_plan || { actions: [] })
const symbols = computed(() => bootstrapData.value.symbols || [])
const lastBacktest = computed(() => bootstrapData.value.last_backtest)

const marketMap = computed(() => {
  return Object.fromEntries(market.value.map((row) => [row.symbol, row]))
})

const portfolioExposureLabel = computed(() => formatCurrency(stats.value.total_exposure || 0))
const rebalanceDriftLabel = computed(() => formatPercent(rebalancePlan.value.drift_score || 0))
const passRateLabel = computed(() => {
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

function syncFromBootstrap() {
  const settings = bootstrapData.value.settings || {}
  settingsForm.paper_trading_enabled = Boolean(settings.paper_trading_enabled)
  settingsForm.risk_profile = settings.risk_profile || 'balanced'
  settingsForm.max_open_positions = Number(settings.max_open_positions || 6)
  settingsForm.rebalance_enabled = Boolean(settings.rebalance_enabled)
  settingsForm.rebalance_key_mode = settings.rebalance_key_mode || 'asset_class'
  settingsForm.rebalance_tolerance_pct = Number(settings.rebalance_tolerance || 0.08) * 100
  allocationJson.value = JSON.stringify(settings.target_allocations || {}, null, 2)

  if (!tradeForm.symbol && symbols.value.length) {
    tradeForm.symbol = symbols.value[0].symbol
  }
  updateTradePrice()
}

function updateTradePrice() {
  const selected = marketMap.value[tradeForm.symbol]
  if (selected) {
    tradeForm.price = Number(selected.price)
  }
}

async function fetchBootstrap() {
  try {
    const { data } = await api.get('bootstrap')
    bootstrapData.value = data
    syncFromBootstrap()
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
    await fetchBootstrap()
    if (successText) {
      setSuccess(successText)
    }
  } catch (error) {
    setError(error)
  } finally {
    busy.value = false
  }
}

async function saveSettings() {
  let targetAllocations = {}
  try {
    targetAllocations = JSON.parse(allocationJson.value || '{}')
  } catch (error) {
    setError(new Error('Target allocations must be valid JSON.'))
    return
  }

  await runAction(
    () =>
      api.post('config', {
        paper_trading_enabled: settingsForm.paper_trading_enabled,
        risk_profile: settingsForm.risk_profile,
        max_open_positions: settingsForm.max_open_positions,
        rebalance_enabled: settingsForm.rebalance_enabled,
        rebalance_key_mode: settingsForm.rebalance_key_mode,
        rebalance_tolerance: Number(settingsForm.rebalance_tolerance_pct || 0) / 100,
        target_allocations: targetAllocations,
      }),
    'Settings saved.',
  )
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

async function applyRebalance() {
  await runAction(() => api.post('paper-trades/rebalance'), 'Rebalance actions applied.')
}

async function runBacktests() {
  await runAction(() => api.post('backtests/run'), 'Backtests completed.')
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
        <h1>FX Scalper Community Edition</h1>
        <p>
          A browser-based companion experience with paper trading, simplified rules,
          transparent rebalancing, and built-in scenario backtests.
        </p>
      </div>

      <div class="hero-badges">
        <span class="badge">Paper Trading Only</span>
        <span class="badge">Vue 3 + Flask</span>
        <span class="badge">Glassmorphic Dashboard</span>
        <span class="badge">First-Party Hosted</span>
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
    </section>

    <div v-if="loading" class="card section-card">
      <div class="empty-state">Loading community edition bootstrap data...</div>
    </div>

    <template v-else>
      <section class="two-col section-stack">
        <article class="card section-card">
          <div class="section-head">
            <h2>Settings</h2>
            <p>Keep the demo configurable without exposing broker credentials or private execution logic.</p>
          </div>
          <div class="section-body">
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
            </div>

            <div class="toggle-row">
              <label class="check-line">
                <input v-model="settingsForm.paper_trading_enabled" type="checkbox" />
                <span>Paper trading enabled</span>
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

            <div class="actions">
              <button class="button" :disabled="busy" @click="saveSettings">Save Settings</button>
            </div>
          </div>
        </article>

        <article class="card section-card">
          <div class="section-head">
            <h2>Paper Trade Entry</h2>
            <p>Open demo positions from the current market snapshots.</p>
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
              <button class="button" :disabled="busy" @click="openPaperTrade">Open Paper Trade</button>
            </div>
          </div>
        </article>
      </section>

      <section class="two-col section-stack">
        <article class="card section-card">
          <div class="section-head">
            <h2>Signal Feed</h2>
            <p>Each market snapshot is evaluated with a simplified public rule stack.</p>
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
              </div>
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
            <p>Simple scenario checks verify signal and rebalance behavior after configuration changes.</p>
          </div>
          <div class="section-body">
            <div v-if="lastBacktest" class="stack-list">
              <div class="item-card">
                <div class="item-row">
                  <div class="item-title">Last Run</div>
                  <div class="kv">{{ lastBacktest.run_at }}</div>
                </div>
                <div class="item-row">
                  <div class="item-title">Scenarios</div>
                  <div class="kv">{{ lastBacktest.scenario_passes }} / {{ lastBacktest.scenario_total }}</div>
                </div>
                <div class="item-row">
                  <div class="item-title">Rebalance Check</div>
                  <div class="kv">{{ lastBacktest.rebalance_check?.action_count || 0 }} actions</div>
                </div>
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
            <p>The latest paper-trade and rebalance events stored in local JSON state.</p>
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
