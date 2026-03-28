<template>
  <div>
    <!-- ページタイトルと操作ボタン -->
    <div class="d-flex align-center justify-space-between mb-4">
      <div class="d-flex align-center">
        <v-btn
          icon="mdi-arrow-left"
          variant="text"
          :to="{ name: 'UserList' }"
          class="mr-2"
        />
        <h1 class="text-h5 font-weight-bold">ユーザー詳細</h1>
      </div>
      <v-btn
        color="primary"
        prepend-icon="mdi-pencil"
        :to="{ name: 'UserEdit', params: { id: props.id } }"
      >
        編集
      </v-btn>
    </div>

    <!-- ローディング表示 -->
    <div v-if="isLoading" class="d-flex justify-center py-8">
      <v-progress-circular indeterminate color="primary" size="48" />
    </div>

    <!-- エラー表示 -->
    <v-alert v-if="errorMessage" type="error" variant="tonal" class="mb-4" closable @click:close="errorMessage = ''">
      {{ errorMessage }}
    </v-alert>

    <template v-if="!isLoading && user">
      <!-- 基本情報 -->
      <v-card class="mb-4">
        <v-card-title>基本情報</v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="12" md="6">
              <v-list density="compact">
                <v-list-item title="ユーザー名" :subtitle="user.username || '-'" />
                <v-list-item title="ロール">
                  <template #subtitle>
                    <v-chip :color="user.role === 'admin' ? 'primary' : 'default'" size="small" label>
                      {{ user.role === 'admin' ? '管理者' : 'ユーザー' }}
                    </v-chip>
                  </template>
                </v-list-item>
              </v-list>
            </v-col>
            <v-col cols="12" md="6">
              <v-list density="compact">
                <v-list-item title="ステータス">
                  <template #subtitle>
                    <v-chip :color="user.is_active ? 'success' : 'error'" size="small" label>
                      {{ user.is_active ? 'アクティブ' : '停止中' }}
                    </v-chip>
                  </template>
                </v-list-item>
                <v-list-item title="作成日時" :subtitle="formatDate(user.created_at)" />
                <v-list-item title="更新日時" :subtitle="formatDate(user.updated_at)" />
              </v-list>
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>

      <!-- LLM設定 -->
      <v-card class="mb-4">
        <v-card-title>LLM設定</v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="12" md="6">
              <v-list density="compact">
                <v-list-item title="プロバイダー" :subtitle="user.llm_provider || '-'" />
                <v-list-item title="モデル" :subtitle="user.model_name || '-'" />
                <v-list-item title="APIキー" :subtitle="user.api_key ? '●●●●●●●●' : '未設定'" />
              </v-list>
            </v-col>
            <v-col cols="12" md="6">
              <v-list density="compact">
                <v-list-item title="Temperature" :subtitle="user.temperature?.toString() || '-'" />
                <v-list-item title="Max Tokens" :subtitle="user.max_tokens?.toString() || '-'" />
              </v-list>
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>

      <!-- コンテキスト圧縮設定 -->
      <v-card class="mb-4">
        <v-card-title>コンテキスト圧縮設定</v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="12" md="6">
              <v-list density="compact">
                <v-list-item title="圧縮機能">
                  <template #subtitle>
                    <v-chip
                      :color="user.context_compression_enabled ? 'success' : 'default'"
                      size="small"
                      label
                    >
                      {{ user.context_compression_enabled ? '有効' : '無効' }}
                    </v-chip>
                  </template>
                </v-list-item>
                <v-list-item title="トークン閾値" :subtitle="user.token_threshold?.toString() || 'モデル推奨値'" />
                <v-list-item title="保持する最近のメッセージ数" :subtitle="user.keep_recent_messages?.toString() || '-'" />
              </v-list>
            </v-col>
            <v-col cols="12" md="6">
              <v-list density="compact">
                <v-list-item title="最小圧縮対象メッセージ数" :subtitle="user.min_to_compress?.toString() || '-'" />
                <v-list-item title="最小圧縮率" :subtitle="user.min_compression_ratio?.toString() || '-'" />
              </v-list>
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>

      <!-- ワークフロー設定 -->
      <v-card class="mb-4">
        <v-card-title>ワークフロー設定</v-card-title>
        <v-card-text>
          <v-list density="compact">
            <v-list-item
              title="選択中のワークフロー"
              :subtitle="workflowSetting?.workflow_definition_name || workflowSetting?.workflow_definition_id?.toString() || 'デフォルト'"
            />
          </v-list>
        </v-card-text>
      </v-card>

      <!-- トークン使用量（今月） -->
      <v-card>
        <v-card-title>トークン使用量（今月）</v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="12" md="4">
              <v-card variant="tonal" color="primary">
                <v-card-text class="text-center">
                  <div class="text-h5">{{ formatTokens(tokenUsage.total_tokens) }}</div>
                  <div class="text-caption">合計トークン数</div>
                </v-card-text>
              </v-card>
            </v-col>
            <v-col cols="12" md="4">
              <v-card variant="tonal" color="info">
                <v-card-text class="text-center">
                  <div class="text-h5">{{ formatTokens(tokenUsage.prompt_tokens) }}</div>
                  <div class="text-caption">プロンプトトークン数</div>
                </v-card-text>
              </v-card>
            </v-col>
            <v-col cols="12" md="4">
              <v-card variant="tonal" color="success">
                <v-card-text class="text-center">
                  <div class="text-h5">{{ formatTokens(tokenUsage.completion_tokens) }}</div>
                  <div class="text-caption">完了トークン数</div>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getUserConfig, getUserWorkflowSetting } from '../api/users.js'
import { getTokenUsageStats } from '../api/statistics.js'

const props = defineProps({
  id: { type: String, required: true },
})

const isLoading = ref(true)
const errorMessage = ref('')
const user = ref(null)
const workflowSetting = ref(null)
const tokenUsage = ref({})

/**
 * 日時を表示用にフォーマットする
 */
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('ja-JP')
}

/**
 * トークン数を読みやすい形式にフォーマットする
 */
const formatTokens = (tokens) => {
  if (tokens == null) return '-'
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`
  return String(tokens)
}

/**
 * ユーザー詳細データを取得する
 */
const fetchData = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    // ユーザー設定取得（IDをメールアドレスとして扱う）
    const userRes = await getUserConfig(props.id)
    user.value = userRes.data

    // ワークフロー設定とトークン使用量を並列取得
    const [workflowRes, tokenRes] = await Promise.allSettled([
      getUserWorkflowSetting(props.id),
      getTokenUsageStats({ username: user.value.username, days: 30 }),
    ])

    if (workflowRes.status === 'fulfilled') {
      workflowSetting.value = workflowRes.value.data
    }
    if (tokenRes.status === 'fulfilled') {
      const userStats = tokenRes.value.data.users?.[0] || {}
      tokenUsage.value = userStats
    }
  } catch (error) {
    errorMessage.value = 'ユーザー情報の取得に失敗しました'
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchData)
</script>
