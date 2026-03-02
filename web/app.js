const { createApp, ref, computed, watch, onMounted, onUnmounted, nextTick, reactive } = Vue;

const API_BASE = window.location.origin;

// ─── Helpers ──────────────────────────────────────────────
async function api(path, opts = {}) {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json();
}

function debounce(fn, ms = 300) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function formatDate(d) {
  if (!d) return '-';
  return new Date(d).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// ─── Shared Components ───────────────────────────────────

const LoadingSpinner = {
  props: { small: Boolean },
  template: `
    <div :class="small ? '' : 'spinner-overlay'">
      <div class="spinner" :class="{ 'spinner-sm': small }"></div>
    </div>`,
};

const StatusBadge = {
  props: { status: String },
  setup(props) {
    const map = { new: '新发现', confirmed: '已确认', archived: '已归档', rejected: '已拒绝' };
    const label = computed(() => map[props.status] || props.status);
    const cls = computed(() => 'badge badge-' + (props.status || 'new'));
    return { label, cls };
  },
  template: `<span :class="cls">{{ label }}</span>`,
};

const TrendIndicator = {
  props: { trend: String },
  setup(props) {
    const display = computed(() => {
      const m = { rising: '↑ 上升', stable: '→ 稳定', declining: '↓ 下降' };
      return m[props.trend] || props.trend || '-';
    });
    const cls = computed(() => 'trend-' + (props.trend || 'stable'));
    return { display, cls };
  },
  template: `<span :class="cls">{{ display }}</span>`,
};

const Pagination = {
  props: { page: Number, pageSize: Number, total: Number },
  emits: ['update:page'],
  setup(props, { emit }) {
    const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));
    const pages = computed(() => {
      const tp = totalPages.value, c = props.page, arr = [];
      const start = Math.max(1, c - 2), end = Math.min(tp, c + 2);
      if (start > 1) { arr.push(1); if (start > 2) arr.push('...'); }
      for (let i = start; i <= end; i++) arr.push(i);
      if (end < tp) { if (end < tp - 1) arr.push('...'); arr.push(tp); }
      return arr;
    });
    const go = (p) => { if (typeof p === 'number' && p >= 1 && p <= totalPages.value) emit('update:page', p); };
    return { totalPages, pages, go };
  },
  template: `
    <div class="pagination" v-if="total > pageSize">
      <button :disabled="page <= 1" @click="go(page - 1)">上一页</button>
      <button v-for="p in pages" :key="p" :class="{ active: p === page }" :disabled="p === '...'" @click="go(p)">{{ p }}</button>
      <button :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
      <span class="ml-3 text-xs text-gray-500">共 {{ total }} 条</span>
    </div>`,
};

const Modal = {
  props: { title: String },
  emits: ['close'],
  template: `
    <div class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-content">
        <div class="modal-header">
          <h3 class="text-lg font-semibold">{{ title }}</h3>
          <button @click="$emit('close')" class="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div class="modal-body"><slot></slot></div>
      </div>
    </div>`,
};

// ─── Dashboard ───────────────────────────────────────────

