import apiClient from './index.js'

/**
 * ユーザーAPI
 * ユーザーCRUD・設定取得・パスワード変更・ワークフロー設定を行う
 */

/**
 * ユーザー一覧取得 (Admin権限必要)
 * @returns {Promise} ユーザー一覧
 */
export const getUsers = () => {
  return apiClient.get('/api/v1/users')
}

/**
 * ユーザー設定取得
 * @param {string} email - メールアドレス
 * @returns {Promise} ユーザー設定
 */
export const getUserConfig = (email) => {
  return apiClient.get(`/api/v1/config/${encodeURIComponent(email)}`)
}

/**
 * ユーザー作成 (Admin権限必要)
 * @param {Object} userData - ユーザー情報とLLM設定
 * @returns {Promise} 作成されたユーザー
 */
export const createUser = (userData) => {
  return apiClient.post('/api/v1/users', userData)
}

/**
 * ユーザー更新
 * @param {string} email - メールアドレス
 * @param {Object} userData - 更新するユーザー情報
 * @returns {Promise} 更新されたユーザー
 */
export const updateUser = (email, userData) => {
  return apiClient.put(`/api/v1/users/${encodeURIComponent(email)}`, userData)
}

/**
 * パスワード変更
 * @param {string} email - メールアドレス
 * @param {Object} passwordData - パスワード変更データ
 * @param {string} passwordData.new_password - 新しいパスワード
 * @param {string} [passwordData.current_password] - 現在のパスワード（ユーザー自身が変更する場合）
 * @returns {Promise}
 */
export const changePassword = (email, passwordData) => {
  return apiClient.put(`/api/v1/users/${encodeURIComponent(email)}/password`, passwordData)
}

/**
 * ユーザーのワークフロー設定取得
 * @param {number} userId - ユーザーID
 * @returns {Promise} ワークフロー設定
 */
export const getUserWorkflowSetting = (userId) => {
  return apiClient.get(`/api/v1/users/${userId}/workflow_setting`)
}

/**
 * ユーザーのワークフロー設定更新
 * @param {number} userId - ユーザーID
 * @param {Object} settingData - ワークフロー設定
 * @param {number} settingData.workflow_definition_id - ワークフロー定義ID
 * @returns {Promise} 更新されたワークフロー設定
 */
export const updateUserWorkflowSetting = (userId, settingData) => {
  return apiClient.put(`/api/v1/users/${userId}/workflow_setting`, settingData)
}
