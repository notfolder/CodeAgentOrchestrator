import apiClient from './index.js'

/**
 * システム設定API
 * システム全体のデフォルト設定を管理する
 */

/**
 * システムデフォルトワークフロー設定を取得する
 * @returns {Promise} { workflow_definition_id: number }
 */
export const getSystemDefaultWorkflow = () => {
  return apiClient.get('/api/v1/system/settings/default_workflow')
}

/**
 * システムデフォルトワークフロー設定を更新する
 * @param {number} workflowDefinitionId - 設定するワークフロー定義ID
 * @returns {Promise} 更新後の設定
 */
export const updateSystemDefaultWorkflow = (workflowDefinitionId) => {
  return apiClient.put('/api/v1/system/settings/default_workflow', {
    workflow_definition_id: workflowDefinitionId,
  })
}