const Dashboard = {
  components: { LoadingSpinner, StatusBadge, TrendIndicator },
  setup() {
    const loading = ref(true);
    const data = ref({
      total_demands: 0, new_this_week: 0, total_articles: 0, analyzed_ratio: 0,
      category_distribution: [], daily_trend: [], top_demands: [], rising_demands: [],
    });
    let pieChart = null, lineChart = null, timer = null;

    async function load() {
      try {
        data.value = await api('/api/analytics/overview');
      } catch (e) {
        console.error('Dashboard load failed:', e);
      } finally {
        loading.value = false;
      }
      await nextTick();
      renderCharts();
    }

    function renderCharts() {
      const catData = data.value.category_distribution || [];
      const pieEl = document.getElementById('chart-category');
      if (pieEl) {
        if (pieChart) pieChart.destroy();
        pieChart = new Chart(pieEl, {
          type: 'doughnut',
          data: {
            labels: catData.map(c => c.name || c.category),
            datasets: [{ data: catData.map(c => c.count || c.value), backgroundColor: ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#06b6d4','#84cc16'] }],
          },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right' } } },
        });
      }
      const trendData = data.value.daily_trend || [];
      const lineEl = document.getElementById('chart-daily');
      if (lineEl) {
        if (lineChart) lineChart.destroy();
        lineChart = new Chart(lineEl, {
          type: 'line',
          data: {
            labels: trendData.map(t => t.date),
            datasets: [{ label: '新增需求', data: trendData.map(t => t.count), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, tension: 0.3 }],
          },
          options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } }, plugins: { legend: { display: false } } },
        });
      }
    }

    onMounted(() => { load(); timer = setInterval(load, 5 * 60 * 1000); });
    onUnmounted(() => { clearInterval(timer); if (pieChart) pieChart.destroy(); if (lineChart) lineChart.destroy(); });

    const stats = computed(() => [
      { icon: '📋', label: '需求总数', value: data.value.total_demands, color: 'text-blue-600' },
      { icon: '🆕', label: '本周新增', value: data.value.new_this_week, color: 'text-green-600' },
      { icon: '📰', label: '文章总数', value: data.value.total_articles, color: 'text-purple-600' },
      { icon: '📊', label: '已分析比例', value: ((data.value.analyzed_ratio || 0) * 100).toFixed(1) + '%', color: 'text-amber-600' },
    ]);

    return { loading, data, stats };
  },
  template: `
    <loading-spinner v-if="loading" />
    <div v-else>
      <!-- Stat Cards -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div v-for="s in stats" :key="s.label" class="card stat-card">
          <div class="flex justify-between items-start">
            <div>
              <div class="stat-label">{{ s.label }}</div>
              <div class="stat-value" :class="s.color">{{ s.value }}</div>
            </div>
            <span class="stat-icon">{{ s.icon }}</span>
          </div>
        </div>
      </div>

      <!-- Charts -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <div class="card">
          <h3 class="font-semibold text-gray-700 mb-3">需求分类分布</h3>
          <div class="chart-container"><canvas id="chart-category"></canvas></div>
        </div>
        <div class="card">
          <h3 class="font-semibold text-gray-700 mb-3">最近7天需求趋势</h3>
          <div class="chart-container"><canvas id="chart-daily"></canvas></div>
        </div>
      </div>

      <!-- Lists -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div class="card">
          <h3 class="font-semibold text-gray-700 mb-3">🔥 最新发现的需求 TOP 10</h3>
          <div v-if="!data.top_demands?.length" class="text-sm text-gray-400 py-4 text-center">暂无数据</div>
          <div v-for="(d, i) in (data.top_demands || []).slice(0, 10)" :key="d.id" class="flex items-center gap-3 py-2 border-b border-gray-100 last:border-0">
            <span class="text-xs font-bold w-5 text-gray-400">{{ i + 1 }}</span>
            <span class="flex-1 text-sm truncate">{{ d.title }}</span>
            <status-badge :status="d.status" />
          </div>
        </div>
        <div class="card">
          <h3 class="font-semibold text-gray-700 mb-3">📈 趋势上升的需求 TOP 10</h3>
          <div v-if="!data.rising_demands?.length" class="text-sm text-gray-400 py-4 text-center">暂无数据</div>
          <div v-for="(d, i) in (data.rising_demands || []).slice(0, 10)" :key="d.id" class="flex items-center gap-3 py-2 border-b border-gray-100 last:border-0">
            <span class="text-xs font-bold w-5 text-gray-400">{{ i + 1 }}</span>
            <span class="flex-1 text-sm truncate">{{ d.title }}</span>
            <trend-indicator :trend="d.trend" />
          </div>
        </div>
      </div>
    </div>`,
};

// ─── Demands Page ────────────────────────────────────────

