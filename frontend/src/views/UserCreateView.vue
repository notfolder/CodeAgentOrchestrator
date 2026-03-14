<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center mb-4">
      <v-btn
        icon="mdi-arrow-left"
        variant="text"
        :to="{ name: 'UserList' }"
        class="mr-2"
      />
      <h1 class="text-h5 font-weight-bold">ユーザー作成</h1>
    </div>

    <!-- エラー表示 -->
    <v-alert v-if="errorMessage" type="error" variant="tonal" class="mb-4" closable @click:close="errorMessage = ''">
      {{ errorMessage }}
    </v-alert>

    <v-form ref="formRef" v-model="isFormValid" @submit.prevent="handleCreate">
      <!-- 基本情報 -->
      <v-card class="mb-4">
        <v-card-title>基本情報</v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="form.email"
                label="メールアドレス *"
                type="email"
                variant="outlined"
                :rules="emailRules"
                required
              />
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="form.username"
                label="ユーザー名"
                variant="outlined"
              />
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="form.password"
                label="パスワード *"
                :type="showPassword ? 'text' : 'password'"
                :append-inner-icon="showPassword ? 'mdi-eye-off' : 'mdi-eye'"
                variant="outlined"
                :rules="passwordRules"
                required
                @click:append-inner="showPassword = !showPassword"
              />
            </v-col>
            <v-col cols="12" md="3">
              <v-select
                v-model="form.role"
                label="ロール *"
                :items="roleOptions"
                item-title="label"
                item-value="value"
                variant="outlined"
                :rules="[(v) => !!v || 'ロールを選択してください']"
                required
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
                label="APIキー"
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

      <!-- 学習機能設定 -->
      <v-card class="mb-4">
        <v-card-title>学習機能設定</v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="12">
              <v-switch
                v-model="form.learning_enabled"
                label="学習機能を有効化"
                color="primary"
                inset
              />
            </v-col>
            <template v-if="form.learning_enabled">
              <v-col cols="12" md="4">
                <v-text-field
                  v-model="form.learning_llm_model"
                  label="学習LLMモデル"
                  variant="outlined"
                />
              </v-col>
              <v-col cols="12" md="4">
                <v-text-field
                  v-model.number="form.learning_llm_temperature"
                  label="学習LLM Temperature"
                  type="number"
                  variant="outlined"
                  step="0.1"
                  min="0"
                  max="2"
                />
              </v-col>
              <v-col cols="12" md="4">
                <v-text-field
                  v-model.number="form.learning_llm_max_tokens"
                  label="学習LLM Max Tokens"
                  type="number"
                  variant="outlined"
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-switch
                  v-model="form.learning_exclude_bot_comments"
                  label="Botコメントを学習から除外"
                  color="primary"
                  inset
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-switch
                  v-model="form.learning_only_after_task_start"
                  label="タスク開始後のコメントのみ学習"
                  color="primary"
                  inset
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
      <div class="d-flex justify-end gap-3">
        <v-btn
          variant="outlined"
          :to="{ name: 'UserList' }"
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
          作成
        </v-btn>
      </div>
    </v-form>

    <!-- 作成成功スナックバー -->
    <v-snackbar v-model="successSnackbar" color="success" timeout="3000">
      ユーザーを作成しました
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { createUser } from '../api/users.js'
import { getWorkflowDefinitions } from '../api/workflows.js'

const router = useRouter()

// フォーム状態
const formRef = ref(null)
const isFormValid = ref(false)
const isSubmitting = ref(false)
const errorMessage = ref('')
const successSnackbar = ref(false)
const showPassword = ref(false)
const showApiKey = ref(false)
const workflowOptions = ref([{ label: 'システムデフォルト', value: null }])

// フォームデータ
const form = ref({
  email: '',
  username: '',
  password: '',
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
  learning_enabled: false,
  learning_llm_model: '',
  learning_llm_temperature: 0.3,
  learning_llm_max_tokens: 4096,
  learning_exclude_bot_comments: true,
  learning_only_after_task_start: true,
  workflow_definition_id: null,
})

// バリデーションルール
const emailRules = [
  (v) => !!v || 'メールアドレスを入力してください',
  (v) => /.+@.+\..+/.test(v) || '有効なメールアドレスを入力してください',
]
const passwordRules = [
  (v) => !!v || 'パスワードを入力してください',
  (v) => v.length >= 8 || 'パスワードは8文字以上で入力してください',
]
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
 * ワークフロー定義一覧を取得してプルダウン用選択肢を生成する
 */
const fetchWorkflows = async () => {
  try {
    const res = await getWorkflowDefinitions()
    const options = (res.data || []).map((w) => ({
      label: `${w.is_preset ? '🔒 ' : ''}${w.name}`,
      value: w.id,
    }))
    workflowOptions.value = [{ label: 'システムデフォルト', value: null }, ...options]
  } catch {
    // ワークフロー取得失敗は非致命的
  }
}

/**
 * ユーザー作成処理
 */
const handleCreate = async () => {
  const { valid } = await formRef.value.validate()
  if (!valid) return

  isSubmitting.value = true
  errorMessage.value = ''

  try {
    await createUser(form.value)
    successSnackbar.value = true
    setTimeout(() => router.push({ name: 'UserList' }), 1000)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || 'ユーザーの作成に失敗しました'
  } finally {
    isSubmitting.value = false
  }
}

onMounted(fetchWorkflows)
</script>
