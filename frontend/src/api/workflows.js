import apiClient from './index.js'

/**
 * ワークフロー定義API
 * ワークフロー定義のCRUDを行う
 */

/**
 * ワークフロー定義一覧取得
 * @returns {Promise} ワークフロー定義一覧
 */
export const getWorkflowDefinitions = () => {
  return apiClient.get('/api/v1/workflow_definitions')
}

/**
 * ワークフロー定義詳細取得
 * @param {number} id - ワークフロー定義ID
 * @returns {Promise} ワークフロー定義詳細
 */
export const getWorkflowDefinition = (id) => {
  return apiClient.get(`/api/v1/workflow_definitions/${id}`)
}

/**
 * ワークフロー定義作成
 * @param {Object} definitionData - ワークフロー定義データ
 * @param {string} definitionData.name - 名前
 * @param {string} definitionData.description - 説明
 * @param {Object} definitionData.graph_definition - グラフ定義
 * @param {Object} definitionData.agent_definition - エージェント定義
 * @param {Object} definitionData.prompt_definition - プロンプト定義
 * @returns {Promise} 作成されたワークフロー定義
 */
export const createWorkflowDefinition = (definitionData) => {
  return apiClient.post('/api/v1/workflow_definitions', definitionData)
}

/**
 * ワークフロー定義更新
 * @param {number} id - ワークフロー定義ID
 * @param {Object} definitionData - 更新するワークフロー定義データ
 * @returns {Promise} 更新されたワークフロー定義
 */
export const updateWorkflowDefinition = (id, definitionData) => {
  return apiClient.put(`/api/v1/workflow_definitions/${id}`, definitionData)
}

/**
 * ワークフロー定義削除
 * @param {number} id - ワークフロー定義ID
 * @returns {Promise}
 */
export const deleteWorkflowDefinition = (id) => {
  return apiClient.delete(`/api/v1/workflow_definitions/${id}`)
}
