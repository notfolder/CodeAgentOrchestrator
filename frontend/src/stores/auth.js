import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as loginApi, refresh as refreshApi } from '../api/auth.js'

/**
 * JWTペイロードをデコードして返す（署名検証なし・表示用途のみ）
 * @param {string} token - JWTトークン文字列
 * @returns {Object|null} デコードされたペイロード
 */
const decodeJwtPayload = (token) => {
  try {
    // JWTはヘッダー.ペイロード.署名の3パーツ構成
    const payload = token.split('.')[1]
    // base64url → base64 に変換してデコード
    return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
  } catch {
    return null
  }
}

/**
 * 認証ストア
 * JWTトークンの管理・ログイン・ログアウト・ユーザー情報を扱う
 */
export const useAuthStore = defineStore('auth', () => {
  const storedToken = localStorage.getItem('access_token') || null

  // ローカルストレージからトークンとユーザー情報を復元
  // user_role が未保存の場合はトークンのペイロードからロールを復元する
  const token = ref(storedToken)
  const username = ref(localStorage.getItem('username') || null)
  const _storedRole = localStorage.getItem('user_role')
  const userRole = ref(_storedRole || (storedToken ? decodeJwtPayload(storedToken)?.role : null) || null)

  /** 認証済みかどうか */
  const isAuthenticated = computed(() => !!token.value)

  /** 管理者かどうか */
  const isAdmin = computed(() => userRole.value === 'admin')

  /**
   * ログイン処理
   * APIにアクセスしてJWTトークンを取得・保存する
   * @param {string} loginUsername - ユーザー名
   * @param {string} password - パスワード
   */
  const login = async (loginUsername, password) => {
    const response = await loginApi(loginUsername, password)
    const { access_token } = response.data

    // JWTペイロードからロールとユーザー名を取得する
    const payload = decodeJwtPayload(access_token)

    // トークンとユーザー情報をローカルストレージに保存
    token.value = access_token
    username.value = payload?.sub || loginUsername
    userRole.value = payload?.role || null

    localStorage.setItem('access_token', access_token)
    localStorage.setItem('username', username.value)
    if (userRole.value) {
      localStorage.setItem('user_role', userRole.value)
    }
  }

  /**
   * ログアウト処理
   * トークンとユーザー情報をクリアする
   */
  const logout = () => {
    token.value = null
    username.value = null
    userRole.value = null

    localStorage.removeItem('access_token')
    localStorage.removeItem('username')
    localStorage.removeItem('user_role')
  }

  /**
   * トークンリフレッシュ処理
   * 新しいトークンを取得してローカルストレージを更新する
   */
  const refreshToken = async () => {
    try {
      const response = await refreshApi()
      const { access_token } = response.data
      token.value = access_token
      localStorage.setItem('access_token', access_token)
    } catch {
      // リフレッシュ失敗時はログアウト
      logout()
    }
  }

  return {
    token,
    username,
    userRole,
    isAuthenticated,
    isAdmin,
    login,
    logout,
    refreshToken,
  }
})
