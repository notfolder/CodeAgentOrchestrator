<template>
  <div>
    <!-- ページタイトル -->
    <div class="d-flex align-center mb-4">
      <v-btn
        icon="mdi-arrow-left"
        variant="text"
        :to="{ name: 'UserSettings' }"
        class="mr-2"
      />
      <h1 class="text-h5 font-weight-bold">パスワード変更</h1>
    </div>

    <!-- エラー表示 -->
    <v-alert v-if="errorMessage" type="error" variant="tonal" class="mb-4" closable @click:close="errorMessage = ''">
      {{ errorMessage }}
    </v-alert>

    <v-row justify="center">
      <v-col cols="12" md="6">
        <v-card>
          <v-card-text>
            <v-form ref="formRef" v-model="isFormValid" @submit.prevent="handleChange">

              <!-- 現在のパスワード（ユーザー自身の場合のみ表示） -->
              <v-text-field
                v-model="form.current_password"
                label="現在のパスワード"
                :type="showCurrent ? 'text' : 'password'"
                :append-inner-icon="showCurrent ? 'mdi-eye-off' : 'mdi-eye'"
                prepend-inner-icon="mdi-lock-outline"
                variant="outlined"
                :rules="currentPasswordRules"
                class="mb-3"
                @click:append-inner="showCurrent = !showCurrent"
              />

              <!-- 新しいパスワード -->
              <v-text-field
                v-model="form.new_password"
                label="新しいパスワード *"
                :type="showNew ? 'text' : 'password'"
                :append-inner-icon="showNew ? 'mdi-eye-off' : 'mdi-eye'"
                prepend-inner-icon="mdi-lock"
                variant="outlined"
                :rules="newPasswordRules"
                class="mb-3"
                required
                @click:append-inner="showNew = !showNew"
              />

              <!-- 新しいパスワード確認 -->
              <v-text-field
                v-model="form.confirm_password"
                label="新しいパスワード（確認） *"
                :type="showConfirm ? 'text' : 'password'"
                :append-inner-icon="showConfirm ? 'mdi-eye-off' : 'mdi-eye'"
                prepend-inner-icon="mdi-lock-check"
                variant="outlined"
                :rules="confirmPasswordRules"
                class="mb-4"
                required
                @click:append-inner="showConfirm = !showConfirm"
              />

              <!-- パスワード要件表示 -->
              <v-alert type="info" variant="tonal" class="mb-4">
                <div class="font-weight-bold mb-1">パスワード要件</div>
                <ul>
                  <li>8文字以上</li>
                  <li>英字と数字を含むことを推奨</li>
                </ul>
              </v-alert>

              <!-- 操作ボタン -->
              <div class="d-flex justify-end gap-3">
                <v-btn
                  variant="outlined"
                  :to="{ name: 'UserSettings' }"
                  :disabled="isSubmitting"
                >
                  キャンセル
                </v-btn>
                <v-btn
                  type="submit"
                  color="primary"
                  :loading="isSubmitting"
                  :disabled="!isFormValid || isSubmitting"
                >
                  変更する
                </v-btn>
              </div>
            </v-form>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- 変更成功スナックバー -->
    <v-snackbar v-model="successSnackbar" color="success" timeout="3000">
      パスワードを変更しました
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { changePassword } from '../api/users.js'
import { useAuthStore } from '../stores/auth.js'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref(null)
const isFormValid = ref(false)
const isSubmitting = ref(false)
const errorMessage = ref('')
const successSnackbar = ref(false)
const showCurrent = ref(false)
const showNew = ref(false)
const showConfirm = ref(false)

// フォームデータ
const form = ref({
  current_password: '',
  new_password: '',
  confirm_password: '',
})

// バリデーションルール
const currentPasswordRules = [
  (v) => !!v || '現在のパスワードを入力してください',
]
const newPasswordRules = [
  (v) => !!v || '新しいパスワードを入力してください',
  (v) => v.length >= 8 || 'パスワードは8文字以上で入力してください',
]
const confirmPasswordRules = [
  (v) => !!v || '確認用パスワードを入力してください',
  (v) => v === form.value.new_password || '新しいパスワードと一致しません',
]

/**
 * パスワード変更処理
 */
const handleChange = async () => {
  const { valid } = await formRef.value.validate()
  if (!valid) return

  isSubmitting.value = true
  errorMessage.value = ''

  try {
    await changePassword(authStore.userEmail, {
      current_password: form.value.current_password,
      new_password: form.value.new_password,
    })
    successSnackbar.value = true
    // 成功後はユーザー設定画面へ戻る
    setTimeout(() => router.push({ name: 'UserSettings' }), 1500)
  } catch (error) {
    if (error.response?.status === 400) {
      errorMessage.value = '現在のパスワードが正しくありません'
    } else {
      errorMessage.value = error.response?.data?.detail || 'パスワードの変更に失敗しました'
    }
  } finally {
    isSubmitting.value = false
  }
}
</script>
