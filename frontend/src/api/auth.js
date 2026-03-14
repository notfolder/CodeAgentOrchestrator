import apiClient from './index.js'

/**
 * 認証API
 * JWT取得・リフレッシュを行う
 */

/**
 * ログイン
 * @param {string} email - メールアドレス
 * @param {string} password - パスワード
 * @returns {Promise} アクセストークンを含むレスポンス
 */
export const login = (email, password) => {
  return apiClient.post('/api/v1/auth/login', { email, password })
}

/**
 * トークンリフレッシュ
 * @returns {Promise} 新しいアクセストークンを含むレスポンス
 */
export const refresh = () => {
  return apiClient.post('/api/v1/auth/refresh')
}
