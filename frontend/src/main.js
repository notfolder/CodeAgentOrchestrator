import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import router from './router/index.js'
import App from './App.vue'

// Vuetify CSSのインポート
import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'

// Vuetifyインスタンスの生成（日本語ロケール対応）
const vuetify = createVuetify({
  components,
  directives,
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi },
  },
  theme: {
    defaultTheme: 'light',
    themes: {
      light: {
        colors: {
          primary: '#1976D2',
          secondary: '#424242',
          accent: '#82B1FF',
          error: '#FF5252',
          info: '#2196F3',
          success: '#4CAF50',
          warning: '#FFC107',
        },
      },
    },
  },
})

// Piniaインスタンスの生成
const pinia = createPinia()

// Vueアプリケーションの生成とプラグイン登録
const app = createApp(App)
app.use(pinia)
app.use(router)
app.use(vuetify)
app.mount('#app')