const Demands = {
  components: { LoadingSpinner, StatusBadge, TrendIndicator, Pagination },
  setup() {
    const loading = ref(false);
    const demands = ref([]);
    const total = ref(0);
    const page = ref(1);
    const pageSize = ref(20);
    const filters = reactive({ category: '', status: '', trend: '', search: '' });
    const sortBy = ref('frequency');
    const sortOrder = ref('desc');
    const categories = ref([]);

    // Detail panel
    const selectedDemand = ref(null);
    const relatedArticles = ref([]);
    const notes = ref('');
    const saving = ref(false);
    const detailLoading = ref(false);

    async function loadDemands() {
      loading.value = true;
      try {
        const params = new URLSearchParams({ page: page.value, page_size: pageSize.value, sort_by: sortBy.value, sort_order: sortOrder.value });
        if (filters.category) params.set('category', filters.category);
        if (filters.status) params.set('status', filters.status);
        if (filters.trend) params.set('trend', filters.trend);
        if (filters.search) params.set('search', filters.search);
        const res = await api(`/api/demands?${params}`);
        demands.value = res.items || res.data || [];
        total.value = res.total || 0;
      } catch (e) {
        console.error('Load demands failed:', e);
      } finally {
        loading.value = false;
      }
    }

    async function loadCategories() {
      try {
        const res = await api('/api/demands/categories');
        categories.value = res.categories || res || [];
      } catch {}
    }

    async function openDetail(d) {
      selectedDemand.value = d;
      notes.value = d.notes || '';
      relatedArticles.value = [];
      detailLoading.value = true;
      try {
        const res = await api(`/api/demands/${d.id}`);
        selectedDemand.value = { ...d, ...res };
        relatedArticles.value = res.related_articles || [];
        notes.value = res.notes || '';
      } catch {} finally {
        detailLoading.value = false;
      }
    }

    function closeDetail() { selectedDemand.value = null; }

    async function saveNotes() {
      if (!selectedDemand.value) return;
      saving.value = true;
      try {
        await api(`/api/demands/${selectedDemand.value.id}`, { method: 'PUT', body: JSON.stringify({ notes: notes.value }) });
        selectedDemand.value.notes = notes.value;
      } catch (e) {
        alert('保存失败: ' + e.message);
      } finally {
        saving.value = false;
      }
    }

    async function updateStatus(status) {
      if (!selectedDemand.value) return;
      try {
        await api(`/api/demands/${selectedDemand.value.id}`, { method: 'PUT', body: JSON.stringify({ status }) });
        selectedDemand.value.status = status;
        loadDemands();
      } catch (e) {
        alert('操作失败: ' + e.message);
      }
    }

    function setSort(field) {
      if (sortBy.value === field) { sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'; }
      else { sortBy.value = field; sortOrder.value = 'desc'; }
      page.value = 1;
      loadDemands();
    }

    function sortIcon(field) {
      if (sortBy.value !== field) return '';
      return sortOrder.value === 'desc' ? ' ▼' : ' ▲';
    }

    const handleSearch = debounce(() => { page.value = 1; loadDemands(); });
    watch([() => filters.category, () => filters.status, () => filters.trend], () => { page.value = 1; loadDemands(); });
    watch(page, loadDemands);
    onMounted(() => { loadDemands(); loadCategories(); });

    return { loading, demands, total, page, pageSize, filters, sortBy, sortOrder, categories,
      selectedDemand, relatedArticles, notes, saving, detailLoading,
      loadDemands, openDetail, closeDetail, saveNotes, updateStatus, setSort, sortIcon, handleSearch, formatDate };
  },
  template: `
    <div>
      <!-- Filters -->
      <div class="card mb-4">
        <div class="flex flex-wrap items-center gap-3">
          <select v-model="filters.category" class="border rounded-lg px-3 py-2 text-sm">
            <option value="">全部分类</option>
            <option v-for="c in categories" :key="c.name || c" :value="c.name || c">{{ c.name || c }}</option>
          </select>
          <select v-model="filters.status" class="border rounded-lg px-3 py-2 text-sm">
            <option value="">全部状态</option>
            <option value="new">新发现</option>
            <option value="confirmed">已确认</option>
            <option value="archived">已归档</option>
            <option value="rejected">已拒绝</option>
          </select>
          <select v-model="filters.trend" class="border rounded-lg px-3 py-2 text-sm">
            <option value="">全部趋势</option>
            <option value="rising">上升</option>
            <option value="stable">稳定</option>
            <option value="declining">下降</option>
          </select>
          <input v-model="filters.search" @input="handleSearch" placeholder="搜索需求..." class="border rounded-lg px-3 py-2 text-sm flex-1 min-w-[200px]">
          <span class="text-xs text-gray-400">排序:</span>
          <button v-for="s in [{k:'frequency',l:'频次'},{k:'importance',l:'重要性'},{k:'created_at',l:'时间'}]" :key="s.k"
                  @click="setSort(s.k)"
                  class="text-xs px-2 py-1 rounded"
                  :class="sortBy === s.k ? 'bg-blue-100 text-blue-700 font-semibold' : 'text-gray-500 hover:bg-gray-100'">
            {{ s.l }}{{ sortIcon(s.k) }}
          </button>
        </div>
      </div>

      <!-- Table -->
      <div class="card p-0 overflow-x-auto">
        <loading-spinner v-if="loading" />
        <table v-else class="data-table">
          <thead>
            <tr>
              <th class="w-16">ID</th>
              <th>标题</th>
              <th>分类</th>
              <th class="w-20">频次</th>
              <th class="w-20">重要性</th>
              <th class="w-24">趋势</th>
              <th class="w-24">状态</th>
              <th class="w-20">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!demands.length"><td colspan="8" class="text-center text-gray-400 py-8">暂无数据</td></tr>
            <tr v-for="d in demands" :key="d.id" @click="openDetail(d)">
              <td class="text-gray-400 text-xs">{{ d.id }}</td>
              <td class="font-medium">{{ d.title }}</td>
              <td><span class="text-xs bg-gray-100 text-gray-600 rounded px-2 py-0.5">{{ d.category || '-' }}</span></td>
              <td>{{ d.frequency ?? d.freq ?? '-' }}</td>
              <td>{{ d.importance ?? '-' }}</td>
              <td><trend-indicator :trend="d.trend" /></td>
              <td><status-badge :status="d.status" /></td>
              <td @click.stop>
                <button class="text-blue-500 hover:text-blue-700 text-xs" @click="openDetail(d)">详情</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <pagination :page="page" :page-size="pageSize" :total="total" @update:page="page = $event" />

      <!-- Detail Panel -->
      <div v-if="selectedDemand" class="detail-panel">
        <div class="detail-panel-header">
          <h3 class="font-semibold text-lg">需求详情</h3>
          <button @click="closeDetail" class="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>
        <div class="detail-panel-body">
          <loading-spinner v-if="detailLoading" />
          <template v-else>
            <div class="mb-4">
              <h4 class="font-semibold text-base mb-1">{{ selectedDemand.title }}</h4>
              <div class="flex items-center gap-2 mb-2">
                <status-badge :status="selectedDemand.status" />
                <trend-indicator :trend="selectedDemand.trend" />
              </div>
              <p class="text-sm text-gray-600 mb-2">{{ selectedDemand.description || '暂无描述' }}</p>
              <div class="grid grid-cols-2 gap-2 text-xs text-gray-500">
                <div>分类: <strong>{{ selectedDemand.category || '-' }}</strong></div>
                <div>频次: <strong>{{ selectedDemand.frequency ?? '-' }}</strong></div>
                <div>重要性: <strong>{{ selectedDemand.importance ?? '-' }}</strong></div>
                <div>更新: <strong>{{ formatDate(selectedDemand.updated_at) }}</strong></div>
              </div>
            </div>

            <!-- Related Articles -->
            <div class="mb-4">
              <h5 class="font-semibold text-sm text-gray-600 mb-2">📰 相关文章</h5>
              <div v-if="!relatedArticles.length" class="text-xs text-gray-400">暂无相关文章</div>
              <a v-for="a in relatedArticles" :key="a.id" :href="a.url" target="_blank"
                 class="block text-sm text-blue-600 hover:underline py-1 truncate">{{ a.title }}</a>
            </div>

            <!-- Notes -->
            <div class="mb-4">
              <h5 class="font-semibold text-sm text-gray-600 mb-2">📝 备注</h5>
              <textarea v-model="notes" rows="4" class="w-full border rounded-lg p-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-300" placeholder="添加备注..."></textarea>
              <button @click="saveNotes" :disabled="saving" class="action-btn bg-blue-500 text-white mt-1">
                <span v-if="saving" class="spinner spinner-sm"></span>{{ saving ? '保存中...' : '保存备注' }}
              </button>
            </div>

            <!-- Actions -->
            <div class="flex gap-2 pt-2 border-t">
              <button @click="updateStatus('confirmed')" class="action-btn bg-green-500 text-white flex-1">✓ 确认</button>
              <button @click="updateStatus('rejected')" class="action-btn bg-red-500 text-white flex-1">✕ 拒绝</button>
              <button @click="updateStatus('archived')" class="action-btn bg-gray-400 text-white flex-1">📦 归档</button>
            </div>
          </template>
        </div>
      </div>
      <div v-if="selectedDemand" class="fixed inset-0 bg-black/20 z-40" @click="closeDetail"></div>
    </div>`,
};

// ─── Articles Page ───────────────────────────────────────

const Articles = {
  components: { LoadingSpinner, StatusBadge, Pagination, Modal },
  setup() {
    const loading = ref(false);
    const articles = ref([]);
    const total = ref(0);
    const page = ref(1);
    const pageSize = ref(20);
    const filters = reactive({ platform: '', date_from: '', date_to: '' });
    const showDetail = ref(false);
    const selectedArticle = ref(null);
    const articleDemands = ref([]);
    const detailLoading = ref(false);

    async function loadArticles() {
      loading.value = true;
      try {
        const params = new URLSearchParams({ page: page.value, page_size: pageSize.value });
        if (filters.platform) params.set('platform', filters.platform);
        if (filters.date_from) params.set('date_from', filters.date_from);
        if (filters.date_to) params.set('date_to', filters.date_to);
        const res = await api(`/api/articles?${params}`);
        articles.value = res.items || res.data || [];
        total.value = res.total || 0;
      } catch (e) {
        console.error('Load articles failed:', e);
      } finally {
        loading.value = false;
      }
    }

    async function openDetail(a) {
      selectedArticle.value = a;
      showDetail.value = true;
      articleDemands.value = [];
      detailLoading.value = true;
      try {
        const res = await api(`/api/articles/${a.id}`);
        selectedArticle.value = { ...a, ...res };
        articleDemands.value = res.demands || res.extracted_demands || [];
      } catch {} finally {
        detailLoading.value = false;
      }
    }

    watch([() => filters.platform, () => filters.date_from, () => filters.date_to], () => { page.value = 1; loadArticles(); });
    watch(page, loadArticles);
    onMounted(loadArticles);

    return { loading, articles, total, page, pageSize, filters, showDetail, selectedArticle, articleDemands, detailLoading, openDetail, formatDate };
  },
  template: `
    <div>
      <!-- Filters -->
      <div class="card mb-4">
        <div class="flex flex-wrap items-center gap-3">
          <select v-model="filters.platform" class="border rounded-lg px-3 py-2 text-sm">
            <option value="">全部平台</option>
            <option value="zhihu">知乎</option>
            <option value="xiaohongshu">小红书</option>
            <option value="douyin">抖音</option>
            <option value="weixin">微信公众号</option>
            <option value="boss">BOSS直聘</option>
          </select>
          <label class="text-sm text-gray-500">从</label>
          <input v-model="filters.date_from" type="date" class="border rounded-lg px-3 py-2 text-sm">
          <label class="text-sm text-gray-500">到</label>
          <input v-model="filters.date_to" type="date" class="border rounded-lg px-3 py-2 text-sm">
        </div>
      </div>

      <!-- Table -->
      <div class="card p-0 overflow-x-auto">
        <loading-spinner v-if="loading" />
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>标题</th>
              <th class="w-24">平台</th>
              <th class="w-24">作者</th>
              <th class="w-20">热度分</th>
              <th class="w-32">发布时间</th>
              <th class="w-24">分析状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!articles.length"><td colspan="6" class="text-center text-gray-400 py-8">暂无数据</td></tr>
            <tr v-for="a in articles" :key="a.id" @click="openDetail(a)">
              <td class="font-medium truncate max-w-xs">{{ a.title }}</td>
              <td><span class="text-xs bg-blue-50 text-blue-600 rounded px-2 py-0.5">{{ a.platform }}</span></td>
              <td class="text-sm">{{ a.author || '-' }}</td>
              <td>{{ a.heat_score ?? a.score ?? '-' }}</td>
              <td class="text-xs text-gray-500">{{ formatDate(a.published_at || a.created_at) }}</td>
              <td>
                <span class="badge" :class="a.analyzed ? 'badge-confirmed' : 'badge-new'">{{ a.analyzed ? '已分析' : '待分析' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <pagination :page="page" :page-size="pageSize" :total="total" @update:page="page = $event" />

      <!-- Article Detail Modal -->
      <modal v-if="showDetail" :title="selectedArticle?.title || '文章详情'" @close="showDetail = false">
        <loading-spinner v-if="detailLoading" />
        <template v-else>
          <div class="mb-4">
            <div class="flex items-center gap-2 text-sm text-gray-500 mb-3">
              <span>{{ selectedArticle?.platform }}</span>
              <span>·</span>
              <span>{{ selectedArticle?.author }}</span>
              <span>·</span>
              <span>{{ formatDate(selectedArticle?.published_at) }}</span>
            </div>
            <h5 class="font-semibold text-sm mb-2">📝 摘要</h5>
            <p class="text-sm text-gray-600 leading-relaxed mb-4">{{ selectedArticle?.summary || '暂无摘要' }}</p>
          </div>
          <div>
            <h5 class="font-semibold text-sm mb-2">💡 提炼出的需求</h5>
            <div v-if="!articleDemands.length" class="text-sm text-gray-400">暂无提炼需求</div>
            <div v-for="d in articleDemands" :key="d.id" class="flex items-center gap-2 py-2 border-b border-gray-100">
              <span class="flex-1 text-sm">{{ d.title }}</span>
              <span class="badge badge-new text-xs">{{ d.category || '未分类' }}</span>
            </div>
          </div>
        </template>
      </modal>
    </div>`,
};

// ─── Trends Page ─────────────────────────────────────────

const Trends = {
  components: { LoadingSpinner, StatusBadge, TrendIndicator },
  setup() {
    const loading = ref(true);
    const timeRange = ref(8);
    const trendData = ref({ top_demands_trend: [], emerging_demands: [], insight_report: '', demand_graph: { nodes: [], edges: [] } });
    let trendChart = null, network = null;

    async function load() {
      loading.value = true;
      try {
        const [trends, graph] = await Promise.all([
          api(`/api/analytics/trends?weeks=${timeRange.value}`),
          api('/api/analytics/demand-graph').catch(() => ({ nodes: [], edges: [] })),
        ]);
        trendData.value = { ...trends, demand_graph: graph };
      } catch (e) {
        console.error('Trends load failed:', e);
      } finally {
        loading.value = false;
      }
      await nextTick();
      renderTrendChart();
      renderNetwork();
    }

    function renderTrendChart() {
      const items = trendData.value.top_demands_trend || [];
      const el = document.getElementById('chart-trends');
      if (!el || !items.length) return;
      if (trendChart) trendChart.destroy();
      const colors = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#06b6d4','#84cc16','#f97316','#64748b'];
      const allDates = [...new Set(items.flatMap(i => (i.data || []).map(d => d.date)))].sort();
      const datasets = items.slice(0, 10).map((item, idx) => ({
        label: item.title || item.name,
        data: allDates.map(date => { const pt = (item.data || []).find(d => d.date === date); return pt ? pt.value : 0; }),
        borderColor: colors[idx % colors.length],
        tension: 0.3,
        fill: false,
        pointRadius: 2,
      }));
      trendChart = new Chart(el, {
        type: 'line',
        data: { labels: allDates, datasets },
        options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
          plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } },
          scales: { y: { beginAtZero: true } } },
      });
    }

    function renderNetwork() {
      const graph = trendData.value.demand_graph || {};
      const container = document.getElementById('network-graph');
      if (!container || !graph.nodes?.length) return;
      if (network) network.destroy();
      const nodes = new vis.DataSet((graph.nodes || []).map(n => ({
        id: n.id, label: n.label || n.title, value: n.frequency || n.size || 10,
        color: { background: '#dbeafe', border: '#3b82f6', highlight: { background: '#93c5fd', border: '#2563eb' } },
        font: { size: 12 },
      })));
      const edges = new vis.DataSet((graph.edges || []).map(e => ({
        from: e.from || e.source, to: e.to || e.target,
        color: { color: '#cbd5e1', highlight: '#64748b' }, width: e.weight || 1,
      })));
      network = new vis.Network(container, { nodes, edges }, {
        physics: { stabilization: { iterations: 100 }, barnesHut: { gravitationalConstant: -3000 } },
        interaction: { hover: true, tooltipDelay: 200 },
        nodes: { shape: 'dot', scaling: { min: 10, max: 40 } },
      });
      network.on('click', (params) => {
        if (params.nodes.length) {
          const nodeId = params.nodes[0];
          const node = (graph.nodes || []).find(n => n.id === nodeId);
          if (node) alert(`需求: ${node.label || node.title}\n频次: ${node.frequency || '-'}`);
        }
      });
    }

    watch(timeRange, load);
    onMounted(load);
    onUnmounted(() => { if (trendChart) trendChart.destroy(); if (network) network.destroy(); });

    return { loading, timeRange, trendData };
  },
  template: `
    <div>
      <!-- Time Range -->
      <div class="card mb-4 flex items-center gap-3">
        <span class="text-sm text-gray-600 font-medium">时间范围:</span>
        <button v-for="w in [4, 8, 12]" :key="w" @click="timeRange = w"
                class="px-3 py-1 rounded-lg text-sm"
                :class="timeRange === w ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'">
          最近 {{ w }} 周
        </button>
      </div>

      <loading-spinner v-if="loading" />
      <template v-else>
        <!-- Trend Chart -->
        <div class="card mb-4">
          <h3 class="font-semibold text-gray-700 mb-3">📈 TOP 10 需求热度趋势</h3>
          <div class="chart-container" style="height: 350px;"><canvas id="chart-trends"></canvas></div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
          <!-- Emerging Demands -->
          <div class="card">
            <h3 class="font-semibold text-gray-700 mb-3">🌱 新兴需求</h3>
            <div v-if="!(trendData.emerging_demands || []).length" class="text-sm text-gray-400 py-4 text-center">暂无数据</div>
            <div v-for="d in (trendData.emerging_demands || [])" :key="d.id" class="flex items-center gap-2 py-2 border-b border-gray-100 last:border-0">
              <span class="badge badge-new">新兴</span>
              <span class="text-sm flex-1">{{ d.title }}</span>
              <span class="text-xs text-gray-400">频次 {{ d.frequency ?? '-' }}</span>
            </div>
          </div>

          <!-- AI Insight Report -->
          <div class="card">
            <h3 class="font-semibold text-gray-700 mb-3">🤖 AI 趋势洞察报告</h3>
            <div v-if="!trendData.insight_report" class="text-sm text-gray-400 py-4 text-center">暂无报告</div>
            <div v-else class="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">{{ trendData.insight_report }}</div>
          </div>
        </div>

        <!-- Network Graph -->
        <div class="card">
          <h3 class="font-semibold text-gray-700 mb-3">🔗 需求关系网络</h3>
          <div id="network-graph" class="network-container"></div>
        </div>
      </template>
    </div>`,
};

