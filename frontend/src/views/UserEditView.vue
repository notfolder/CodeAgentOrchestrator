<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center mb-4">
      <v-btn
        icon="mdi-arrow-left"
        variant="text"
        :to="{ name: 'UserDetail', params: { id: props.id } }"
        class="mr-2"
      />
      <h1 class="text-h5 font-weight-bold">ユーザー編集</h1>
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
            <v-col cols="12" md="6">
              <!-- ユーザー名は読み取り専用 -->
              <v-text-field
                v-model="form.username"
                label="ユーザー名"
                variant="outlined"
                readonly
                disabled
              />
            </v-col>
            <!-- 管理者のみロール変更可能 -->
            <v-col v-if="authStore.isAdmin" cols="12" md="3">
              <v-select
                v-model="form.role"
                label="ロール"
                :items="roleOptions"
                item-title="label"
                item-value="value"
                variant="outlined"
              />
            </v-col>
            <v-col cols="12" md="3">
              <v-switch
                v-model="form.is_active"
                label="アクティブ"
                color="primary"
                inset
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
                :rules="temperatureRules"
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
                  :rules="keepRecentRules"
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
                  :rules="minCompressRules"
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
                  :rules="compressionRatioRules"
                  step="0.05"
                  min="0.5"
                  max="0.95"
                />
              </v-col>
            </template>
          </v-row>
        </v-card-text>
      </v-card>

      <!-- ワークフロー設定 -->
      <v-card class="mb-4">
        <v-card-title>ワークフロー設定</v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="12" md="6">
              <v-select
                v-model="form.workflow_definition_id"
                label="ワークフロー定義"
                :items="workflowOptions"
                item-title="label"
                item-value="value"
                variant="outlined"
                hint="未選択の場合はシステムデフォルト"
                persistent-hint
              />
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>

      <!-- 操作ボタン -->
      <div class="d-flex justify-space-between">
        <!-- 管理者のみ他ユーザーのパスワード代理変更ボタンを表示 -->
        <v-btn
          v-if="authStore.isAdmin"
          variant="outlined"
          color="warning"
          prepend-icon="mdi-lock-reset"
          :to="{ name: 'PasswordChange', query: { username: originalUsername } }"
        >
          パスワード変更（管理者代理）
        </v-btn>
        <div class="d-flex gap-3">
          <v-btn
            variant="outlined"
            :to="{ name: 'UserDetail', params: { id: props.id } }"
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
      </div>
    </v-form>

    <!-- 保存成功スナックバー -->
    <v-snackbar v-model="successSnackbar" color="success" timeout="3000">
      ユーザー情報を更新しました
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getUserConfig, updateUser, updateUserWorkflowSetting } from '../api/users.js'
import { getWorkflowDefinitions } from '../api/workflows.js'
import { useAuthStore } from '../stores/auth.js'

const props = defineProps({
  id: { type: String, required: true },
})

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref(null)
const isFormValid = ref(false)
const isLoading = ref(true)
const isSubmitting = ref(false)
const errorMessage = ref('')
const successSnackbar = ref(false)
const showApiKey = ref(false)
const workflowOptions = ref([{ label: 'システムデフォルト', value: null }])
const originalUsername = ref('')

// フォームデータ
const form = ref({
  username: '',
  role: 'user',
  is_active: true,
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
  workflow_definition_id: null,
})

// バリデーションルール
const temperatureRules = [
  (v) => v == null || (v >= 0 && v <= 2) || 'Temperatureは0〜2の範囲で入力してください',
]
const keepRecentRules = [
  (v) => v == null || (v >= 1 && v <= 50) || '1〜50の範囲で入力してください',
]
const minCompressRules = [
  (v) => v == null || (v >= 1 && v <= 20) || '1〜20の範囲で入力してください',
]
const compressionRatioRules = [
  (v) => v == null || (v >= 0.5 && v <= 0.95) || '0.5〜0.95の範囲で入力してください',
]

const roleOptions = [
  { label: '管理者', value: 'admin' },
  { label: 'ユーザー', value: 'user' },
]

const llmProviderOptions = ['openai', 'anthropic', 'azure_openai', 'google']

/**
 * ユーザー情報とワークフロー定義一覧を取得する
 */
const fetchData = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const [userRes, workflowRes] = await Promise.allSettled([
      getUserConfig(props.id),
      getWorkflowDefinitions(),
    ])

    if (userRes.status === 'fulfilled') {
      const user = userRes.value.data
      originalUsername.value = user.username
      // フォームに既存値を反映
      Object.keys(form.value).forEach((key) => {
        if (user[key] !== undefined) form.value[key] = user[key]
      })
      // APIキーは表示しない（変更時のみ入力させる）
      form.value.api_key = ''
    } else {
      errorMessage.value = 'ユーザー情報の取得に失敗しました'
    }

    if (workflowRes.status === 'fulfilled') {
      const options = (workflowRes.value.data || []).map((w) => ({
        label: `${w.is_preset ? '🔒 ' : ''}${w.name}`,
        value: w.id,
      }))
      workflowOptions.value = [{ label: 'システムデフォルト', value: null }, ...options]
    }
  } finally {
    isLoading.value = false
  }
}

/**
 * ユーザー情報を保存する
 */
const handleSave = async () => {
  const { valid } = await formRef.value.validate()
  if (!valid) return

  isSubmitting.value = true
  errorMessage.value = ''

  try {
    // APIキーが空の場合は送信データから除外する
    const updateData = { ...form.value }
    if (!updateData.api_key) {
      delete updateData.api_key
    }

    // ユーザー情報の更新
    await updateUser(originalUsername.value, updateData)

    // ワークフロー設定の更新
    if (form.value.workflow_definition_id !== null) {
      await updateUserWorkflowSetting(props.id, {
        workflow_definition_id: form.value.workflow_definition_id,
      })
    }

    successSnackbar.value = true
    setTimeout(() => router.push({ name: 'UserDetail', params: { id: props.id } }), 1000)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || 'ユーザー情報の更新に失敗しました'
  } finally {
    isSubmitting.value = false
  }
}

onMounted(fetchData)
</script>
