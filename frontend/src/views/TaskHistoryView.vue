<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-bold">タスク実行履歴</h1>
    </div>

    <!-- フィルタ -->
    <v-card class="mb-4">
      <v-card-text>
        <v-row>
          <v-col cols="12" md="4">
            <v-text-field
              v-model="filters.search"
              label="検索（タスクID・ユーザー）"
              prepend-inner-icon="mdi-magnify"
              variant="outlined"
              density="compact"
              clearable
              hide-details
            />
          </v-col>
          <v-col cols="12" md="2">
            <v-select
              v-model="filters.status"
              label="ステータス"
              :items="statusOptions"
              item-title="label"
              item-value="value"
              variant="outlined"
              density="compact"
              hide-details
            />
          </v-col>
          <v-col cols="12" md="3">
            <v-select
              v-model="filters.email"
              label="ユーザー"
              :items="userEmailOptions"
              item-title="label"
              item-value="value"
              variant="outlined"
              density="compact"
              hide-details
            />
          </v-col>
          <v-col cols="12" md="2">
            <v-select
              v-model="filters.days"
              label="期間"
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
              @click="fetchTasks"
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

    <!-- タスク一覧テーブル -->
    <v-card>
      <v-data-table
        :headers="headers"
        :items="filteredTasks"
        :loading="isLoading"
        loading-text="読み込み中..."
        no-data-text="タスクが見つかりません"
        :items-per-page="20"
      >
        <!-- ステータス列 -->
        <template #item.status="{ item }">
          <v-chip
            :color="getStatusColor(item.status)"
            size="small"
            label
          >
            {{ getStatusLabel(item.status) }}
          </v-chip>
        </template>

        <!-- 開始日時列 -->
        <template #item.started_at="{ item }">
          {{ formatDate(item.started_at) }}
        </template>

        <!-- 完了日時列 -->
        <template #item.completed_at="{ item }">
          {{ formatDate(item.completed_at) }}
        </template>

        <!-- トークン数列 -->
        <template #item.total_tokens="{ item }">
          {{ item.total_tokens?.toLocaleString('ja-JP') ?? '-' }}
        </template>
      </v-data-table>
    </v-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getTaskHistory } from '../api/statistics.js'
import { getUsers } from '../api/users.js'

const isLoading = ref(true)
const errorMessage = ref('')
const tasks = ref([])
const userEmailOptions = ref([{ label: '全ユーザー', value: '' }])

// フィルタ状態
const filters = ref({
  search: '',
  status: '',
  email: '',
  days: '',
})

// テーブルヘッダー
const headers = [
  { title: 'タスクID', key: 'uuid', width: '200px' },
  { title: 'ユーザー', key: 'user_email' },
  { title: 'タスク種別', key: 'task_type', width: '140px' },
  { title: 'ステータス', key: 'status', width: '110px' },
  { title: '開始日時', key: 'started_at', width: '160px' },
  { title: '完了日時', key: 'completed_at', width: '160px' },
  { title: 'トークン数', key: 'total_tokens', align: 'end', width: '120px' },
]

// ステータスフィルタの選択肢
const statusOptions = [
  { label: 'すべて', value: '' },
  { label: '完了', value: 'completed' },
  { label: '実行中', value: 'running' },
  { label: '失敗', value: 'failed' },
  { label: '待機中', value: 'pending' },
]

// 期間フィルタの選択肢
const daysOptions = [
  { label: 'すべて', value: '' },
  { label: '直近7日間', value: 7 },
  { label: '直近30日間', value: 30 },
  { label: '直近90日間', value: 90 },
]

// クライアントサイドフィルタリング適用後のタスク一覧
const filteredTasks = computed(() => {
  let result = tasks.value

  if (filters.value.search) {
    const q = filters.value.search.toLowerCase()
    result = result.filter(
      (t) =>
        t.uuid?.toLowerCase().includes(q) ||
        t.user_email?.toLowerCase().includes(q)
    )
  }

  if (filters.value.status) {
    result = result.filter((t) => t.status === filters.value.status)
  }

  if (filters.value.email) {
    result = result.filter((t) => t.user_email === filters.value.email)
  }

  return result
})

/**
 * ステータスに対応する色を返す
 */
const getStatusColor = (status) => {
  const map = { completed: 'success', running: 'info', failed: 'error', pending: 'warning' }
  return map[status] || 'default'
}

/**
 * ステータスの日本語ラベルを返す
 */
const getStatusLabel = (status) => {
  const map = { completed: '完了', running: '実行中', failed: '失敗', pending: '待機中' }
  return map[status] || status
}

/**
 * 日時を表示用にフォーマットする
 */
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('ja-JP', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * タスク一覧を取得する
 */
const fetchTasks = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const params = {}
    if (filters.value.days) {
      const now = new Date()
      const past = new Date(now.getTime() - filters.value.days * 24 * 60 * 60 * 1000)
      params.started_after = past.toISOString()
    }

    const res = await getTaskHistory(params)
    tasks.value = res.data.tasks || res.data || []
  } catch {
    errorMessage.value = 'タスク履歴の取得に失敗しました'
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
    // 非致命的
  }
}

onMounted(async () => {
  await fetchUserEmails()
  await fetchTasks()
})
</script>
