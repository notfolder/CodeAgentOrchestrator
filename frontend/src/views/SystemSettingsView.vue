<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-bold">システム設定</h1>
    </div>

    <!-- ローディング表示 -->
    <div v-if="isLoading" class="d-flex justify-center py-8">
      <v-progress-circular indeterminate color="primary" size="48" />
    </div>

    <!-- エラー表示 -->
    <v-alert
      v-if="errorMessage"
      type="error"
      variant="tonal"
      class="mb-4"
      closable
      @click:close="errorMessage = ''"
    >
      {{ errorMessage }}
    </v-alert>

    <!-- 保存成功メッセージ -->
    <v-alert
      v-if="successMessage"
      type="success"
      variant="tonal"
      class="mb-4"
      closable
      @click:close="successMessage = ''"
    >
      {{ successMessage }}
    </v-alert>

    <!-- 設定フォーム -->
    <v-card v-if="!isLoading">
      <v-card-title class="d-flex align-center">
        <v-icon icon="mdi-tune" class="mr-2" color="primary" />
        デフォルトワークフロー設定
      </v-card-title>
      <v-card-text>
        <p class="text-body-2 text-medium-emphasis mb-4">
          ユーザーがワークフローを設定していない場合に使用されるシステムデフォルトのワークフローを選択します。
        </p>
        <v-select
          v-model="selectedWorkflowId"
          :items="workflowOptions"
          item-title="label"
          item-value="id"
          label="デフォルトワークフロー"
          variant="outlined"
          :loading="isLoadingWorkflows"
          :disabled="isSaving"
        />
      </v-card-text>
      <v-card-actions class="px-4 pb-4">
        <v-spacer />
        <v-btn
          color="primary"
          variant="elevated"
          :loading="isSaving"
          :disabled="isLoading || isLoadingWorkflows"
          @click="handleSave"
        >
          保存
        </v-btn>
      </v-card-actions>
    </v-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { getSystemDefaultWorkflow, updateSystemDefaultWorkflow } from '../api/system.js'
import { getWorkflowDefinitions } from '../api/workflows.js'

// ローディング状態
const isLoading = ref(true)
const isLoadingWorkflows = ref(false)
const isSaving = ref(false)

// メッセージ
const errorMessage = ref('')
const successMessage = ref('')

// ワークフロー一覧とデフォルト選択値
const workflows = ref([])
const selectedWorkflowId = ref(null)

/**
 * ワークフロー選択肢（v-selectのitemsに渡す形式）
 */
const workflowOptions = computed(() =>
  workflows.value.map((wf) => ({
    id: wf.id,
    label: `${wf.id}: ${wf.name}`,
  }))
)

/**
 * ワークフロー定義一覧とシステムデフォルト設定を並行取得する
 */
const loadData = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const [workflowsRes, defaultRes] = await Promise.all([
      getWorkflowDefinitions(),
      getSystemDefaultWorkflow(),
    ])
    workflows.value = workflowsRes.data
    selectedWorkflowId.value = defaultRes.data.workflow_definition_id
  } catch (err) {
    errorMessage.value =
      err.response?.data?.detail ?? 'システム設定の読み込みに失敗しました。'
  } finally {
    isLoading.value = false
  }
}

/**
 * デフォルトワークフロー設定を保存する
 */
const handleSave = async () => {
  if (selectedWorkflowId.value === null) {
    errorMessage.value = 'ワークフローを選択してください。'
    return
  }
  isSaving.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    await updateSystemDefaultWorkflow(selectedWorkflowId.value)
    successMessage.value = 'システムデフォルトワークフローを保存しました。'
  } catch (err) {
    errorMessage.value =
      err.response?.data?.detail ?? 'システム設定の保存に失敗しました。'
  } finally {
    isSaving.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>
