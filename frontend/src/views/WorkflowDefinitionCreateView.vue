<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center mb-4">
      <v-btn
        icon="mdi-arrow-left"
        variant="text"
        :to="{ name: 'WorkflowDefinitionList' }"
        class="mr-2"
      />
      <h1 class="text-h5 font-weight-bold">ワークフロー定義作成</h1>
    </div>

    <!-- エラー表示 -->
    <v-alert v-if="errorMessage" type="error" variant="tonal" class="mb-4" closable @click:close="errorMessage = ''">
      {{ errorMessage }}
    </v-alert>

    <!-- システムプリセットから複製 -->
    <v-card class="mb-4">
      <v-card-title>システムプリセットから複製</v-card-title>
      <v-card-text>
        <v-row align="center">
          <v-col cols="12" md="6">
            <v-select
              v-model="selectedPreset"
              label="プリセットを選択"
              :items="presetOptions"
              item-title="label"
              item-value="value"
              variant="outlined"
              density="compact"
              hide-details
            />
          </v-col>
          <v-col cols="auto">
            <v-btn
              color="secondary"
              :disabled="!selectedPreset"
              prepend-icon="mdi-content-copy"
              @click="copyFromPreset"
            >
              複製
            </v-btn>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <v-form ref="formRef" v-model="isFormValid" @submit.prevent="handleCreate">
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
            font-family="monospace"
            hint="有効なJSON形式で入力してください"
            persistent-hint
          />
          <!-- Mermaid フローチャートプレビュー -->
          <MermaidPreview :graph-definition="parsedGraphDef" class="mt-4" />
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
          :to="{ name: 'WorkflowDefinitionList' }"
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
      ワークフロー定義を作成しました
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getWorkflowDefinitions, createWorkflowDefinition } from '../api/workflows.js'
import MermaidPreview from '../components/MermaidPreview.vue'

const router = useRouter()

const formRef = ref(null)
const isFormValid = ref(false)
const isSubmitting = ref(false)
const errorMessage = ref('')
const successSnackbar = ref(false)
const selectedPreset = ref(null)
const presetOptions = ref([])
const presets = ref([])

// フォームデータ
const form = ref({
  name: '',
  description: '',
  graph_definition_str: '{}',
  agent_definition_str: '{}',
  prompt_definition_str: '{}',
})

/**
 * graph_definition_str をパースしたオブジェクトを返す computed。
 * JSON 不正時は null を返し、MermaidPreview がプレースホルダを表示する。
 */
const parsedGraphDef = computed(() => {
  try {
    return JSON.parse(form.value.graph_definition_str || '{}')
  } catch {
    return null
  }
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
 * 選択したプリセットのJSONをフォームにコピーする
 */
const copyFromPreset = () => {
  const preset = presets.value.find((p) => p.id === selectedPreset.value)
  if (!preset) return

  form.value.graph_definition_str = JSON.stringify(preset.graph_definition, null, 2)
  form.value.agent_definition_str = JSON.stringify(preset.agent_definition, null, 2)
  form.value.prompt_definition_str = JSON.stringify(preset.prompt_definition, null, 2)
}

/**
 * ワークフロー定義を作成する
 */
const handleCreate = async () => {
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

    await createWorkflowDefinition(payload)
    successSnackbar.value = true
    setTimeout(() => router.push({ name: 'WorkflowDefinitionList' }), 1000)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || 'ワークフロー定義の作成に失敗しました'
  } finally {
    isSubmitting.value = false
  }
}

/**
 * プリセット一覧を取得してプルダウン用選択肢を生成する
 */
const fetchPresets = async () => {
  try {
    const res = await getWorkflowDefinitions()
    const allWorkflows = res.data || []
    presets.value = allWorkflows.filter((w) => w.is_preset)
    presetOptions.value = presets.value.map((p) => ({
      label: p.name,
      value: p.id,
    }))
  } catch {
    // プリセット取得失敗は非致命的
  }
}

onMounted(fetchPresets)
</script>
