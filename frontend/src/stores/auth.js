import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as loginApi, refresh as refreshApi } from '../api/auth.js'

/**
 * 認証ストア
 * JWTトークンの管理・ログイン・ログアウト・ユーザー情報を扱う
 */
export const useAuthStore = defineStore('auth', () => {
  // ローカルストレージからトークンとユーザー情報を復元
  const token = ref(localStorage.getItem('access_token') || null)
  const userEmail = ref(localStorage.getItem('user_email') || null)
  const userRole = ref(localStorage.getItem('user_role') || null)

  /** 認証済みかどうか */
  const isAuthenticated = computed(() => !!token.value)

  /** 管理者かどうか */
  const isAdmin = computed(() => userRole.value === 'admin')

  /**
   * ログイン処理
   * APIにアクセスしてJWTトークンを取得・保存する
   * @param {string} email - メールアドレス
   * @param {string} password - パスワード
   */
  const login = async (email, password) => {
    const response = await loginApi(email, password)
    const { access_token, user } = response.data

    // トークンとユーザー情報をローカルストレージに保存
    token.value = access_token
    userEmail.value = user?.email || email
    userRole.value = user?.role || null

    localStorage.setItem('access_token', access_token)
    localStorage.setItem('user_email', userEmail.value)
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
    userEmail.value = null
    userRole.value = null

    localStorage.removeItem('access_token')
    localStorage.removeItem('user_email')
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
    userEmail,
    userRole,
    isAuthenticated,
    isAdmin,
    login,
    logout,
    refreshToken,
  }
})
