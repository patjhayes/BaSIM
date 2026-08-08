import { defineConfig } from 'vite'
import { resolve } from 'node:path'

export default defineConfig({
  envDir: resolve(import.meta.dirname, '..'),
  build: {
    rollupOptions: {
      input: {
        app: resolve(import.meta.dirname, 'index.html'),
        billing: resolve(import.meta.dirname, 'billing.html'),
        help: resolve(import.meta.dirname, 'help.html'),
        login: resolve(import.meta.dirname, 'login.html'),
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