// ─── Tag Cloud Page ──────────────────────────────────────

const TagCloud = {
  components: { LoadingSpinner },
  setup() {
    const loading = ref(true);
    const tags = ref([]);
    const categoryCounts = ref([]);
    const selectedTag = ref('');
    const filteredDemands = ref([]);
    const filterLoading = ref(false);

    async function load() {
      loading.value = true;
      try {
        const [tagsRes, catRes] = await Promise.all([
          api('/api/demands/tags'),
          api('/api/demands/categories'),
        ]);
        tags.value = tagsRes.tags || tagsRes || [];
        categoryCounts.value = catRes.categories || catRes || [];
      } catch (e) {
        console.error('TagCloud load failed:', e);
      } finally {
        loading.value = false;
      }
    }

    function tagSize(count) {
      const max = Math.max(...tags.value.map(t => t.count || 1), 1);
      const min = Math.min(...tags.value.map(t => t.count || 1), 1);
      const ratio = max === min ? 1 : (count - min) / (max - min);
      return 0.75 + ratio * 1.5;
    }

    async function clickTag(tag) {
      selectedTag.value = tag.name || tag.tag;
      filterLoading.value = true;
      try {
        const res = await api(`/api/demands?tag=${encodeURIComponent(selectedTag.value)}&page_size=20`);
        filteredDemands.value = res.items || res.data || [];
      } catch {} finally {
        filterLoading.value = false;
      }
    }

    onMounted(load);
    return { loading, tags, categoryCounts, selectedTag, filteredDemands, filterLoading, tagSize, clickTag };
  },
  template: `
    <loading-spinner v-if="loading" />
    <div v-else>
      <!-- Tag Cloud -->
      <div class="card mb-4">
        <h3 class="font-semibold text-gray-700 mb-3">🏷️ 标签云</h3>
        <div v-if="!tags.length" class="text-sm text-gray-400 py-8 text-center">暂无标签</div>
        <div class="tag-cloud">
          <span v-for="t in tags" :key="t.name || t.tag"
                class="tag-cloud-item"
                :class="{ 'bg-indigo-600 text-white': selectedTag === (t.name || t.tag) }"
                :style="{ fontSize: tagSize(t.count || 1) + 'rem' }"
                @click="clickTag(t)">
            {{ t.name || t.tag }}
            <sup class="text-xs opacity-60 ml-0.5">{{ t.count }}</sup>
          </span>
        </div>
      </div>

      <!-- Filtered Demands -->
      <div v-if="selectedTag" class="card mb-4">
        <h3 class="font-semibold text-gray-700 mb-3">🔍 标签 "{{ selectedTag }}" 的需求</h3>
        <loading-spinner v-if="filterLoading" :small="true" />
        <div v-else-if="!filteredDemands.length" class="text-sm text-gray-400 py-4 text-center">暂无匹配需求</div>
        <div v-for="d in filteredDemands" :key="d.id" class="flex items-center gap-2 py-2 border-b border-gray-100 last:border-0">
          <span class="text-sm flex-1">{{ d.title }}</span>
          <span class="text-xs text-gray-400">{{ d.category }}</span>
        </div>
      </div>

      <!-- Category Cards -->
      <div>
        <h3 class="font-semibold text-gray-700 mb-3">📂 分类概览</h3>
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          <div v-for="c in categoryCounts" :key="c.name || c.category" class="card text-center">
            <div class="text-2xl font-bold text-blue-600">{{ c.count ?? 0 }}</div>
            <div class="text-sm text-gray-500 mt-1">{{ c.name || c.category }}</div>
          </div>
        </div>
      </div>
    </div>`,
};

