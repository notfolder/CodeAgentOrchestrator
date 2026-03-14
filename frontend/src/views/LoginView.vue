<template>
  <v-app>
    <!-- ログイン画面（サイドメニューなし） -->
    <v-main class="bg-grey-lighten-3">
      <v-container class="fill-height" fluid>
        <v-row align="center" justify="center">
          <v-col cols="12" sm="8" md="5" lg="4">
            <!-- ログインカード -->
            <v-card elevation="4" rounded="lg">
              <v-card-title class="text-center py-6">
                <v-icon icon="mdi-robot" size="48" color="primary" class="mb-2" />
                <div class="text-h5 font-weight-bold">Coding Agent</div>
                <div class="text-subtitle-1 text-medium-emphasis">管理画面</div>
              </v-card-title>

              <v-card-text>
                <v-form ref="formRef" v-model="isFormValid" @submit.prevent="handleLogin">
                  <!-- メールアドレス入力 -->
                  <v-text-field
                    v-model="email"
                    label="メールアドレス"
                    type="email"
                    prepend-inner-icon="mdi-email"
                    variant="outlined"
                    :rules="emailRules"
                    class="mb-3"
                    required
                  />
                  <!-- パスワード入力 -->
                  <v-text-field
                    v-model="password"
                    label="パスワード"
                    :type="showPassword ? 'text' : 'password'"
                    prepend-inner-icon="mdi-lock"
                    :append-inner-icon="showPassword ? 'mdi-eye-off' : 'mdi-eye'"
                    variant="outlined"
                    :rules="passwordRules"
                    class="mb-4"
                    required
                    @click:append-inner="showPassword = !showPassword"
                  />

                  <!-- エラーメッセージ -->
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

                  <!-- ログインボタン -->
                  <v-btn
                    type="submit"
                    block
                    color="primary"
                    size="large"
                    :loading="isLoading"
                    :disabled="!isFormValid || isLoading"
                  >
                    ログイン
                  </v-btn>
                </v-form>
              </v-card-text>
            </v-card>
          </v-col>
        </v-row>
      </v-container>
    </v-main>
  </v-app>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

const router = useRouter()
const authStore = useAuthStore()

// フォームの状態管理
const formRef = ref(null)
const isFormValid = ref(false)
const email = ref('')
const password = ref('')
const showPassword = ref(false)
const isLoading = ref(false)
const errorMessage = ref('')

// バリデーションルール
const emailRules = [
  (v) => !!v || 'メールアドレスを入力してください',
  (v) => /.+@.+\..+/.test(v) || '有効なメールアドレスを入力してください',
]
const passwordRules = [
  (v) => !!v || 'パスワードを入力してください',
]

/**
 * ログイン処理
 * 認証ストアのloginを呼び出してダッシュボードへ遷移する
 */
const handleLogin = async () => {
  const { valid } = await formRef.value.validate()
  if (!valid) return

  isLoading.value = true
  errorMessage.value = ''

  try {
    await authStore.login(email.value, password.value)
    router.push({ name: 'Dashboard' })
  } catch (error) {
    if (error.response?.status === 401) {
      errorMessage.value = 'メールアドレスまたはパスワードが正しくありません'
    } else {
      errorMessage.value = 'ログインに失敗しました。しばらく経ってから再度お試しください'
    }
  } finally {
    isLoading.value = false
  }
}
</script>
