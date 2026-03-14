import axios from 'axios'
import { useAuthStore } from '../stores/auth.js'

// AxiosインスタンスのベースURL設定
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// リクエストインターセプター: JWTトークンをAuthorizationヘッダーに自動付与
apiClient.interceptors.request.use(
  (config) => {
    const authStore = useAuthStore()
    if (authStore.token) {
      config.headers.Authorization = `Bearer ${authStore.token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// レスポンスインターセプター: 401エラー時は自動ログアウト
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const authStore = useAuthStore()
      authStore.logout()
      // ログインページへリダイレクト（Vue Routerのインスタンスを直接使わずwindowで対応）
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default apiClient
