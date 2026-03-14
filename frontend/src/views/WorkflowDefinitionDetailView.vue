<template>
  <div>
    <!-- ページタイトルと操作ボタン -->
    <div class="d-flex align-center justify-space-between mb-4">
      <div class="d-flex align-center">
        <v-btn
          icon="mdi-arrow-left"
          variant="text"
          :to="{ name: 'WorkflowDefinitionList' }"
          class="mr-2"
        />
        <h1 class="text-h5 font-weight-bold">ワークフロー定義詳細</h1>
      </div>
      <!-- ユーザー作成のワークフローのみ編集ボタンを表示 -->
      <v-btn
        v-if="workflow && !workflow.is_preset"
        color="primary"
        prepend-icon="mdi-pencil"
        :to="{ name: 'WorkflowDefinitionEdit', params: { id: props.id } }"
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

    <template v-if="!isLoading && workflow">
      <!-- 基本情報 -->
      <v-card class="mb-4">
        <v-card-title>基本情報</v-card-title>
        <v-card-text>
          <v-list density="compact">
            <v-list-item title="ID" :subtitle="workflow.id?.toString()" />
            <v-list-item title="名前" :subtitle="workflow.name" />
            <v-list-item title="説明" :subtitle="workflow.description || '-'" />
            <v-list-item title="種別">
              <template #subtitle>
                <v-chip :color="workflow.is_preset ? 'warning' : 'primary'" size="small" label>
                  <v-icon v-if="workflow.is_preset" icon="mdi-lock" size="small" class="mr-1" />
                  {{ workflow.is_preset ? 'システムプリセット' : 'ユーザー作成' }}
                </v-chip>
              </template>
            </v-list-item>
            <v-list-item title="作成日時" :subtitle="formatDate(workflow.created_at)" />
            <v-list-item title="更新日時" :subtitle="formatDate(workflow.updated_at)" />
          </v-list>
        </v-card-text>
      </v-card>

      <!-- グラフ定義 -->
      <v-card class="mb-4">
        <v-card-title>グラフ定義</v-card-title>
        <v-card-text>
          <pre class="json-block">{{ formatJson(workflow.graph_definition) }}</pre>
        </v-card-text>
      </v-card>

      <!-- エージェント定義 -->
      <v-card class="mb-4">
        <v-card-title>エージェント定義</v-card-title>
        <v-card-text>
          <pre class="json-block">{{ formatJson(workflow.agent_definition) }}</pre>
        </v-card-text>
      </v-card>

      <!-- プロンプト定義 -->
      <v-card>
        <v-card-title>プロンプト定義</v-card-title>
        <v-card-text>
          <pre class="json-block">{{ formatJson(workflow.prompt_definition) }}</pre>
        </v-card-text>
      </v-card>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getWorkflowDefinition } from '../api/workflows.js'

const props = defineProps({
  id: { type: String, required: true },
})

const isLoading = ref(true)
const errorMessage = ref('')
const workflow = ref(null)

/**
 * JSONオブジェクトを整形して文字列化する
 * @param {Object|null} obj
 * @returns {string}
 */
const formatJson = (obj) => {
  if (!obj) return '-'
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

/**
 * 日時を表示用にフォーマットする
 */
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('ja-JP')
}

/**
 * ワークフロー定義詳細を取得する
 */
const fetchWorkflow = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const res = await getWorkflowDefinition(props.id)
    workflow.value = res.data
  } catch {
    errorMessage.value = 'ワークフロー定義の取得に失敗しました'
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchWorkflow)
</script>

<style scoped>
/* JSONコードブロックのスタイル */
.json-block {
  background: #f5f5f5;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  padding: 12px;
  font-family: 'Courier New', Courier, monospace;
  font-size: 0.85em;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow-y: auto;
}
</style>
