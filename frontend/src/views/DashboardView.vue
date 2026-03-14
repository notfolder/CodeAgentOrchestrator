<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-bold">ダッシュボード</h1>
    </div>

    <!-- ローディング表示 -->
    <div v-if="isLoading" class="d-flex justify-center py-8">
      <v-progress-circular indeterminate color="primary" size="48" />
    </div>

    <!-- エラー表示 -->
    <v-alert v-if="errorMessage" type="error" variant="tonal" class="mb-4" closable @click:close="errorMessage = ''">
      {{ errorMessage }}
    </v-alert>

    <template v-if="!isLoading">
      <!-- 統計カード群 -->
      <v-row class="mb-4">
        <!-- 登録ユーザー数 -->
        <v-col cols="12" md="4">
          <v-card>
            <v-card-text class="text-center py-6">
              <v-icon icon="mdi-account-group" size="40" color="primary" class="mb-2" />
              <div class="text-h4 font-weight-bold">{{ stats.total_users ?? '-' }}</div>
              <div class="text-body-1 text-medium-emphasis">登録ユーザー数</div>
            </v-card-text>
          </v-card>
        </v-col>
        <!-- 実行中タスク数 -->
        <v-col cols="12" md="4">
          <v-card>
            <v-card-text class="text-center py-6">
              <v-icon icon="mdi-play-circle" size="40" color="success" class="mb-2" />
              <div class="text-h4 font-weight-bold">{{ stats.active_tasks ?? '-' }}</div>
              <div class="text-body-1 text-medium-emphasis">実行中タスク数</div>
            </v-card-text>
          </v-card>
        </v-col>
        <!-- 今月のトークン使用量 -->
        <v-col cols="12" md="4">
          <v-card>
            <v-card-text class="text-center py-6">
              <v-icon icon="mdi-chart-line" size="40" color="warning" class="mb-2" />
              <div class="text-h4 font-weight-bold">{{ formatTokens(stats.monthly_tokens) }}</div>
              <div class="text-body-1 text-medium-emphasis">今月のトークン使用量</div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row>
        <!-- 最近のタスク一覧（最新5件） -->
        <v-col cols="12" md="7">
          <v-card>
            <v-card-title class="d-flex align-center">
              <v-icon icon="mdi-history" class="mr-2" />
              最近の活動
            </v-card-title>
            <v-card-text>
              <v-table v-if="recentTasks.length > 0" density="compact">
                <thead>
                  <tr>
                    <th>日時</th>
                    <th>ユーザー</th>
                    <th>タスク種別</th>
                    <th>ステータス</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="task in recentTasks" :key="task.uuid">
                    <td>{{ formatDate(task.started_at) }}</td>
                    <td>{{ task.user_email }}</td>
                    <td>{{ task.task_type }}</td>
                    <td>
                      <v-chip
                        :color="getStatusColor(task.status)"
                        size="small"
                        label
                      >
                        {{ getStatusLabel(task.status) }}
                      </v-chip>
                    </td>
                  </tr>
                </tbody>
              </v-table>
              <div v-else class="text-center text-medium-emphasis py-4">
                最近のタスクはありません
              </div>
            </v-card-text>
          </v-card>
        </v-col>

        <!-- トークン使用量推移（直近7日間） -->
        <v-col cols="12" md="5">
          <v-card>
            <v-card-title class="d-flex align-center">
              <v-icon icon="mdi-chart-bar" class="mr-2" />
              トークン使用量推移（直近7日間）
            </v-card-title>
            <v-card-text>
              <div v-if="dailyTokens.length > 0">
                <!-- 簡易バーチャート -->
                <div class="d-flex align-end justify-space-around" style="height: 120px;">
                  <div
                    v-for="item in dailyTokens"
                    :key="item.date"
                    class="d-flex flex-column align-center"
                    style="flex: 1;"
                  >
                    <div
                      class="bg-primary rounded-t"
                      :style="{
                        width: '80%',
                        height: getBarHeight(item.total_tokens) + 'px',
                        minHeight: item.total_tokens > 0 ? '4px' : '0',
                      }"
                    />
                    <div class="text-caption mt-1">{{ formatShortDate(item.date) }}</div>
                  </div>
                </div>
                <!-- 最大値表示 -->
                <div class="text-caption text-medium-emphasis text-right mt-2">
                  最大: {{ formatTokens(maxDailyTokens) }}
                </div>
              </div>
              <div v-else class="text-center text-medium-emphasis py-4">
                データがありません
              </div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getDashboardStats, getTaskHistory, getTokenUsageStats } from '../api/statistics.js'

const isLoading = ref(true)
const errorMessage = ref('')
const stats = ref({})
const recentTasks = ref([])
const dailyTokens = ref([])

// 直近7日間のトークン最大値（バーチャートの高さ計算用）
const maxDailyTokens = computed(() => {
  if (dailyTokens.value.length === 0) return 0
  return Math.max(...dailyTokens.value.map((d) => d.total_tokens || 0))
})

/**
 * バーの高さを計算する（最大100px）
 * @param {number} tokens - トークン数
 * @returns {number} 高さ（px）
 */
const getBarHeight = (tokens) => {
  if (maxDailyTokens.value === 0) return 0
  return Math.round((tokens / maxDailyTokens.value) * 100)
}

/**
 * トークン数を読みやすい形式にフォーマットする
 * @param {number|null} tokens
 * @returns {string}
 */
const formatTokens = (tokens) => {
  if (tokens == null) return '-'
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`
  return String(tokens)
}

/**
 * 日時を表示用にフォーマットする
 * @param {string} dateStr - ISO8601形式の日時文字列
 * @returns {string}
 */
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return d.toLocaleString('ja-JP', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/**
 * 曜日の短縮表示
 * @param {string} dateStr
 * @returns {string}
 */
const formatShortDate = (dateStr) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const days = ['日', '月', '火', '水', '木', '金', '土']
  return days[d.getDay()]
}

/**
 * タスクステータスに対応する色を返す
 * @param {string} status
 * @returns {string}
 */
const getStatusColor = (status) => {
  const map = {
    completed: 'success',
    running: 'info',
    failed: 'error',
    pending: 'warning',
  }
  return map[status] || 'default'
}

/**
 * タスクステータスの日本語ラベルを返す
 * @param {string} status
 * @returns {string}
 */
const getStatusLabel = (status) => {
  const map = {
    completed: '完了',
    running: '実行中',
    failed: '失敗',
    pending: '待機中',
  }
  return map[status] || status
}

/**
 * ダッシュボードデータを取得する
 */
const fetchData = async () => {
  isLoading.value = true
  errorMessage.value = ''

  try {
    // 統計・タスク・トークン推移を並列取得
    const [statsRes, tasksRes, tokenRes] = await Promise.allSettled([
      getDashboardStats(),
      getTaskHistory({ per_page: 5, page: 1 }),
      getTokenUsageStats({ days: 7 }),
    ])

    if (statsRes.status === 'fulfilled') {
      stats.value = statsRes.value.data
    }
    if (tasksRes.status === 'fulfilled') {
      recentTasks.value = tasksRes.value.data.tasks || tasksRes.value.data || []
    }
    if (tokenRes.status === 'fulfilled') {
      dailyTokens.value = tokenRes.value.data.daily || []
    }
  } catch (error) {
    errorMessage.value = 'データの取得に失敗しました'
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchData)
</script>
