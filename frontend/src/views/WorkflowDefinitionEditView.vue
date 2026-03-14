<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center mb-4">
      <v-btn
        icon="mdi-arrow-left"
        variant="text"
        :to="{ name: 'WorkflowDefinitionDetail', params: { id: props.id } }"
        class="mr-2"
      />
      <h1 class="text-h5 font-weight-bold">ワークフロー定義編集</h1>
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
              <v-text-field
                v-model="form.name"
                label="名前 *"
                variant="outlined"
                :rules="[(v) => !!v || '名前を入力してください']"
                required
              />
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="form.description"
                label="説明"
                variant="outlined"
              />
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>

      <!-- グラフ定義JSONエディタ -->
      <v-card class="mb-4">
        <v-card-title>グラフ定義 (JSON)</v-card-title>
        <v-card-text>
          <v-textarea
            v-model="form.graph_definition_str"
            label="グラフ定義JSON"
            variant="outlined"
            rows="10"
            :rules="jsonRules"
            hint="有効なJSON形式で入力してください"
            persistent-hint
          />
        </v-card-text>
      </v-card>

      <!-- エージェント定義JSONエディタ -->
      <v-card class="mb-4">
        <v-card-title>エージェント定義 (JSON)</v-card-title>
        <v-card-text>
          <v-textarea
            v-model="form.agent_definition_str"
            label="エージェント定義JSON"
            variant="outlined"
            rows="10"
            :rules="jsonRules"
            hint="有効なJSON形式で入力してください"
            persistent-hint
          />
        </v-card-text>
      </v-card>

      <!-- プロンプト定義JSONエディタ -->
      <v-card class="mb-4">
        <v-card-title>プロンプト定義 (JSON)</v-card-title>
        <v-card-text>
          <v-textarea
            v-model="form.prompt_definition_str"
            label="プロンプト定義JSON"
            variant="outlined"
            rows="10"
            :rules="jsonRules"
            hint="有効なJSON形式で入力してください"
            persistent-hint
          />
        </v-card-text>
      </v-card>

      <!-- 操作ボタン -->
      <div class="d-flex justify-end gap-3">
        <v-btn
          variant="outlined"
          :to="{ name: 'WorkflowDefinitionDetail', params: { id: props.id } }"
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
      ワークフロー定義を更新しました
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getWorkflowDefinition, updateWorkflowDefinition } from '../api/workflows.js'

const props = defineProps({
  id: { type: String, required: true },
})

const router = useRouter()

const formRef = ref(null)
const isFormValid = ref(false)
const isLoading = ref(true)
const isSubmitting = ref(false)
const errorMessage = ref('')
const successSnackbar = ref(false)

// フォームデータ
const form = ref({
  name: '',
  description: '',
  graph_definition_str: '{}',
  agent_definition_str: '{}',
  prompt_definition_str: '{}',
})

// JSONバリデーションルール
const jsonRules = [
  (v) => {
    if (!v) return true
    try {
      JSON.parse(v)
      return true
    } catch {
      return '有効なJSON形式で入力してください'
    }
  },
]

/**
 * ワークフロー定義詳細を取得してフォームに反映する
 */
const fetchWorkflow = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const res = await getWorkflowDefinition(props.id)
    const wf = res.data

    // プリセットは編集不可
    if (wf.is_preset) {
      errorMessage.value = 'システムプリセットは編集できません'
      return
    }

    form.value.name = wf.name
    form.value.description = wf.description || ''
    form.value.graph_definition_str = JSON.stringify(wf.graph_definition, null, 2)
    form.value.agent_definition_str = JSON.stringify(wf.agent_definition, null, 2)
    form.value.prompt_definition_str = JSON.stringify(wf.prompt_definition, null, 2)
  } catch {
    errorMessage.value = 'ワークフロー定義の取得に失敗しました'
  } finally {
    isLoading.value = false
  }
}

/**
 * ワークフロー定義を保存する
 */
const handleSave = async () => {
  const { valid } = await formRef.value.validate()
  if (!valid) return

  isSubmitting.value = true
  errorMessage.value = ''

  try {
    const payload = {
      name: form.value.name,
      description: form.value.description,
      graph_definition: JSON.parse(form.value.graph_definition_str || '{}'),
      agent_definition: JSON.parse(form.value.agent_definition_str || '{}'),
      prompt_definition: JSON.parse(form.value.prompt_definition_str || '{}'),
    }

    await updateWorkflowDefinition(props.id, payload)
    successSnackbar.value = true
    setTimeout(() => router.push({ name: 'WorkflowDefinitionDetail', params: { id: props.id } }), 1000)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || 'ワークフロー定義の更新に失敗しました'
  } finally {
    isSubmitting.value = false
  }
}

onMounted(fetchWorkflow)
</script>
