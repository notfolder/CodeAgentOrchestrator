<template>
  <div>
    <!-- ページタイトルと新規作成ボタン -->
    <div class="d-flex align-center justify-space-between mb-4">
      <h1 class="text-h5 font-weight-bold">ユーザー一覧</h1>
      <v-btn
        color="primary"
        prepend-icon="mdi-plus"
        :to="{ name: 'UserCreate' }"
      >
        新規作成
      </v-btn>
    </div>

    <!-- エラー表示 -->
    <v-alert v-if="errorMessage" type="error" variant="tonal" class="mb-4" closable @click:close="errorMessage = ''">
      {{ errorMessage }}
    </v-alert>

    <!-- 検索・フィルタ -->
    <v-card class="mb-4">
      <v-card-text>
        <v-row>
          <v-col cols="12" md="6">
            <v-text-field
              v-model="searchQuery"
              label="検索（ユーザー名）"
              prepend-inner-icon="mdi-magnify"
              variant="outlined"
              density="compact"
              clearable
              hide-details
            />
          </v-col>
          <v-col cols="12" md="3">
            <v-select
              v-model="roleFilter"
              label="ロールフィルタ"
              :items="roleOptions"
              item-title="label"
              item-value="value"
              variant="outlined"
              density="compact"
              hide-details
            />
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <!-- ユーザー一覧テーブル -->
    <v-card>
      <v-data-table
        :headers="headers"
        :items="filteredUsers"
        :loading="isLoading"
        :items-per-page="10"
        loading-text="読み込み中..."
        no-data-text="ユーザーが見つかりません"
      >
        <!-- ステータス列 -->
        <template #item.is_active="{ item }">
          <v-chip
            :color="item.is_active ? 'success' : 'error'"
            size="small"
            label
          >
            {{ item.is_active ? 'アクティブ' : '停止中' }}
          </v-chip>
        </template>

        <!-- ロール列 -->
        <template #item.role="{ item }">
          <v-chip
            :color="item.role === 'admin' ? 'primary' : 'default'"
            size="small"
            label
          >
            {{ item.role === 'admin' ? '管理者' : 'ユーザー' }}
          </v-chip>
        </template>

        <!-- 作成日時列 -->
        <template #item.created_at="{ item }">
          {{ formatDate(item.created_at) }}
        </template>

        <!-- 操作ボタン列 -->
        <template #item.actions="{ item }">
          <v-btn
            size="small"
            variant="text"
            icon="mdi-eye"
            :to="{ name: 'UserDetail', params: { id: item.username } }"
            title="詳細"
          />
          <v-btn
            size="small"
            variant="text"
            icon="mdi-pencil"
            :to="{ name: 'UserEdit', params: { id: item.username } }"
            title="編集"
          />
        </template>
      </v-data-table>
    </v-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getUsers } from '../api/users.js'

const isLoading = ref(true)
const errorMessage = ref('')
const users = ref([])
const searchQuery = ref('')
const roleFilter = ref('all')

// テーブルヘッダー定義
const headers = [
  { title: 'ID', key: 'id', width: '80px' },
  { title: 'ユーザー名', key: 'username' },
  { title: 'ロール', key: 'role', width: '120px' },
  { title: 'ステータス', key: 'is_active', width: '120px' },
  { title: '作成日時', key: 'created_at', width: '160px' },
  { title: '操作', key: 'actions', sortable: false, width: '100px', align: 'center' },
]

// ロールフィルタの選択肢
const roleOptions = [
  { label: 'すべて', value: 'all' },
  { label: '管理者', value: 'admin' },
  { label: 'ユーザー', value: 'user' },
]

// 検索・フィルタ適用後のユーザー一覧
const filteredUsers = computed(() => {
  let result = users.value

  // ロールフィルタ
  if (roleFilter.value !== 'all') {
    result = result.filter((u) => u.role === roleFilter.value)
  }

  // テキスト検索
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(
      (u) =>
        u.username?.toLowerCase().includes(q)
    )
  }

  return result
})

/**
 * 日時を表示用にフォーマットする
 * @param {string} dateStr
 * @returns {string}
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
 * ユーザー一覧を取得する
 */
const fetchUsers = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const res = await getUsers()
    users.value = res.data
  } catch (error) {
    errorMessage.value = 'ユーザー一覧の取得に失敗しました'
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchUsers)
</script>
