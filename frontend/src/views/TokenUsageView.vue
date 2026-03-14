<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center justify-space-between mb-4">
      <h1 class="text-h5 font-weight-bold">トークン使用量統計</h1>
      <!-- CSVエクスポートボタン -->
      <v-btn
        color="secondary"
        prepend-icon="mdi-download"
        :disabled="isLoading || tokenStats.length === 0"
        @click="exportCsv"
      >
        CSVエクスポート
      </v-btn>
    </div>

    <!-- フィルタ -->
    <v-card class="mb-4">
      <v-card-text>
        <v-row>
          <v-col cols="12" md="5">
            <v-select
              v-model="emailFilter"
              label="ユーザーフィルタ"
              :items="userEmailOptions"
              item-title="label"
              item-value="value"
              variant="outlined"
              density="compact"
              hide-details
            />
          </v-col>
          <v-col cols="12" md="4">
            <v-select
              v-model="daysFilter"
              label="集計期間"
              :items="daysOptions"
              item-title="label"
              item-value="value"
              variant="outlined"
              density="compact"
              hide-details
            />
          </v-col>
          <v-col cols="auto">
            <v-btn
              color="primary"
              prepend-icon="mdi-filter"
              :loading="isLoading"
              @click="fetchStats"
            >
              絞り込み
            </v-btn>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <!-- エラー表示 -->
    <v-alert v-if="errorMessage" type="error" variant="tonal" class="mb-4" closable @click:close="errorMessage = ''">
      {{ errorMessage }}
    </v-alert>

    <!-- トークン使用量テーブル -->
    <v-card>
      <v-data-table
        :headers="headers"
        :items="tokenStats"
        :loading="isLoading"
        loading-text="読み込み中..."
        no-data-text="データがありません"
        :items-per-page="20"
      >
        <!-- 合計トークン列 -->
        <template #item.total_tokens="{ item }">
          {{ formatNumber(item.total_tokens) }}
        </template>
        <!-- プロンプトトークン列 -->
        <template #item.prompt_tokens="{ item }">
          {{ formatNumber(item.prompt_tokens) }}
        </template>
        <!-- 完了トークン列 -->
        <template #item.completion_tokens="{ item }">
          {{ formatNumber(item.completion_tokens) }}
        </template>
      </v-data-table>
    </v-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getTokenUsageStats } from '../api/statistics.js'
import { getUsers } from '../api/users.js'

const isLoading = ref(true)
const errorMessage = ref('')
const tokenStats = ref([])
const emailFilter = ref('')
const daysFilter = ref(30)
const userEmailOptions = ref([{ label: '全ユーザー', value: '' }])

// テーブルヘッダー
const headers = [
  { title: 'ユーザーメール', key: 'email' },
  { title: '合計トークン数', key: 'total_tokens', align: 'end' },
  { title: 'プロンプトトークン数', key: 'prompt_tokens', align: 'end' },
  { title: '完了トークン数', key: 'completion_tokens', align: 'end' },
]

// 集計期間の選択肢
const daysOptions = [
  { label: '直近7日間', value: 7 },
  { label: '直近30日間', value: 30 },
  { label: '直近90日間', value: 90 },
]

/**
 * 数値を読みやすい形式にフォーマットする
 * @param {number} num
 * @returns {string}
 */
const formatNumber = (num) => {
  if (num == null) return '-'
  return num.toLocaleString('ja-JP')
}

/**
 * CSVエクスポート処理
 */
const exportCsv = () => {
  const header = 'ユーザーメール,合計トークン数,プロンプトトークン数,完了トークン数'
  const rows = tokenStats.value.map(
    (s) => `${s.email},${s.total_tokens},${s.prompt_tokens},${s.completion_tokens}`
  )
  const csvContent = [header, ...rows].join('\n')
  const blob = new Blob(['\uFEFF' + csvContent], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `token_usage_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

/**
 * トークン使用量統計を取得する
 */
const fetchStats = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const params = { days: daysFilter.value }
    if (emailFilter.value) params.email = emailFilter.value

    const res = await getTokenUsageStats(params)
    tokenStats.value = res.data.users || res.data || []
  } catch {
    errorMessage.value = 'トークン使用量統計の取得に失敗しました'
  } finally {
    isLoading.value = false
  }
}

/**
 * ユーザー一覧を取得してフィルタ用選択肢を生成する
 */
const fetchUserEmails = async () => {
  try {
    const res = await getUsers()
    const emails = (res.data || []).map((u) => ({ label: u.email, value: u.email }))
    userEmailOptions.value = [{ label: '全ユーザー', value: '' }, ...emails]
  } catch {
    // ユーザー一覧取得失敗は非致命的
  }
}

onMounted(async () => {
  await fetchUserEmails()
  await fetchStats()
})
</script>