// ─── Settings Page ───────────────────────────────────────

const Settings = {
  components: { LoadingSpinner },
  setup() {
    const loading = ref(true);
    const saving = ref(false);
    const config = ref({ platforms: [], ai: { provider: '', model: '', batch_size: 10, daily_budget: 100 } });
    const actionStatus = reactive({});

    async function loadConfig() {
      loading.value = true;
      try {
        config.value = await api('/api/config');
      } catch (e) {
        console.error('Load config failed:', e);
      } finally {
        loading.value = false;
      }
    }

    async function saveConfig() {
      saving.value = true;
      try {
        await api('/api/config', { method: 'PUT', body: JSON.stringify(config.value) });
        alert('配置已保存');
      } catch (e) {
        alert('保存失败: ' + e.message);
      } finally {
        saving.value = false;
      }
    }

    async function runAction(key, endpoint, method = 'POST') {
      actionStatus[key] = 'loading';
      try {
        if (key === 'export_excel' || key === 'export_csv' || key === 'export_markdown') {
          window.open(`${API_BASE}${endpoint}`, '_blank');
          actionStatus[key] = 'success';
        } else {
          await api(endpoint, { method });
          actionStatus[key] = 'success';
        }
      } catch (e) {
        actionStatus[key] = 'error';
        console.error(`Action ${key} failed:`, e);
      }
      setTimeout(() => { actionStatus[key] = ''; }, 3000);
    }

    function statusIcon(key) {
      const s = actionStatus[key];
      if (s === 'loading') return '⏳';
      if (s === 'success') return '✅';
      if (s === 'error') return '❌';
      return '';
    }

    onMounted(loadConfig);
    return { loading, saving, config, saveConfig, runAction, statusIcon, actionStatus };
  },
  template: `
    <loading-spinner v-if="loading" />
    <div v-else>
      <!-- Platform Config -->
      <div class="card mb-4">
        <h3 class="font-semibold text-gray-700 mb-4">🌐 平台配置</h3>
        <div v-if="!(config.platforms || []).length" class="text-sm text-gray-400">暂无平台配置</div>
        <div v-for="p in (config.platforms || [])" :key="p.name" class="flex items-center gap-4 py-3 border-b border-gray-100 last:border-0">
          <span class="w-28 text-sm font-medium">{{ p.name }}</span>
          <div class="toggle-switch" :class="{ on: p.enabled }" @click="p.enabled = !p.enabled"></div>
          <label class="text-xs text-gray-500 ml-4">抓取间隔(分钟)</label>
          <input v-model.number="p.interval" type="number" min="1" class="border rounded px-2 py-1 text-sm w-20">
        </div>
      </div>

      <!-- AI Config -->
      <div class="card mb-4">
        <h3 class="font-semibold text-gray-700 mb-4">🤖 AI 配置</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm text-gray-600 mb-1">Provider</label>
            <select v-model="config.ai.provider" class="w-full border rounded-lg px-3 py-2 text-sm">
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="deepseek">DeepSeek</option>
              <option value="local">本地模型</option>
            </select>
          </div>
          <div>
            <label class="block text-sm text-gray-600 mb-1">模型名称</label>
            <input v-model="config.ai.model" class="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. gpt-4o">
          </div>
          <div>
            <label class="block text-sm text-gray-600 mb-1">批量大小</label>
            <input v-model.number="config.ai.batch_size" type="number" min="1" class="w-full border rounded-lg px-3 py-2 text-sm">
          </div>
          <div>
            <label class="block text-sm text-gray-600 mb-1">每日预算</label>
            <input v-model.number="config.ai.daily_budget" type="number" min="0" class="w-full border rounded-lg px-3 py-2 text-sm">
          </div>
        </div>
      </div>

      <!-- Save Config -->
      <div class="card mb-4">
        <button @click="saveConfig" :disabled="saving" class="action-btn bg-blue-500 text-white px-6 py-2">
          <span v-if="saving" class="spinner spinner-sm"></span>{{ saving ? '保存中...' : '💾 保存配置' }}
        </button>
      </div>

      <!-- Actions -->
      <div class="card">
        <h3 class="font-semibold text-gray-700 mb-4">⚡ 操作</h3>
        <div class="flex flex-wrap gap-3">
          <button v-for="a in [
            { key: 'crawl', label: '🕷️ 手动抓取', endpoint: '/api/crawl/trigger' },
            { key: 'analyze', label: '🧠 手动分析', endpoint: '/api/analyze/trigger' },
            { key: 'export_excel', label: '📊 导出Excel', endpoint: '/api/export/excel' },
            { key: 'export_csv', label: '📄 导出CSV', endpoint: '/api/export/csv' },
            { key: 'export_markdown', label: '📝 导出Markdown', endpoint: '/api/export/markdown' },
          ]" :key="a.key" @click="runAction(a.key, a.endpoint)"
             :disabled="actionStatus[a.key] === 'loading'"
             class="action-btn bg-gray-100 text-gray-700 hover:bg-gray-200 px-4 py-2">
            {{ a.label }} {{ statusIcon(a.key) }}
          </button>
        </div>
      </div>
    </div>`,
};

