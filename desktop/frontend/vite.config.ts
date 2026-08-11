import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the API runs separately on 8000; proxy /api and /font-file to it.
// (Font files are served by the backend from signer-core and the user's own
// upload folder, not from public/.)
// Prod: the backend serves the built frontend, so no proxy is needed.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/font-file': 'http://127.0.0.1:8000' } },
})
