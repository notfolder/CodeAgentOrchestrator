<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-bold">ユーザー設定</h1>
    </div>

    <!-- ローディング表示 -->
    <div v-if="isLoading" class="d-flex justify-center py-8">
      <v-progress-circular indeterminate color="primary" size="48" />
    </div>

    <!-- エラー表示 -->
    <v-alert v-if="errorMessage" type="error" variant="tonal" class="mb-4" closable @click:close="errorMessage = ''">
      {{ errorMessage }}
    </v-alert>

    <v-form v-if="!isLoading" ref="formRef" v-model="isFormValid" @submit.prevent="handleSave">
      <!-- 基本情報 -->
      <v-card class="mb-4">
        <v-card-title>基本情報</v-card-title>
        <v-card-text>
          <v-row>
            <!-- メールアドレスは読み取り専用 -->
            <v-col cols="12" md="6">
              <v-text-field
                v-model="form.username"
                label="ユーザー名（GitLab）"
                variant="outlined"
                readonly
                disabled
              />
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
              <v-select
                v-model="form.llm_provider"
                label="プロバイダー"
                :items="llmProviderOptions"
                variant="outlined"
              />
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="form.model_name"
                label="モデル名"
                variant="outlined"
              />
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="form.api_key"
                label="APIキー（変更する場合のみ入力）"
                :type="showApiKey ? 'text' : 'password'"
                :append-inner-icon="showApiKey ? 'mdi-eye-off' : 'mdi-eye'"
                variant="outlined"
                @click:append-inner="showApiKey = !showApiKey"
              />
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field
                v-model.number="form.temperature"
                label="Temperature"
                type="number"
                variant="outlined"
                step="0.1"
                min="0"
                max="2"
              />
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field
                v-model.number="form.max_tokens"
                label="Max Tokens"
                type="number"
                variant="outlined"
                min="1"
              />
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>

      <!-- コンテキスト圧縮設定 -->
      <v-card class="mb-4">
        <v-card-title>コンテキスト圧縮設定</v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="12">
              <v-switch
                v-model="form.context_compression_enabled"
                label="コンテキスト圧縮を有効化"
                color="primary"
                inset
              />
            </v-col>
            <template v-if="form.context_compression_enabled">
              <v-col cols="12" md="3">
                <v-text-field
                  v-model.number="form.token_threshold"
                  label="トークン閾値"
                  type="number"
                  variant="outlined"
                  hint="1,000〜150,000 (空欄でモデル推奨値)"
                  persistent-hint
                />
              </v-col>
              <v-col cols="12" md="3">
                <v-text-field
                  v-model.number="form.keep_recent_messages"
                  label="保持する最近のメッセージ数"
                  type="number"
                  variant="outlined"
                  min="1"
                  max="50"
                />
              </v-col>
              <v-col cols="12" md="3">
                <v-text-field
                  v-model.number="form.min_to_compress"
                  label="最小圧縮対象メッセージ数"
                  type="number"
                  variant="outlined"
                  min="1"
                  max="20"
                />
              </v-col>
              <v-col cols="12" md="3">
                <v-text-field
                  v-model.number="form.min_compression_ratio"
                  label="最小圧縮率"
                  type="number"
                  variant="outlined"
                  step="0.05"
                  min="0.5"
                  max="0.95"
                />
              </v-col>
            </template>
          </v-row>
        </v-card-text>
      </v-card>

      <!-- 今月のトークン使用量 -->
      <v-card class="mb-4">
        <v-card-title>今月のトークン使用量</v-card-title>
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

      <!-- パスワード変更リンク -->
      <v-card class="mb-4">
        <v-card-title>セキュリティ</v-card-title>
        <v-card-text>
          <v-btn
            variant="outlined"
            color="warning"
            prepend-icon="mdi-lock-reset"
            :to="{ name: 'PasswordChange' }"
          >
            パスワードを変更する
          </v-btn>
        </v-card-text>
      </v-card>

      <!-- 操作ボタン -->
      <div class="d-flex justify-end gap-3">
        <v-btn
          variant="outlined"
          :to="{ name: 'Dashboard' }"
          :disabled="isSubmitting"
        >
          キャンセル
        </v-btn>
        <v-btn
          type="submit"
          color="primary"
          :loading="isSubmitting"
          :disabled="!isFormValid || isSubmitting"
        >
          保存
        </v-btn>
      </div>
    </v-form>

    <!-- 保存成功スナックバー -->
    <v-snackbar v-model="successSnackbar" color="success" timeout="3000">
      設定を更新しました
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getUserConfig, updateUser } from '../api/users.js'
import { getTokenUsageStats } from '../api/statistics.js'
import { useAuthStore } from '../stores/auth.js'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref(null)
const isFormValid = ref(false)
const isLoading = ref(true)
const isSubmitting = ref(false)
const errorMessage = ref('')
const successSnackbar = ref(false)
const showApiKey = ref(false)
const tokenUsage = ref({})

// フォームデータ
const form = ref({
  username: '',
  llm_provider: '',
  model_name: '',
  api_key: '',
  temperature: 0.7,
  max_tokens: 4096,
  context_compression_enabled: false,
  token_threshold: null,
  keep_recent_messages: 10,
  min_to_compress: 5,
  min_compression_ratio: 0.7,
})

const llmProviderOptions = ['openai', 'anthropic', 'azure_openai', 'google']

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
 * ユーザー設定とトークン使用量を取得する
 */
const fetchData = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const username = authStore.username
    const [userRes, tokenRes] = await Promise.allSettled([
      getUserConfig(username),
      getTokenUsageStats({ username, days: 30 }),
    ])

    if (userRes.status === 'fulfilled') {
      const user = userRes.value.data
      Object.keys(form.value).forEach((key) => {
        if (user[key] !== undefined) form.value[key] = user[key]
      })
      // APIキーは表示しない
      form.value.api_key = ''
    } else {
      errorMessage.value = 'ユーザー設定の取得に失敗しました'
    }

    if (tokenRes.status === 'fulfilled') {
      tokenUsage.value = tokenRes.value.data.users?.[0] || {}
    }
  } finally {
    isLoading.value = false
  }
}

/**
 * 設定を保存する
 */
const handleSave = async () => {
  const { valid } = await formRef.value.validate()
  if (!valid) return

  isSubmitting.value = true
  errorMessage.value = ''

  try {
    const updateData = { ...form.value }
    // APIキーが空の場合は送信データから除外
    if (!updateData.api_key) delete updateData.api_key

    await updateUser(form.value.username, updateData)
    successSnackbar.value = true
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '設定の更新に失敗しました'
  } finally {
    isSubmitting.value = false
  }
}

onMounted(fetchData)
</script>
