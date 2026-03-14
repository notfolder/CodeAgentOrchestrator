<template>
  <div>
    <!-- ページタイトルと新規作成ボタン -->
    <div class="d-flex align-center justify-space-between mb-4">
      <h1 class="text-h5 font-weight-bold">ワークフロー定義一覧</h1>
      <v-btn
        color="primary"
        prepend-icon="mdi-plus"
        :to="{ name: 'WorkflowDefinitionCreate' }"
      >
        新規作成
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

    <template v-if="!isLoading">
      <!-- システムプリセット一覧 -->
      <v-card class="mb-4">
        <v-card-title class="d-flex align-center">
          <v-icon icon="mdi-lock" class="mr-2" color="warning" />
          システムプリセット
        </v-card-title>
        <v-card-text>
          <v-table v-if="presetWorkflows.length > 0">
            <thead>
              <tr>
                <th>ID</th>
                <th>名前</th>
                <th>説明</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="wf in presetWorkflows" :key="wf.id">
                <td>{{ wf.id }}</td>
                <td>
                  <v-icon icon="mdi-lock" size="small" color="warning" class="mr-1" />
                  {{ wf.name }}
                </td>
                <td>{{ wf.description }}</td>
                <td>
                  <v-btn
                    size="small"
                    variant="text"
                    icon="mdi-eye"
                    :to="{ name: 'WorkflowDefinitionDetail', params: { id: wf.id } }"
                    title="詳細"
                  />
                </td>
              </tr>
            </tbody>
          </v-table>
          <div v-else class="text-center text-medium-emphasis py-4">
            システムプリセットがありません
          </div>
        </v-card-text>
      </v-card>

      <!-- ユーザー作成ワークフロー一覧 -->
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon icon="mdi-sitemap" class="mr-2" color="primary" />
          ユーザー作成ワークフロー
        </v-card-title>
        <v-card-text>
          <v-table v-if="userWorkflows.length > 0">
            <thead>
              <tr>
                <th>ID</th>
                <th>名前</th>
                <th>説明</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="wf in userWorkflows" :key="wf.id">
                <td>{{ wf.id }}</td>
                <td>{{ wf.name }}</td>
                <td>{{ wf.description }}</td>
                <td>
                  <v-btn
                    size="small"
                    variant="text"
                    icon="mdi-eye"
                    :to="{ name: 'WorkflowDefinitionDetail', params: { id: wf.id } }"
                    title="詳細"
                  />
                  <v-btn
                    size="small"
                    variant="text"
                    icon="mdi-pencil"
                    :to="{ name: 'WorkflowDefinitionEdit', params: { id: wf.id } }"
                    title="編集"
                  />
                  <v-btn
                    size="small"
                    variant="text"
                    icon="mdi-delete"
                    color="error"
                    title="削除"
                    @click="openDeleteDialog(wf)"
                  />
                </td>
              </tr>
            </tbody>
          </v-table>
          <div v-else class="text-center text-medium-emphasis py-4">
            ユーザー作成ワークフローがありません
          </div>
        </v-card-text>
      </v-card>
    </template>

    <!-- 削除確認ダイアログ -->
    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card>
        <v-card-title>ワークフロー削除の確認</v-card-title>
        <v-card-text>
          「{{ deleteTarget?.name }}」を削除しますか？この操作は取り消せません。
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="deleteDialog = false">キャンセル</v-btn>
          <v-btn
            color="error"
            variant="flat"
            :loading="isDeleting"
            @click="handleDelete"
          >
            削除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 削除成功スナックバー -->
    <v-snackbar v-model="successSnackbar" color="success" timeout="3000">
      ワークフロー定義を削除しました
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getWorkflowDefinitions, deleteWorkflowDefinition } from '../api/workflows.js'

const isLoading = ref(true)
const isDeleting = ref(false)
const errorMessage = ref('')
const workflows = ref([])
const deleteDialog = ref(false)
const deleteTarget = ref(null)
const successSnackbar = ref(false)

// システムプリセット
const presetWorkflows = computed(() => workflows.value.filter((w) => w.is_preset))
// ユーザー作成ワークフロー
const userWorkflows = computed(() => workflows.value.filter((w) => !w.is_preset))

/**
 * 削除確認ダイアログを開く
 * @param {Object} wf - 削除対象のワークフロー
 */
const openDeleteDialog = (wf) => {
  deleteTarget.value = wf
  deleteDialog.value = true
}

/**
 * ワークフロー定義を削除する
 */
const handleDelete = async () => {
  if (!deleteTarget.value) return
  isDeleting.value = true
  try {
    await deleteWorkflowDefinition(deleteTarget.value.id)
    workflows.value = workflows.value.filter((w) => w.id !== deleteTarget.value.id)
    deleteDialog.value = false
    successSnackbar.value = true
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || 'ワークフロー定義の削除に失敗しました'
    deleteDialog.value = false
  } finally {
    isDeleting.value = false
    deleteTarget.value = null
  }
}

/**
 * ワークフロー定義一覧を取得する
 */
const fetchWorkflows = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const res = await getWorkflowDefinitions()
    workflows.value = res.data || []
  } catch {
    errorMessage.value = 'ワークフロー定義の取得に失敗しました'
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchWorkflows)
</script>