// ─── App ─────────────────────────────────────────────────

const app = createApp({
  components: { Dashboard, Demands, Articles, Trends, TagCloud, Settings, Modal, LoadingSpinner },
  setup() {
    const currentPage = ref('Dashboard');
    const globalSearch = ref('');
    const showModal = ref(false);
    const modalTitle = ref('');
    const modalContent = ref(null);
    const modalProps = ref({});

    const navItems = [
      { key: 'Dashboard', label: '仪表盘', icon: '📊' },
      { key: 'Demands', label: '需求库', icon: '📋' },
      { key: 'Articles', label: '文章库', icon: '📰' },
      { key: 'Trends', label: '趋势分析', icon: '📈' },
      { key: 'TagCloud', label: '标签云', icon: '🏷️' },
      { key: 'Settings', label: '设置', icon: '⚙️' },
    ];

    const currentPageLabel = computed(() => {
      const item = navItems.find(n => n.key === currentPage.value);
      return item ? item.label : '';
    });

    function handleGlobalSearch() {
      if (globalSearch.value.trim()) {
        currentPage.value = 'Demands';
      }
    }

    return { currentPage, globalSearch, showModal, modalTitle, modalContent, modalProps, navItems, currentPageLabel, handleGlobalSearch };
  },
});

app.mount('#app');
