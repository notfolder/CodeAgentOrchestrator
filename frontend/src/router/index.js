import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

// 各画面コンポーネントの遅延ロード設定
const LoginView = () => import('../views/LoginView.vue')
const DashboardView = () => import('../views/DashboardView.vue')
const UserListView = () => import('../views/UserListView.vue')
const UserDetailView = () => import('../views/UserDetailView.vue')
const UserCreateView = () => import('../views/UserCreateView.vue')
const UserEditView = () => import('../views/UserEditView.vue')
const WorkflowDefinitionListView = () => import('../views/WorkflowDefinitionListView.vue')
const WorkflowDefinitionDetailView = () => import('../views/WorkflowDefinitionDetailView.vue')
const WorkflowDefinitionCreateView = () => import('../views/WorkflowDefinitionCreateView.vue')
const WorkflowDefinitionEditView = () => import('../views/WorkflowDefinitionEditView.vue')
const TokenUsageView = () => import('../views/TokenUsageView.vue')
const TaskHistoryView = () => import('../views/TaskHistoryView.vue')
const UserSettingsView = () => import('../views/UserSettingsView.vue')
const PasswordChangeView = () => import('../views/PasswordChangeView.vue')
const AppLayout = () => import('../components/AppLayout.vue')

const routes = [
  // SC-01: ログイン画面（認証不要）
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { requiresAuth: false },
  },
  // 認証必須の画面群（AppLayoutで囲む）
  {
    path: '/',
    component: AppLayout,
    meta: { requiresAuth: true },
    children: [
      // SC-02: ダッシュボード
      {
        path: '',
        name: 'Dashboard',
        component: DashboardView,
      },
      // SC-03: ユーザー一覧
      {
        path: 'users',
        name: 'UserList',
        component: UserListView,
      },
      // SC-05: ユーザー作成 (/users/new は /users/:id より先に定義する必要あり)
      {
        path: 'users/new',
        name: 'UserCreate',
        component: UserCreateView,
      },
      // SC-04: ユーザー詳細
      {
        path: 'users/:id',
        name: 'UserDetail',
        component: UserDetailView,
        props: true,
      },
      // SC-06: ユーザー編集
      {
        path: 'users/:id/edit',
        name: 'UserEdit',
        component: UserEditView,
        props: true,
      },
      // SC-07: ワークフロー定義一覧
      {
        path: 'workflows',
        name: 'WorkflowDefinitionList',
        component: WorkflowDefinitionListView,
      },
      // SC-09: ワークフロー定義作成 (/workflows/new は /workflows/:id より先に定義)
      {
        path: 'workflows/new',
        name: 'WorkflowDefinitionCreate',
        component: WorkflowDefinitionCreateView,
      },
      // SC-08: ワークフロー定義詳細
      {
        path: 'workflows/:id',
        name: 'WorkflowDefinitionDetail',
        component: WorkflowDefinitionDetailView,
        props: true,
      },
      // SC-10: ワークフロー定義編集
      {
        path: 'workflows/:id/edit',
        name: 'WorkflowDefinitionEdit',
        component: WorkflowDefinitionEditView,
        props: true,
      },
      // SC-11: トークン使用量統計
      {
        path: 'statistics/tokens',
        name: 'TokenUsage',
        component: TokenUsageView,
      },
      // SC-12: タスク実行履歴
      {
        path: 'tasks',
        name: 'TaskHistory',
        component: TaskHistoryView,
      },
      // SC-13: ユーザー設定
      {
        path: 'settings',
        name: 'UserSettings',
        component: UserSettingsView,
      },
      // SC-14: パスワード変更
      {
        path: 'settings/password',
        name: 'PasswordChange',
        component: PasswordChangeView,
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ナビゲーションガード: 認証チェック
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  const requiresAuth = to.meta.requiresAuth !== false

  if (requiresAuth && !authStore.isAuthenticated) {
    // 未認証の場合はログインページへリダイレクト
    next({ name: 'Login' })
  } else if (to.name === 'Login' && authStore.isAuthenticated) {
    // 認証済みでログインページにアクセスした場合はダッシュボードへ
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})

export default router
