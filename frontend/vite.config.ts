import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: process.env.KAVACH_API_PROXY_TARGET || 'http://127.0.0.1:8001', changeOrigin: true },
      '/geojson': { target: process.env.KAVACH_API_PROXY_TARGET || 'http://127.0.0.1:8001', changeOrigin: true },
      '/weather': { target: process.env.KAVACH_API_PROXY_TARGET || 'http://127.0.0.1:8001', changeOrigin: true },
      '/route': { target: process.env.KAVACH_API_PROXY_TARGET || 'http://127.0.0.1:8001', changeOrigin: true },
      '/simulate': { target: process.env.KAVACH_API_PROXY_TARGET || 'http://127.0.0.1:8001', changeOrigin: true },
    },
  },
})
