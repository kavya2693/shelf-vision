import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api is proxied to the FastAPI twin in both `vite` and `vite preview`.
const proxy = { '/api': { target: 'http://127.0.0.1:8020', changeOrigin: true } }

export default defineConfig({
  plugins: [react()],
  base: './',
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
  build: { chunkSizeWarningLimit: 1500 },
})
