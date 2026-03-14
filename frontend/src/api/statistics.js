import apiClient from './index.js'

/**
 * 統計API
 * トークン使用量・ダッシュボード統計・タスク履歴を取得する
 */

/**
 * ダッシュボード統計取得
 * @returns {Promise} 登録ユーザー数・実行中タスク数・今月トークン使用量など
 */
export const getDashboardStats = () => {
  return apiClient.get('/api/v1/dashboard/stats')
}

/**
 * トークン使用量統計取得
 * @param {Object} params - クエリパラメータ
 * @param {string} [params.email] - 特定ユーザーのメールアドレス（省略時は全ユーザー）
 * @param {number} [params.days] - 集計期間（日数: 7, 30, 90）
 * @returns {Promise} ユーザー別トークン使用量統計
 */
export const getTokenUsageStats = (params = {}) => {
  return apiClient.get('/api/v1/statistics/tokens', { params })
}

/**
 * タスク実行履歴取得
 * @param {Object} params - クエリパラメータ
 * @param {string} [params.email] - ユーザーフィルタ
 * @param {string} [params.status] - ステータスフィルタ
 * @param {string} [params.task_type] - タスク種別フィルタ
 * @param {string} [params.started_after] - 開始日時フィルタ（ISO8601）
 * @param {string} [params.started_before] - 終了日時フィルタ（ISO8601）
 * @param {number} [params.page] - ページ番号
 * @param {number} [params.per_page] - 1ページあたりの件数
 * @returns {Promise} タスク実行履歴一覧
 */
export const getTaskHistory = (params = {}) => {
  return apiClient.get('/api/v1/tasks', { params })
}
