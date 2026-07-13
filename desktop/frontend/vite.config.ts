import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the API runs separately on 8000; proxy /api to it.
// Prod: the backend serves the built frontend, so no proxy is needed.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
})
