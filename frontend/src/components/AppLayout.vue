<template>
  <v-app>
    <!-- サイドナビゲーションドロワー -->
    <v-navigation-drawer v-model="drawer" :rail="rail" permanent>
      <!-- アプリケーション名 -->
      <v-list-item
        prepend-icon="mdi-robot"
        title="Coding Agent"
        nav
      >
        <template #append>
          <v-btn
            :icon="rail ? 'mdi-chevron-right' : 'mdi-chevron-left'"
            variant="text"
            @click="rail = !rail"
          />
        </template>
      </v-list-item>

      <v-divider />

      <!-- ナビゲーションメニュー -->
      <v-list density="compact" nav>
        <v-list-item
          prepend-icon="mdi-view-dashboard"
          title="ダッシュボード"
          :to="{ name: 'Dashboard' }"
          value="dashboard"
        />
        <v-list-item
          prepend-icon="mdi-account-group"
          title="ユーザー管理"
          :to="{ name: 'UserList' }"
          value="users"
          v-if="authStore.isAdmin"
        />
        <v-list-item
          prepend-icon="mdi-sitemap"
          title="ワークフロー管理"
          :to="{ name: 'WorkflowDefinitionList' }"
          value="workflows"
        />
        <v-list-item
          prepend-icon="mdi-chart-bar"
          title="統計"
          :to="{ name: 'TokenUsage' }"
          value="statistics"
        />
        <v-list-item
          prepend-icon="mdi-history"
          title="タスク履歴"
          :to="{ name: 'TaskHistory' }"
          value="tasks"
        />
        <v-list-item
          prepend-icon="mdi-tune"
          title="システム設定"
          :to="{ name: 'SystemSettings' }"
          value="system-settings"
          v-if="authStore.isAdmin"
        />
      </v-list>
    </v-navigation-drawer>

    <!-- ヘッダーアプリバー -->
    <v-app-bar elevation="1">
      <v-app-bar-title>Coding Agent 管理画面</v-app-bar-title>
      <template #append>
        <!-- 設定メニュー（ユーザーメール表示） -->
        <v-menu>
          <template #activator="{ props }">
            <v-btn
              v-bind="props"
              variant="text"
              :prepend-icon="'mdi-account-circle'"
            >
              {{ authStore.username }}
            </v-btn>
          </template>
          <v-list>
            <v-list-item
              prepend-icon="mdi-cog"
              title="ユーザー設定"
              :to="{ name: 'UserSettings' }"
            />
            <v-list-item
              prepend-icon="mdi-lock-reset"
              title="パスワード変更"
              :to="{ name: 'PasswordChange' }"
            />
            <v-divider />
            <v-list-item
              prepend-icon="mdi-logout"
              title="ログアウト"
              @click="handleLogout"
            />
          </v-list>
        </v-menu>
      </template>
    </v-app-bar>

    <!-- メインコンテンツエリア -->
    <v-main>
      <v-container fluid class="pa-4">
        <router-view />
      </v-container>
    </v-main>
  </v-app>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

// サイドナビゲーションの表示状態
const drawer = ref(true)
// レール（折りたたみ）モード
const rail = ref(false)

const authStore = useAuthStore()
const router = useRouter()

/**
 * ログアウト処理
 * 認証ストアをクリアしてログインページへ遷移する
 */
const handleLogout = () => {
  authStore.logout()
  router.push({ name: 'Login' })
}
</script>
