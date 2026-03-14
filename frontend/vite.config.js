import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // Vuetifyのオートインポート設定
    vuetify({ autoImport: true }),
  ],
  server: {
    port: 3000,
    // バックエンドAPIへのプロキシ設定
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': '/src',
    },
  },
})
